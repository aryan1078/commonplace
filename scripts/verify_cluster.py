"""Reproducible process-level leader-kill and restart acceptance test."""
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import json

ROOT = Path(__file__).resolve().parents[1]
for part in ["gen/python", "clients", "services/gateway/src"]:
    sys.path.insert(0, str(ROOT / part))
import grpc
from collab.v1 import raft_pb2, raft_pb2_grpc
from collab_client.client import CollabClient
from collab_client.textops import Change
from collab_client.simulate import run_simulation


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def run():
    peers = [f"127.0.0.1:{free_port()}" for _ in range(3)]
    assist, gateway = free_port(), free_port()
    processes, outputs = {}, []
    channels = [grpc.aio.insecure_channel(p) for p in peers]
    stubs = [raft_pb2_grpc.RaftServiceStub(c) for c in channels]
    report = {}
    with tempfile.TemporaryDirectory(prefix="collab-raft-") as directory:
        def start(i):
            command = ["docnode", "--port", peers[i].split(":")[1], "--address", peers[i],
                       "--peers", ",".join(peers), "--data-dir", str(Path(directory) / f"node{i}")]
            launch(str(i), command)
        def launch(name, command):
            output = open(Path(directory) / f"{name}.log", "a", encoding="utf8")
            outputs.append(output)
            processes[name] = subprocess.Popen([sys.executable, str(ROOT / "run.py"), *command],
                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                env={**os.environ, "ASSIST_PROVIDER": "fake", "ASSIST_PORT": str(assist)},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        def kill(i):
            processes[str(i)].kill()
            processes[str(i)].wait(timeout=5)
        async def states(doc):
            async def one(stub):
                try:
                    return await stub.Status(raft_pb2.StatusRequest(doc_id=doc), timeout=0.5)
                except grpc.RpcError:
                    return None
            return await asyncio.gather(*(one(s) for s in stubs))
        async def agree(doc, revision):
            for _ in range(150):
                replies = await states(doc)
                if all(s and s.revision == revision for s in replies) and len({s.digest for s in replies}) == 1:
                    return replies
                await asyncio.sleep(0.1)
            raise AssertionError(f"replicas did not converge at revision {revision}")
        client = CollabClient(f"127.0.0.1:{gateway}")
        view = None
        try:
            for i in range(3):
                start(i)
            launch("assist", ["assist"])
            launch("gateway", ["gateway", "--port", str(gateway), "--docnodes", ",".join(peers),
                               "--assist", f"127.0.0.1:{assist}"])
            for _ in range(100):
                try:
                    await client.login("alice", "alice123")
                    view = await client.join("acceptance")
                    break
                except Exception:
                    await asyncio.sleep(0.1)
            assert view is not None, "cluster startup"
            await view.edit(Change(0, 0, "Persistent notes 🎉"))
            await agree("acceptance", 1)
            # Simulate an ambiguous result: retry the same ID through a replacement.
            from collab.v1 import common_pb2, document_pb2
            from gateway.docs import DocsClient
            docs = DocsClient(",".join(peers))
            operation = common_pb2.Operation(doc_id="retry", op_id=common_pb2.OpId(client_id="retry-client",seq=1),
                changes=[common_pb2.TextChange(range=common_pb2.TextRange(),insert="once")])
            request = document_pb2.SubmitOperationsRequest(doc_id="retry", operations=[operation])
            await docs.submit(request)
            work = asyncio.create_task(run_simulation(f"127.0.0.1:{gateway}", 8, 25, seed=42))
            await asyncio.sleep(0.8)
            replies = await states("acceptance")
            leader = next(i for i,s in enumerate(replies) if s and s.role == "leader")
            old_term = replies[leader].term
            began = time.monotonic()
            kill(leader)
            await view.edit(Change(0, 0, "Recovered: "))
            report["recovery_seconds"] = round(time.monotonic()-began, 3)
            retry = await docs.submit(request)
            assert retry.duplicates == 1 and retry.applied == 0
            simulation = await work
            assert simulation.consistent
            report["simulation"] = simulation.lines()
            assert not view.closed
            start(leader)
            final = await agree("acceptance", 2)
            assert max(s.term for s in final) > old_term
            await agree(simulation.doc_id, 200)
            await agree("retry", 1)
            for i in range(3):
                kill(i)
            for i in range(3):
                start(i)
            await agree("acceptance", 2)
            await agree(simulation.doc_id, 200)
            await agree("retry", 1)
            assert (await docs.submit(request)).duplicates == 1
            # A follower can also fail while the leader and other voter continue.
            replies = await states("acceptance")
            follower = next(i for i, state in enumerate(replies) if state.role == "follower")
            kill(follower)
            await view.edit(Change(0, 0, "Follower recovered: "))
            start(follower)
            await agree("acceptance", 3)
            await agree(simulation.doc_id, 200)
            # Keep one voter alive and verify quorum-backed reads/writes time out.
            replies = await states("acceptance")
            survivor = next(i for i,s in enumerate(replies) if s.role == "leader")
            for i in range(3):
                if i != survivor:
                    kill(i)
            from collab.v1 import document_pb2_grpc
            stub = document_pb2_grpc.DocumentServiceStub(channels[survivor])
            for method, payload in [
                (stub.GetSnapshot, document_pb2.GetSnapshotRequest(doc_id="acceptance")),
                (stub.SubmitOperations, request),
            ]:
                try:
                    await method(payload, timeout=4)
                    raise AssertionError("operation succeeded without majority")
                except grpc.aio.AioRpcError as error:
                    assert error.code() in (grpc.StatusCode.FAILED_PRECONDITION,grpc.StatusCode.DEADLINE_EXCEEDED)
            report["checks"] = ["leader killed during 200-edit workload", "live view survived",
                "duplicate retry after failover", "all three replicas matched",
                "full cluster disk restart", "deduplication after disk restart",
                "follower crash accepts a new edit and catches up on its original disk",
                "majority loss rejects reads and writes"]
            print(json.dumps(report, indent=2))
            await docs.close()
        finally:
            if view:
                await view.close()
            await client.close()
            for channel in channels:
                await channel.close()
            for process in processes.values():
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            for output in outputs:
                output.close()
            for name in processes:
                log = Path(directory) / f"{name}.log"
                if log.exists() and "Traceback" in log.read_text(encoding="utf8"):
                    print(log.read_text(encoding="utf8")[-3000:], file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(run())
