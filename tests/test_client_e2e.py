"""The client library against the whole in-process stack."""

import asyncio

from collab.v1 import gateway_pb2
from collab_client.client import CollabClient
from collab_client.simulate import run_simulation
from collab_client.textops import Change
from stack import running_stack

S = gateway_pb2


def run(test):
    async def main():
        async with running_stack() as stack:
            await test(stack)

    asyncio.run(main())


def test_concurrent_edits_on_the_same_revision_both_land():
    async def test(stack):
        async with CollabClient(stack.gateway) as alice, CollabClient(stack.gateway) as bob:
            await alice.login("alice", "alice123")
            await bob.login("bob", "bob123")
            a = await alice.join("notes")
            b = await bob.join("notes")
            await a.edit(Change(0, 0, "Hello world"))
            await b.wait_for_revision(1)

            # Both edit revision 1 at the same moment.
            ra, rb = await asyncio.gather(
                alice.edit("notes", [Change(5, 5, ",")], 1),
                bob.edit("notes", [Change(11, 11, "!")], 1),
            )
            assert sorted([ra.attempts, rb.attempts]) == [1, 2]  # one was rebased
            await a.wait_for_revision(3)
            await b.wait_for_revision(3)
            assert a.text == b.text == "Hello, world!"
            await a.close()
            await b.close()

    run(test)


def test_logout_closes_the_live_view():
    async def test(stack):
        async with CollabClient(stack.gateway) as bob:
            await bob.login("bob", "bob123")
            view = await bob.join("notes")
            assert await bob.logout() == S.OK
            await view.wait_for(lambda v: v.closed is not None)
            assert view.closed.status == S.UNAUTHENTICATED

    run(test)


def test_get_returns_id_data_pairs():
    async def test(stack):
        async with CollabClient(stack.gateway) as c:
            await c.login("carol", "carol123")
            await c.edit("d1", [Change(0, 0, "abc")], 0)
            status, items = await c.get("documents")
            assert status == S.OK and [(i, d.revision) for i, d in items] == [("d1", 1)]
            assert [op.revision for op in await c.history("d1")] == [1]

    run(test)


def test_simulation_is_consistent():
    async def test(stack):
        report = await run_simulation(stack.gateway, users=5, edits=10, seed=1)
        assert report.consistent, report.lines()
        assert report.attempts > report.expected_revision  # conflicts really happened

    run(test)
