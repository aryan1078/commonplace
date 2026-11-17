"""CollabService over real gRPC, with a real docnode and the fake LLM."""

import asyncio

import grpc

from collab.v1 import assist_pb2, common_pb2, document_pb2, gateway_pb2, presence_pb2
from gateway.docs import DocsClient
from stack import running_stack

S = gateway_pb2


def run(test, **kwargs):
    async def main():
        async with running_stack(**kwargs) as stack:
            await test(stack)

    asyncio.run(main())


async def login(stub, name):
    reply = await stub.Login(gateway_pb2.LoginRequest(username=name, password=f"{name}123"))
    assert reply.status == S.OK
    return reply.token


def edit(token, doc, client, seq, base, pos, text, session_id="", user_id=""):
    op = common_pb2.Operation(
        op_id=common_pb2.OpId(client_id=client, seq=seq), base_revision=base, doc_id="other", user_id=user_id,
        changes=[common_pb2.TextChange(range=common_pb2.TextRange(start=pos, end=pos), insert=text)],
    )
    return gateway_pb2.PostRequest(
        token=token, session_id=session_id, edit=document_pb2.SubmitOperationsRequest(doc_id=doc, operations=[op])
    )


async def next_event(stream, kind):
    """The next Join event of this kind, skipping others."""
    while True:
        event = await asyncio.wait_for(stream.read(), 5)
        if event.WhichOneof("event") == kind:
            return event


def test_login_rejects_bad_credentials_without_saying_which():
    async def test(stack):
        wrong = await stack.stub.Login(gateway_pb2.LoginRequest(username="alice", password="nope"))
        unknown = await stack.stub.Login(gateway_pb2.LoginRequest(username="mallory", password="x"))
        assert wrong.status == unknown.status == S.INVALID_CREDENTIALS
        assert wrong.message == unknown.message and not wrong.token

    run(test)


def test_every_call_needs_a_valid_token():
    async def test(stack):
        stub = stack.stub
        assert (await stub.Post(edit("bad", "d", "c", 1, 0, 0, "x"))).status == S.UNAUTHENTICATED
        get = gateway_pb2.GetRequest(token="bad", documents=gateway_pb2.DocumentsParams())
        assert (await stub.Get(get)).status == S.UNAUTHENTICATED
        assert (await stub.Logout(gateway_pb2.LogoutRequest(token="bad"))).status == S.UNAUTHENTICATED
        [event] = [e async for e in stub.Join(gateway_pb2.JoinRequest(token="bad", doc_id="d"))]
        assert event.closed.status == S.UNAUTHENTICATED
        [event] = [e async for e in stub.Assist(gateway_pb2.AssistRequest(token="bad", ask=gateway_pb2.AskRequest()))]
        assert event.status == S.UNAUTHENTICATED

    run(test)


def test_edit_identity_and_stale_revision():
    async def test(stack):
        alice = await login(stack.stub, "alice")
        reply = await stack.stub.Post(edit(alice, "notes", "c-a", 1, 0, 0, "hello", user_id="mallory"))
        assert reply.status == S.OK and reply.edit.revision == 1
        [committed] = stack.sm.history("notes", 0)
        assert (committed.op.user_id, committed.op.doc_id) == ("alice", "notes")  # set by the gateway

        bob = await login(stack.stub, "bob")
        stale = await stack.stub.Post(edit(bob, "notes", "c-b", 1, 0, 0, "X"))
        assert stale.status == S.STALE_REVISION and stale.current_revision == 1

        bad = await stack.stub.Post(edit(bob, "notes", "c-b", 1, 1, 99, "X"))
        assert bad.status == S.INVALID_ARGUMENT
        assert (await stack.stub.Post(edit(bob, "bad id!", "c-b", 1, 0, 0, "X"))).status == S.INVALID_ARGUMENT

    run(test)


def test_join_streams_snapshot_operations_and_presence(monkeypatch):
    async def test(stack):
        # The Join snapshot succeeds, then discovery for the subscription
        # crosses an election. The existing Join must survive both failures.
        original_snapshot = DocsClient.snapshot
        calls = 0
        recovered = asyncio.Event()

        async def interrupted_discovery(self, doc_id):
            nonlocal calls
            calls += 1
            if calls in (2, 3):
                code = grpc.StatusCode.UNAVAILABLE if calls == 2 else grpc.StatusCode.DEADLINE_EXCEEDED
                raise grpc.aio.AioRpcError(code, (), (), "leader election")
            snapshot = await original_snapshot(self, doc_id)
            if calls >= 4:
                recovered.set()
            return snapshot

        monkeypatch.setattr(DocsClient, "snapshot", interrupted_discovery)
        stub = stack.stub
        alice, bob = await login(stub, "alice"), await login(stub, "bob")
        await stub.Post(edit(alice, "doc", "c-a", 1, 0, 0, "hi"))

        a_stream = stub.Join(gateway_pb2.JoinRequest(token=alice, doc_id="doc"))
        joined = (await next_event(a_stream, "joined")).joined
        assert (joined.name, joined.snapshot.text, joined.snapshot.revision) == ("alice", "hi", 1)
        await asyncio.wait_for(recovered.wait(), 3)

        b_stream = stub.Join(gateway_pb2.JoinRequest(token=bob, doc_id="doc"))
        b_session = (await next_event(b_stream, "joined")).joined.session_id
        while len((await next_event(a_stream, "presence")).presence.participants) != 2:
            pass  # alice sees bob arrive

        reply = await stub.Post(edit(bob, "doc", "c-b", 1, 1, 2, "!", session_id=b_session))
        assert reply.status == S.OK
        op = (await next_event(a_stream, "operation")).operation
        assert (op.revision, op.operation.user_id, op.operation.changes[0].insert) == (2, "bob", "!")

        cursor = presence_pb2.CursorUpdate(revision=2, anchor=1, head=3)
        assert (await stub.Post(gateway_pb2.PostRequest(token=bob, session_id=b_session, cursor=cursor))).status == S.OK
        while True:
            ps = (await next_event(a_stream, "presence")).presence.participants
            bob_p = next(p for p in ps if p.name == "bob")
            if bob_p.cursor.head == 3:
                break
        assert bob_p.editing and bob_p.last_edit_unix_ms > 0

        # Someone else cannot move bob's cursor.
        stolen = gateway_pb2.PostRequest(token=alice, session_id=b_session, cursor=cursor)
        assert (await stub.Post(stolen)).status == S.NOT_FOUND

        presence = await stub.Get(gateway_pb2.GetRequest(token=alice, presence=gateway_pb2.PresenceParams(doc_id="doc")))
        assert sorted(i.participant.name for i in presence.items) == ["alice", "bob"]

        b_stream.cancel()
        while len((await next_event(a_stream, "presence")).presence.participants) != 1:
            pass  # bob left
        a_stream.cancel()

    run(test)


