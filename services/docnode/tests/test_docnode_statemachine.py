import asyncio
import random

import pytest

from docnode import text
from docnode.statemachine import (
    ApplyError,
    Batch,
    InvalidOperation,
    OpId,
    Operation,
    Result,
    StaleError,
    StateMachine,
)
from docnode.text import Change


def op(client: str, seq: int, base: int, *changes: Change, doc: str = "doc") -> Operation:
    return Operation(op_id=OpId(client, seq), doc_id=doc, base_revision=base, changes=changes)


def ins(pos: int, s: str) -> Change:
    return Change(pos, pos, s)


def apply(sm: StateMachine, *ops: Operation) -> Result:
    return sm.apply(Batch("doc", ops))


def assert_text(sm: StateMachine, want: str, want_rev: int) -> None:
    assert sm.snapshot("doc") == (want, want_rev)


def test_new_document_is_empty():
    assert_text(StateMachine(), "", 0)


def test_accepts_edit_at_current_revision():
    sm = StateMachine()
    assert apply(sm, op("a", 1, 0, ins(0, "hello"))) == Result(revision=1, applied=1)
    apply(sm, op("b", 1, 1, ins(5, " world")))
    assert_text(sm, "hello world", 2)


def test_rejects_stale_edit_and_changes_nothing():
    sm = StateMachine()
    apply(sm, op("a", 1, 0, ins(0, "hello")))

    # Client b made its edit against revision 0, before a's edit arrived.
    with pytest.raises(StaleError) as info:
        apply(sm, op("b", 1, 0, ins(0, "X")))
    assert info.value.current == 1
    assert_text(sm, "hello", 1)

    # b rebases onto revision 1 and resends with the same seq: accepted.
    apply(sm, op("b", 1, 1, ins(0, "X")))
    assert_text(sm, "Xhello", 2)


def test_batch_of_consecutive_edits():
    sm = StateMachine()
    res = apply(
        sm,
        op("a", 1, 0, ins(0, "abc")),
        op("a", 2, 1, ins(3, "def")),
        op("a", 3, 2, Change(0, 1, "A")),
    )
    assert (res.revision, res.applied) == (3, 3)
    assert_text(sm, "Abcdef", 3)


def test_batch_is_all_or_nothing():
    sm = StateMachine()
    with pytest.raises(InvalidOperation):
        apply(sm, op("a", 1, 0, ins(0, "fine")), op("a", 2, 1, Change(0, 99, "")))
    assert_text(sm, "", 0)
    # The first op was not applied, so its seq was not used up either.
    apply(sm, op("a", 1, 0, ins(0, "fine")))
    assert_text(sm, "fine", 1)


def test_retried_batch_is_not_applied_twice():
    sm = StateMachine()
    batch = [op("a", 1, 0, ins(0, "x")), op("a", 2, 1, ins(1, "y"))]
    apply(sm, *batch)

    # The client timed out and sends the same batch again.
    assert apply(sm, *batch) == Result(revision=2, applied=0, duplicates=2)
    assert_text(sm, "xy", 2)

    # A retry that also carries a new edit: old ones skipped, the new one applied.
    assert apply(sm, *batch, op("a", 3, 2, ins(2, "z"))) == Result(revision=3, applied=1, duplicates=2)
    assert_text(sm, "xyz", 3)


@pytest.mark.parametrize(
    "batch",
    [
        Batch("", (op("a", 1, 0),)),
        Batch("doc", (op("a", 1, 0, doc="other"),)),
        Batch("doc", (op("", 1, 0),)),
        Batch("doc", (op("a", 0, 0),)),
        Batch("doc", (op("a", 1, 0, Change(1, 2, "")),)),
    ],
    ids=["no-doc-id", "wrong-doc", "no-client-id", "seq-zero", "range-past-end"],
)
def test_invalid_operations(batch):
    with pytest.raises(InvalidOperation):
        StateMachine().apply(batch)


def test_history():
    sm = StateMachine()
    apply(sm, op("a", 1, 0, ins(0, "a")), op("a", 2, 1, ins(1, "b")))
    [c] = sm.history("doc", 1)
    assert (c.revision, c.op.op_id.seq) == (2, 2)
    assert [c.revision for c in sm.history("doc", 0, limit=1)] == [1]
    with pytest.raises(InvalidOperation):
        sm.history("doc", 5)


