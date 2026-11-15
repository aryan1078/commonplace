import asyncio

import pytest

from docnode.statemachine import Batch, InvalidOperation, OpId, Operation, StaleError, StateMachine
from docnode.subscribe import SubscriberTooSlow
from docnode.text import Change


def op(client: str, seq: int, base: int, pos: int, s: str) -> Operation:
    return Operation(OpId(client, seq), "doc", base, (Change(pos, pos, s),))


def apply(sm: StateMachine, *ops: Operation) -> None:
    sm.apply(Batch("doc", ops))


def test_subscription_gets_backlog_then_live_operations():
    sm = StateMachine()
    apply(sm, op("a", 1, 0, 0, "a"), op("a", 2, 1, 1, "b"))

    sub = sm.subscribe("doc", 1, 10)
    assert [c.revision for c in sub.backlog] == [2]

    apply(sm, op("b", 1, 2, 2, "c"))
    got = asyncio.run(sub.next())
    assert (got.revision, got.op.op_id.client_id) == (3, "b")
    sub.close()


def test_rejected_batches_are_not_published():
    sm = StateMachine()
    sub = sm.subscribe("doc", 0, 10)
    with pytest.raises(StaleError):
        apply(sm, op("a", 1, 7, 0, "x"))
    assert sub.get_nowait() is None
    sub.close()


def test_slow_subscriber_is_dropped():
    sm = StateMachine()
    sub = sm.subscribe("doc", 0, 1)  # room for one queued operation
    apply(sm, op("a", 1, 0, 0, "1"))
    apply(sm, op("a", 2, 1, 0, "2"))  # queue full: dropped

    assert asyncio.run(sub.next()).revision == 1  # the one that fit
    assert asyncio.run(sub.next()) is None  # then the end
    assert isinstance(sub.error, SubscriberTooSlow)
    # Writers were never blocked.
    assert sm.snapshot("doc") == ("21", 2)


def test_close_ends_subscription():
    sm = StateMachine()
    sub = sm.subscribe("doc", 0, 1)
    sub.close()
    sub.close()  # safe twice
    assert asyncio.run(sub.next()) is None and sub.error is None
    apply(sm, op("a", 1, 0, 0, "x"))  # no error after close


def test_waiting_reader_is_woken_by_a_commit():
    sm = StateMachine()
    sub = sm.subscribe("doc", 0, 10)

    async def main():
        reader = asyncio.create_task(sub.next())
        await asyncio.sleep(0.01)
        apply(sm, op("a", 1, 0, 0, "x"))
        return await asyncio.wait_for(reader, 1)

    assert asyncio.run(main()).revision == 1


def test_subscribe_from_future_revision_fails():
    with pytest.raises(InvalidOperation):
        StateMachine().subscribe("doc", 3, 1)