def test_logout_closes_join_streams():
    async def test(stack):
        bob = await login(stack.stub, "bob")
        stream = stack.stub.Join(gateway_pb2.JoinRequest(token=bob, doc_id="doc"))
        await next_event(stream, "joined")
        assert (await stack.stub.Logout(gateway_pb2.LogoutRequest(token=bob))).status == S.OK
        closed = (await next_event(stream, "closed")).closed
        assert closed.status == S.UNAUTHENTICATED and "logged out" in closed.reason
        assert (await stack.stub.Post(edit(bob, "doc", "c", 1, 0, 0, "x"))).status == S.UNAUTHENTICATED

    run(test)


def test_expired_token_closes_join_stream():
    async def test(stack):
        token = await login(stack.stub, "carol")
        stream = stack.stub.Join(gateway_pb2.JoinRequest(token=token, doc_id="doc"))
        await next_event(stream, "joined")
        closed = (await next_event(stream, "closed")).closed
        assert closed.status == S.UNAUTHENTICATED and "expired" in closed.reason

    run(test, token_ttl_s=0.5)


def test_get_snapshot_history_and_documents():
    async def test(stack):
        alice = await login(stack.stub, "alice")
        await stack.stub.Post(edit(alice, "a", "c", 1, 0, 0, "one"))
        await stack.stub.Post(edit(alice, "a", "c", 2, 1, 3, " two"))
        await stack.stub.Post(edit(alice, "b", "c2", 1, 0, 0, "x"))

        def get(**params):
            return stack.stub.Get(gateway_pb2.GetRequest(token=alice, **params))

        snap = await get(snapshot=gateway_pb2.SnapshotParams(doc_id="a"))
        assert [(i.id, i.snapshot.text) for i in snap.items] == [("a", "one two")]
        history = await get(history=gateway_pb2.HistoryParams(doc_id="a", from_revision=1))
        assert [(i.id, i.operation.operation.changes[0].insert) for i in history.items] == [("2", " two")]
        docs = await get(documents=gateway_pb2.DocumentsParams())
        assert [(i.id, i.document.revision) for i in docs.items] == [("a", 2), ("b", 1)]
        future = await get(history=gateway_pb2.HistoryParams(doc_id="a", from_revision=9))
        assert future.status == S.INVALID_ARGUMENT

    run(test)


def test_assist_tasks():
    async def test(stack):
        alice = await login(stack.stub, "alice")
        text = "We meet on Friday. so i will bring the slides."
        await stack.stub.Post(edit(alice, "notes", "c", 1, 0, 0, text))

        async def assist(**task):
            request = gateway_pb2.AssistRequest(token=alice, request_id="r1", doc_id="notes", **task)
            return [e async for e in stack.stub.Assist(request)]

        [answer] = await assist(ask=gateway_pb2.AskRequest(question="When do we meet?"))
        assert answer.status == S.OK and answer.answer.answer == "We meet on Friday."
        assert answer.answer.revision == 1 and answer.request_id == "r1"

        summary = await assist(summarize=assist_pb2.SummarizeRequest())
        assert "".join(e.summary.delta for e in summary) == "Summary: We meet on Friday."

        context = assist_pb2.TextContext(
            request_id="r1", text=text,
            anchor=common_pb2.TextAnchor(doc_id="notes", revision=1, range=common_pb2.TextRange(start=0, end=len(text))),
        )
        [grammar] = await assist(check_grammar=assist_pb2.CheckGrammarRequest(context=context))
        assert [(s.original, s.replacement) for s in grammar.grammar.suggestions] == [("i", "I")]

        pieces = await assist(autocomplete=assist_pb2.AutocompleteRequest(
            context=assist_pb2.TextContext(request_id="r1", before=text)))
        assert "".join(e.autocomplete.delta for e in pieces).strip()

        [bad] = await assist(enhance=assist_pb2.EnhanceRequest(context=context))  # no mode
        assert bad.status == S.INVALID_ARGUMENT

    run(test)
