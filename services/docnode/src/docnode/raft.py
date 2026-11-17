"""Fixed-membership Raft with SQLite durability and replay of committed commands.

Consensus state is confined to the asyncio event loop. SQLite transactions finish
before replies. Network calls never hold a state lock. Each peer has one sender.
See Ongaro and Ousterhout, extended Raft paper, Figure 2 and section 8.
"""
import asyncio
import hashlib
import logging
import random
import sqlite3
import time
from pathlib import Path

import grpc
from collab.v1 import document_pb2, raft_pb2 as pb, raft_pb2_grpc as rpc
from .convert import batch_from_proto, operation_to_proto, committed_to_proto
from .oplog import NotLeader
from .statemachine import ApplyError

log = logging.getLogger("raft")


class RaftLog(rpc.RaftServiceServicer):
    def __init__(self, address, peers, directory, sm):
        self.address, self.peers, self.sm = address, peers, sm
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(directory) / "raft.sqlite"))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), term INTEGER, vote TEXT, committed INTEGER)")
        self.db.execute("CREATE TABLE IF NOT EXISTS entries (idx INTEGER PRIMARY KEY, term INTEGER, command BLOB)")
        self.db.execute("INSERT OR IGNORE INTO state VALUES (1,0,'',0)")
        self.db.execute("CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), configuration TEXT)")
        configuration = "|".join([address, *sorted(peers)])
        saved = self.db.execute("SELECT configuration FROM identity WHERE id=1").fetchone()
        if saved and saved[0] != configuration:
            self.db.close()
            raise ValueError("data directory belongs to a different voter or membership")
        self.db.execute("INSERT OR IGNORE INTO identity VALUES (1,?)", (configuration,))
        self.db.commit()
        self.term, self.vote, self.commit = self.db.execute("SELECT term,vote,committed FROM state").fetchone()
        self.entries = [pb.Entry(term=0)] + [
            pb.Entry(term=t, command=c) for t,c in self.db.execute("SELECT term,command FROM entries ORDER BY idx")
        ]
        self.role, self.leader, self.applied = "follower", "", 0
        self.pending = {}
        self.channels = {p: grpc.aio.insecure_channel(p, options=[
            ("grpc.initial_reconnect_backoff_ms", 100),
            ("grpc.min_reconnect_backoff_ms", 100),
            ("grpc.max_reconnect_backoff_ms", 500)]) for p in peers}
        self.stubs = {p: rpc.RaftServiceStub(ch) for p,ch in self.channels.items()}
        self.locks = {p: asyncio.Lock() for p in peers}
        self.tasks = set()
        self.next_index, self.match = {}, {}
        self.contacts = {}
        self.elected_at = 0.0
        self.reset_timer()
        self.apply_committed()

    def reset_timer(self):
        self.deadline = time.monotonic() + random.uniform(0.8, 1.4)

    def persist(self):
        with self.db:
            self.db.execute("UPDATE state SET term=?,vote=?,committed=? WHERE id=1",
                            (self.term, self.vote, self.commit))

    def step_down(self, term, leader=""):
        if term > self.term:
            self.term, self.vote = term, ""
        self.role, self.leader = "follower", leader
        self.persist()
        self.reset_timer()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(NotLeader(leader))
        self.pending.clear()

    def append_local(self, entry):
        index = len(self.entries)
        with self.db:
            self.db.execute("INSERT INTO entries VALUES (?,?,?)", (index, entry.term, entry.command))
        self.entries.append(entry)
        return index

    def apply_committed(self):
        while self.applied < self.commit:
            self.applied += 1
            entry = self.entries[self.applied]
            result = None
            if entry.command:
                request = document_pb2.SubmitOperationsRequest.FromString(entry.command)
                try:
                    result = self.sm.apply(batch_from_proto(request.doc_id, request.operations))
                except ApplyError as error:
                    result = error
            future = self.pending.pop(self.applied, None)
            if future is not None and not future.done():
                if isinstance(result, Exception):
                    future.set_exception(result)
                else:
                    future.set_result(result)

    async def RequestVote(self, request, context):
        if request.term > self.term:
            self.step_down(request.term)
        fresh = (request.last_term, request.last_index) >= (self.entries[-1].term, len(self.entries)-1)
        granted = request.term == self.term and fresh and self.vote in ("", request.candidate)
        if granted:
            self.vote = request.candidate
            self.persist()
            self.reset_timer()
        return pb.VoteReply(term=self.term, granted=granted)

    async def AppendEntries(self, request, context):
        if request.term < self.term:
            return pb.AppendReply(term=self.term)
        if self.role != "follower" or request.term > self.term:
            self.step_down(request.term, request.leader)
        self.leader = request.leader
        self.reset_timer()
        if request.prev_index >= len(self.entries) or self.entries[request.prev_index].term != request.prev_term:
            return pb.AppendReply(term=self.term)
        start = request.prev_index + 1
        for offset, entry in enumerate(request.entries):
            index = start + offset
            if index < len(self.entries) and self.entries[index].term != entry.term:
                if index <= self.commit:
                    await context.abort(grpc.StatusCode.INTERNAL, "attempt to replace committed entry")
                with self.db:
                    self.db.execute("DELETE FROM entries WHERE idx>=?", (index,))
                del self.entries[index:]
            if index == len(self.entries):
                self.append_local(entry)
        # Only the prefix established by this RPC can become committed.
        matched = request.prev_index + len(request.entries)
        if request.commit > self.commit:
            self.commit = max(self.commit, min(request.commit, matched))
            self.persist()
            self.apply_committed()
        return pb.AppendReply(term=self.term, success=True, match_index=matched)

    async def Status(self, request, context):
        text, revision = self.sm.snapshot(request.doc_id)
        digest = hashlib.sha256(text.encode("utf-8"))
        for c in self.sm.history(request.doc_id, 0):
            digest.update(committed_to_proto(c).SerializeToString(deterministic=True))
        return pb.StatusReply(node=self.address, role=self.role, term=self.term, leader=self.leader,
            last_index=len(self.entries)-1, commit_index=self.commit, applied_index=self.applied,
            revision=revision, digest=digest.hexdigest())

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def election(self):
        self.term += 1
        term = self.term
        self.role, self.vote, self.leader = "candidate", self.address, ""
        self.persist()
        self.reset_timer()
        votes = 1
        async def ask(peer):
            nonlocal votes
            try:
                reply = await self.stubs[peer].RequestVote(pb.VoteRequest(term=term,
                    candidate=self.address, last_index=len(self.entries)-1, last_term=self.entries[-1].term),
                    timeout=0.4)
            except grpc.aio.AioRpcError:
                return
            if reply.term > self.term:
                self.step_down(reply.term)
            if self.role == "candidate" and self.term == term and reply.granted:
                votes += 1
        await asyncio.gather(*(ask(p) for p in self.peers))
        if self.role == "candidate" and self.term == term and votes >= (len(self.peers)+1)//2+1:
            self.role, self.leader = "leader", self.address
            self.elected_at = time.monotonic()
            self.contacts = {}
            self.next_index = {p: len(self.entries) for p in self.peers}
            self.match = {p: 0 for p in self.peers}
            self.append_local(pb.Entry(term=term))
            log.info("elected leader %s term %s", self.address, term)
            self.replicate()

    def replicate(self):
        for peer in self.peers:
            if not self.locks[peer].locked():
                self.spawn(self.send(peer))

    async def send(self, peer):
        async with self.locks[peer]:
            term = self.term
            while self.role == "leader" and self.term == term:
                index = self.next_index[peer]
                entries = self.entries[index:index+128]
                request = pb.AppendRequest(term=term, leader=self.address, prev_index=index-1,
                    prev_term=self.entries[index-1].term, entries=entries, commit=self.commit)
                try:
                    reply = await self.stubs[peer].AppendEntries(request, timeout=0.4)
                except grpc.aio.AioRpcError:
                    return
                if reply.term > self.term:
                    self.step_down(reply.term)
                if self.role != "leader" or self.term != term:
                    return
                if not reply.success:
                    self.next_index[peer] = max(1, index-1)
                    continue
                self.contacts[peer] = time.monotonic()
                self.match[peer] = reply.match_index
                self.next_index[peer] = reply.match_index+1
                majority = (len(self.peers)+1)//2+1
                replicated = sorted([len(self.entries)-1, *self.match.values()], reverse=True)[majority-1]
                if replicated > self.commit and self.entries[replicated].term == self.term:
                    self.commit = replicated
                    self.persist()
                    self.apply_committed()
                if self.next_index[peer] >= len(self.entries):
                    return

    async def start(self):
        self.ticker = asyncio.create_task(self.tick())

    async def tick(self):
        while True:
            await asyncio.sleep(0.1)
            if self.role == "leader":
                now = time.monotonic()
                recent = 1 + sum(now - seen < 1.4 for seen in self.contacts.values())
                if now - self.elected_at > 1.4 and recent < (len(self.peers)+1)//2+1:
                    self.step_down(self.term)
                else:
                    self.replicate()
            elif time.monotonic() >= self.deadline:
                await self.election()

    async def command(self, payload=b""):
        if self.role != "leader":
            raise NotLeader(self.leader)
        index = self.append_local(pb.Entry(term=self.term, command=payload))
        future = asyncio.get_running_loop().create_future()
        self.pending[index] = future
        self.replicate()
        try:
            return await asyncio.wait_for(future, 2.5)
        except TimeoutError:
            raise NotLeader(self.leader)
        finally:
            self.pending.pop(index, None)

    async def propose(self, batch):
        request = document_pb2.SubmitOperationsRequest(doc_id=batch.doc_id,
            operations=[operation_to_proto(op) for op in batch.ops])
        return await self.command(request.SerializeToString(deterministic=True))

    async def read_barrier(self):
        await self.command()

    async def close(self):
        self.ticker.cancel()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(self.ticker, *self.tasks, return_exceptions=True)
        for ch in self.channels.values():
            await ch.close()
        self.db.close()
