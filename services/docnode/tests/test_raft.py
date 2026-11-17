import asyncio
import grpc
from collab.v1 import raft_pb2 as pb, raft_pb2_grpc as rpc
from docnode.raft import RaftLog
from docnode.statemachine import StateMachine, Batch, Operation, OpId
from docnode.text import Change


def test_partition_and_conflicting_suffix(tmp_path):
    async def scenario():
        servers = [grpc.aio.server() for _ in range(3)]
        addresses = [f"127.0.0.1:{s.add_insecure_port('127.0.0.1:0')}" for s in servers]
        nodes = [RaftLog(a, [p for p in addresses if p != a], tmp_path / str(i), StateMachine())
                 for i,a in enumerate(addresses)]
        blocked = set()

        class Link:
            def __init__(self, source, target, stub):
                self.source, self.target, self.stub = source, target, stub

            def __getattr__(self, method):
                async def call(*args, **kwargs):
                    if (self.source,self.target) in blocked:
                        # Return a genuine gRPC transport failure through a closed port.
                        async with grpc.aio.insecure_channel("127.0.0.1:1") as channel:
                            return await getattr(rpc.RaftServiceStub(channel), method)(*args, timeout=0.05)
                    return await getattr(self.stub, method)(*args, **kwargs)
                return call

        async def until(predicate):
            for _ in range(100):
                if predicate():
                    return
                await asyncio.sleep(0.05)
            raise AssertionError("cluster failed to stabilize")

        try:
            for i,node in enumerate(nodes):
                for peer, stub in list(node.stubs.items()):
                    node.stubs[peer] = Link(i, addresses.index(peer), stub)
                rpc.add_RaftServiceServicer_to_server(node, servers[i])
                await servers[i].start()
                await node.start()
            await until(lambda: sum(n.role == "leader" for n in nodes) == 1)
            old = next(i for i,n in enumerate(nodes) if n.role == "leader")
            leader = nodes[old]
            await leader.propose(Batch("doc", (Operation(OpId("a",1),"doc",0,(Change(0,0,"base"),)),)))
            for j in range(3):
                if j != old:
                    blocked.update({(old,j),(j,old)})
            # Old leader appends an uncommitted conflicting suffix.
            failed = asyncio.create_task(leader.propose(Batch("doc", (
                Operation(OpId("a",2),"doc",1,(Change(4,4," discarded"),)),))))
            await until(lambda: any(n.role == "leader" for i,n in enumerate(nodes) if i != old))
            replacement = next(n for i,n in enumerate(nodes) if i != old and n.role == "leader")
            await replacement.propose(Batch("doc", (Operation(OpId("b",1),"doc",1,(Change(4,4," committed"),)),)))
            try:
                await failed
                raise AssertionError("isolated leader acknowledged a write")
            except Exception as error:
                from docnode.oplog import NotLeader
                assert isinstance(error, NotLeader)
            try:
                await leader.read_barrier()
                raise AssertionError("isolated leader served authoritative read")
            except Exception as error:
                from docnode.oplog import NotLeader
                assert isinstance(error, NotLeader)
            blocked.clear()
            await until(lambda: all(n.sm.snapshot("doc") == ("base committed",2) for n in nodes))
            assert all(n.commit == n.applied for n in nodes)
        finally:
            for node in nodes:
                await node.close()
            for server in servers:
                await server.stop(0)
    asyncio.run(scenario())


def test_vote_persists_and_log_freshness(tmp_path):
    async def scenario():
        node = RaftLog("a", [], tmp_path, StateMachine())
        vote = pb.VoteRequest(term=3, candidate="b")
        assert (await node.RequestVote(vote,None)).granted
        node.db.close()
        node = RaftLog("a", [], tmp_path, StateMachine())
        assert not (await node.RequestVote(pb.VoteRequest(term=3,candidate="c"),None)).granted
        node.append_local(pb.Entry(term=3))
        assert not (await node.RequestVote(pb.VoteRequest(term=4,candidate="c",last_index=100,last_term=2),None)).granted
        assert (await node.RequestVote(pb.VoteRequest(term=4,candidate="c",last_index=1,last_term=3),None)).granted
        node.db.close()
    asyncio.run(scenario())
