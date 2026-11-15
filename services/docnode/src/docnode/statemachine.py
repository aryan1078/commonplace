"""Every document, and the rules for applying batches of operations to them.

`StateMachine.apply` is deterministic: given the same batches in the same
order, every copy ends with exactly the same text, revisions and
accept/reject decisions. It never reads the clock, generates random numbers or
talks to the network. That is what lets Raft keep several copies in sync by
feeding each one the same log.

Conflicts are resolved by the clients: an operation is accepted only if it was
made against the document's current revision. Anything older is rejected with
StaleError, and the client rebases its edit onto the newer revisions and sends
it again.

The state machine is owned by one asyncio event loop and is not thread-safe;
every call is short and never awaits, so no locking is needed.
"""

from dataclasses import dataclass, field

from . import text
from .subscribe import Subscription


@dataclass(frozen=True)
class OpId:
    """Identifies one operation, so a retried operation is applied only once.

    Each editor session picks a random client_id and numbers its operations
    1, 2, 3, ... in the order it creates them.
    """

    client_id: str
    seq: int


@dataclass(frozen=True)
class Operation:
    op_id: OpId
    doc_id: str
    base_revision: int  # the revision the edit was made against
    changes: tuple[text.Change, ...] = ()
    user_id: str = ""


@dataclass(frozen=True)
class Batch:
    """Operations on one document, applied all-or-nothing: one log entry.

    Operation i must be based on the revision produced by operation i-1, so a
    client can send several pending edits at once.
    """

    doc_id: str
    ops: tuple[Operation, ...]


@dataclass(frozen=True)
class Committed:
    """An accepted operation and the revision it produced."""

    revision: int
    op: Operation


@dataclass(frozen=True)
class Result:
    revision: int  # the document's revision after the batch
    applied: int = 0  # operations applied now
    duplicates: int = 0  # operations skipped because they were applied before


@dataclass(frozen=True)
class DocumentInfo:
    doc_id: str
    revision: int
    length: int  # UTF-16 code units


class ApplyError(Exception):
    """The batch was rejected and nothing changed. Every replica rejects it
    the same way, so this is an outcome, not a failure."""


class StaleError(ApplyError):
    """An operation was made against an older revision. The client should
    catch up to `current`, rebase its edit and send it again."""

    def __init__(self, base_revision: int, current: int):
        super().__init__(
            f"operation is based on revision {base_revision} "
            f"but the document is at revision {current}"
        )
        self.base_revision = base_revision
        self.current = current


class InvalidOperation(ApplyError):
    """The batch is malformed (bad IDs, ranges outside the text, ...)."""


@dataclass
class _Document:
    text: bytes = b""  # UTF-16-LE
    history: list[Operation] = field(default_factory=list)  # history[i] produced revision i+1
    last_seq: dict[str, int] = field(default_factory=dict)  # highest applied seq per client
    subs: set[Subscription[Committed]] = field(default_factory=set)

    @property
    def revision(self) -> int:
        return len(self.history)

    def since(self, from_revision: int, limit: int | None = None) -> list[Committed]:
        if from_revision > self.revision:
            raise InvalidOperation(
                f"revision {from_revision} is in the future (document is at {self.revision})"
            )
        end = self.revision if limit is None else min(self.revision, from_revision + limit)
        return [Committed(i + 1, self.history[i]) for i in range(from_revision, end)]

    def publish(self, c: Committed) -> None:
        for sub in list(self.subs):
            if not sub.deliver(c):
                self.subs.discard(sub)  # too slow: dropped, never waited for


_EMPTY = _Document()


class StateMachine:
    def __init__(self) -> None:
        # Any document ID can be used; one never edited is empty, at revision 0.
        self._docs: dict[str, _Document] = {}

    def _doc(self, doc_id: str) -> _Document:
        d = self._docs.get(doc_id)
        if d is None:
            d = self._docs[doc_id] = _Document()
        return d

    def apply(self, batch: Batch) -> Result:
        """Applies every new operation in the batch, or raises ApplyError
        (StaleError or InvalidOperation) and changes nothing."""
        if not batch.doc_id:
            raise InvalidOperation("doc_id is empty")
        d = self._doc(batch.doc_id)

        # First pass: check everything and build the new text without touching d.
        revision = d.revision
        new_text = d.text
        seen: dict[str, int] = {}  # seq updates made by this batch so far
        accepted: list[Operation] = []
        duplicates = 0

        for i, op in enumerate(batch.ops):
            if op.doc_id != batch.doc_id:
                raise InvalidOperation(
                    f"operation {i} is for document {op.doc_id!r}, not {batch.doc_id!r}"
                )
            if not op.op_id.client_id or op.op_id.seq <= 0:
                raise InvalidOperation(f"operation {i} needs a client_id and a seq above 0")
            last = seen.get(op.op_id.client_id, d.last_seq.get(op.op_id.client_id, 0))
            if op.op_id.seq <= last:
                duplicates += 1  # a retry of something already applied: skip it
                continue
            if op.base_revision != revision:
                raise StaleError(op.base_revision, revision)
            try:
                new_text = text.apply(new_text, op.changes)
            except text.InvalidChange as err:
                raise InvalidOperation(f"operation {i}: {err}") from None
            seen[op.op_id.client_id] = op.op_id.seq
            accepted.append(op)
            revision += 1

        # Second pass: everything checked out, so commit.
        d.text = new_text
        d.last_seq.update(seen)
        for op in accepted:
            d.history.append(op)
            d.publish(Committed(d.revision, op))
        return Result(revision=d.revision, applied=len(accepted), duplicates=duplicates)

    def snapshot(self, doc_id: str) -> tuple[str, int]:
        """The document's current text and revision."""
        d = self._docs.get(doc_id, _EMPTY)
        return text.decode(d.text), d.revision

    def history(self, doc_id: str, from_revision: int, limit: int | None = None) -> list[Committed]:
        """Committed operations after from_revision, at most limit of them."""
        return self._docs.get(doc_id, _EMPTY).since(from_revision, limit)

    def documents(self) -> list[DocumentInfo]:
        """Every document with at least one committed operation, by doc_id."""
        return [
            DocumentInfo(doc_id, d.revision, len(d.text) // 2)
            for doc_id, d in sorted(self._docs.items())
            if d.revision > 0
        ]

    def subscribe(self, doc_id: str, from_revision: int, buffer: int) -> Subscription[Committed]:
        """Starts delivering the document's operations after from_revision.

        The backlog is taken and the subscriber registered in one step, with
        no await in between, so no operation can slip through unseen. Up to
        `buffer` operations may queue before the subscriber is dropped.
        """
        d = self._docs.get(doc_id, _EMPTY)
        backlog = d.since(from_revision)
        d = self._doc(doc_id)
        sub: Subscription[Committed] = Subscription(backlog, buffer, d.subs.discard)
        d.subs.add(sub)
        return sub
