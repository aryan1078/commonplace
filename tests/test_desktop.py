import asyncio
import pytest
from collab_client.desktop import DesktopSession, differences, merge_draft
from collab_client.textops import apply_changes
from stack import running_stack


def test_draft_merging_keeps_local_and_remote_insertions():
    result = merge_draft("hello", "hello local", "remote hello", 11)
    assert result["text"] == "remote hello local"
    assert apply_changes("a🎉b".encode("utf-16-le"), differences("a🎉b", "a🎉new b")).decode("utf-16-le") == "a🎉new b"


def test_desktop_login_edit_presence_history_and_logout():
    async def scenario():
        async with running_stack() as stack:
            alice, bob = DesktopSession(stack.gateway), DesktopSession(stack.gateway)
            with pytest.raises(ValueError, match="incorrect"):
                await alice.login("alice", "wrong")
            await alice.login("alice", "alice123")
            await bob.login("bob", "bob123")
            await alice.create("Project Notes")
            await bob.open("project-notes")
            a = alice.state()["document"]
            b = bob.state()["document"]
            await asyncio.gather(alice.save(a["id"], a["text"], "Alice 🎉\n", a["revision"]),
                                 bob.save(b["id"], b["text"], "Bob\n", b["revision"]))
            await alice.view.wait_for_revision(3)
            await bob.view.wait_for_revision(3)
            assert alice.view.text == bob.view.text
            assert "Alice 🎉" in bob.view.text and "Bob" in bob.view.text
            assert len(await alice.history()) == 3
            with pytest.raises(ValueError, match="already exists"):
                await alice.create("Project Notes")
            await alice.logout()
            with pytest.raises(Exception, match="UNAUTHENTICATED"):
                await alice.poll()
            await bob.logout()
    asyncio.run(scenario())


def test_suggestion_rejects_changed_passage():
    async def scenario():
        from collab.v1 import assist_pb2, common_pb2
        async with running_stack() as stack:
            session = DesktopSession(stack.gateway)
            await session.login("alice", "alice123")
            await session.create("Suggestions")
            await session.save("suggestions", "", "a typo", 1)
            session.suggestions = [assist_pb2.Suggestion(original="typo", replacement="word",
                anchor=common_pb2.TextAnchor(doc_id="suggestions", revision=2,
                    range=common_pb2.TextRange(start=2,end=6)))]
            await session.save("suggestions", "a typo", "a change", 2)
            with pytest.raises(ValueError, match="Someone edited"):
                await session.accept(0)
            assert session.view.text == "a change"
            await session.logout()
    asyncio.run(scenario())


def test_cluster_status_requires_login():
    async def scenario():
        from collab.v1 import gateway_pb2
        async with running_stack() as stack:
            reply = await stack.stub.ClusterStatus(gateway_pb2.ClusterStatusRequest())
            assert reply.status == gateway_pb2.UNAUTHENTICATED
    asyncio.run(scenario())


def test_retry_after_lost_save_reply_preserves_new_keystrokes():
    async def scenario():
        from collab_client.client import CollabError
        from collab.v1 import gateway_pb2
        async with running_stack() as stack:
            session = DesktopSession(stack.gateway)
            await session.login("alice", "alice123")
            await session.create("Lost reply")
            original = session.client.edit
            async def lost_reply(*args, **kwargs):
                await original(*args, **kwargs)
                raise CollabError(gateway_pb2.UNAVAILABLE, "reply lost after commitment")
            session.client.edit = lost_reply
            with pytest.raises(CollabError):
                await session.save("lost-reply", "", "hello", 1)
            session.client.edit = original
            result = await session.save("lost-reply", "", "hello again", 1)
            assert result["document"]["text"] == "hello again"
            assert len(await session.history()) == 3
            await session.logout()
    asyncio.run(scenario())