def test_documents_lists_only_edited_documents():
    sm = StateMachine()
    apply(sm, op("a", 1, 0, ins(0, "🎉!")))
    sm.snapshot("never-edited")
    [d] = sm.documents()
    assert (d.doc_id, d.revision, d.length) == ("doc", 1, 3)


def random_edit(r: random.Random, doc: bytes) -> Change:
    """A valid edit against doc (UTF-16-LE bytes), never cutting a surrogate pair."""
    size = len(doc) // 2

    def unit(i: int) -> int:
        return doc[2 * i] | (doc[2 * i + 1] << 8)

    start = r.randint(0, size)
    end = start
    if r.randrange(3) == 0 and start < size:
        end = start + r.randint(0, min(3, size - start))
    while 0 < start < size and 0xDC00 <= unit(start) <= 0xDFFF:
        start -= 1  # never start inside an emoji
    while 0 < end < size and 0xDC00 <= unit(end) <= 0xDFFF:
        end += 1
    end = max(end, start)
    return Change(start, end, r.choice(["a", "bc", "🎉", "é", "नम", " ", "xyz"]))


def outcome(sm: StateMachine, batch: Batch) -> tuple[Result | None, str]:
    try:
        return sm.apply(batch), ""
    except ApplyError as err:
        return None, f"{type(err).__name__}: {err}"


@pytest.mark.parametrize("seed", range(1, 21))
def test_replicas_agree(seed):
    """The property Raft depends on: two state machines fed the same 300
    batches in the same order end identical and make the same decisions,
    including for stale, duplicate and invalid batches."""
    r = random.Random(seed)
    leader, follower = StateMachine(), StateMachine()
    seqs: dict[str, int] = {}
    views: dict[str, tuple[bytes, int]] = {}  # each client's possibly outdated copy
    outcomes = {"applied": 0, "stale": 0, "duplicate": 0, "invalid": 0}

    for step in range(300):
        client = f"c{r.randrange(4)}"
        doc, rev = views.get(client, (b"", 0))
        if r.randrange(3) == 0:  # sometimes catch up to the latest revision
            s, rev = leader.snapshot("doc")
            doc = text.encode(s)
        seqs[client] = seqs.get(client, 0) + 1
        seq = 1 if r.randrange(10) == 0 else seqs[client]  # sometimes an old retry
        change = random_edit(r, doc)
        if r.randrange(25) == 0:
            change = Change(0, len(doc) // 2 + 5, "")  # sometimes plain invalid
        batch = Batch("doc", (op(client, seq, rev, change),))

        res1, err1 = outcome(leader, batch)
        res2, err2 = outcome(follower, batch)
        assert (res1, err1) == (res2, err2), f"step {step}: replicas disagree"

        if err1.startswith("StaleError"):
            outcomes["stale"] += 1
        elif err1:
            outcomes["invalid"] += 1
            seqs[client] -= 1  # not applied: the seq can be reused
        elif res1.duplicates:
            outcomes["duplicate"] += 1
        else:
            outcomes["applied"] += 1
        if res1 is not None and res1.applied == 1:
            s, rev = leader.snapshot("doc")
            doc = text.encode(s)
        views[client] = (doc, rev)

    assert leader.snapshot("doc") == follower.snapshot("doc")
    assert all(outcomes[k] > 0 for k in ("applied", "stale", "duplicate")), outcomes

    # Replaying the committed history from scratch also gives the same text.
    doc = b""
    for c in leader.history("doc", 0):
        doc = text.apply(doc, c.op.changes)
    assert text.decode(doc) == leader.snapshot("doc")[0]


def test_concurrent_writers():
    """Many writers interleaving between reading a snapshot and submitting."""
    sm = StateMachine()
    accepted = 0

    async def writer(w: int) -> None:
        nonlocal accepted
        r = random.Random(w)
        seq = 0
        for _ in range(200):
            s, rev = sm.snapshot("doc")
            await asyncio.sleep(0)  # let other writers commit in between
            seq += 1
            try:
                sm.apply(Batch("doc", (op(f"w{w}", seq, rev, random_edit(r, text.encode(s))),)))
                accepted += 1
            except StaleError:
                seq -= 1  # not applied: the seq can be reused

    async def main() -> None:
        await asyncio.gather(*(writer(w) for w in range(8)))

    asyncio.run(main())
    assert sm.snapshot("doc")[1] == accepted > 0
