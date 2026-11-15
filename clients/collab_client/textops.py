"""Client-side text operations: applying committed edits and rebasing our own.

Positions are UTF-16 code units, like everywhere in the API. The client keeps
its copy of a document as UTF-16-LE bytes so positions index it directly.

Rebasing: when an edit is rejected as stale, the edits it missed are known
(from the history), so each position in our edit is moved past them. The rule
for a tie is fixed: our insertion at the same point as an earlier insertion
goes after it, and our deletion never swallows text inserted at its edges.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

ENCODING = "utf-16-le"


@dataclass(frozen=True)
class Change:
    """Replace [start, end) with insert. Positions in UTF-16 code units."""

    start: int
    end: int
    insert: str


def utf16_len(s: str) -> int:
    return len(s.encode(ENCODING)) // 2


def utf16_offset(s: str, char_index: int) -> int:
    """The UTF-16 position of the Python character index char_index in s."""
    return utf16_len(s[:char_index])


def apply_changes(doc: bytes, changes: Iterable[Change]) -> bytes:
    """Applies changes (sorted, relative to doc) to UTF-16-LE bytes."""
    out, pos = [], 0
    for c in changes:
        if not (pos <= c.start <= c.end <= len(doc) // 2):
            raise ValueError(f"change [{c.start}, {c.end}) does not fit the document")
        out += [doc[2 * pos : 2 * c.start], c.insert.encode(ENCODING)]
        pos = c.end
    out.append(doc[2 * pos :])
    return b"".join(out)


def map_position(pos: int, changes: Sequence[Change], after_inserts: bool) -> int:
    """Where pos ends up once `changes` (made against the same text) apply.

    after_inserts decides ties: True moves pos past text inserted exactly at
    pos (and to the end of a replacement that covers it), False keeps it before.
    """
    delta = 0
    for c in changes:
        added = utf16_len(c.insert)
        if c.end < pos or (c.end == pos and c.start < c.end):
            delta += added - (c.end - c.start)  # entirely before pos
            continue
        if c.start > pos:
            break  # entirely after pos
        if c.start == c.end:  # an insertion exactly at pos
            if after_inserts:
                delta += added
                continue
            break
        if c.start == pos:  # a replacement starting at pos: stay at its start
            break
        # pos is inside replaced text: snap to one end of the replacement.
        return c.start + delta + (added if after_inserts else 0)
    return pos + delta


def rebase(ours: Sequence[Change], theirs: Sequence[Change]) -> list[Change]:
    """Moves our changes (against text T) onto T with `theirs` applied."""
    out = []
    for c in ours:
        start = map_position(c.start, theirs, after_inserts=True)
        end = start if c.end == c.start else max(start, map_position(c.end, theirs, after_inserts=False))
        out.append(Change(start, end, c.insert))
    return out
