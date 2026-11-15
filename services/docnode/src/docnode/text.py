"""Applies edits to document text.

Documents are stored as UTF-16-LE bytes, because every position in the API is
a UTF-16 code unit (see common.proto). Unit i lives at bytes [2i, 2i+2), so a
position sent by a client indexes the text directly, with no conversion.
"""

from collections.abc import Sequence
from dataclasses import dataclass

ENCODING = "utf-16-le"


@dataclass(frozen=True)
class Change:
    """Replace the text in [start, end) with insert.

    start and end are UTF-16 offsets into the document the change was made
    against.
    """

    start: int
    end: int
    insert: str


class InvalidChange(ValueError):
    """A change does not fit the document. Nothing was applied."""


def encode(s: str) -> bytes:
    return s.encode(ENCODING)


def decode(units: bytes) -> str:
    return units.decode(ENCODING)


def length(s: str) -> int:
    """Length of s in UTF-16 code units."""
    return len(encode(s)) // 2


def _unit(doc: bytes, i: int) -> int:
    return doc[2 * i] | (doc[2 * i + 1] << 8)


def _splits_pair(doc: bytes, p: int) -> bool:
    """True if p falls between the two halves of a surrogate pair.

    Characters outside the Basic Multilingual Plane (most emoji) take two
    UTF-16 units; cutting between them would corrupt the text.
    """
    if p <= 0 or p >= len(doc) // 2:
        return False
    return 0xD800 <= _unit(doc, p - 1) <= 0xDBFF and 0xDC00 <= _unit(doc, p) <= 0xDFFF


def apply(doc: bytes, changes: Sequence[Change]) -> bytes:
    """Returns doc with all changes applied (doc is immutable bytes).

    All changes refer to positions in doc, not to the result of earlier
    changes in the list. They must be sorted by start and must not overlap.
    Raises InvalidChange, and applies nothing, if any change is invalid.
    """
    size = len(doc) // 2
    prev_end = 0
    for i, c in enumerate(changes):
        if c.start < 0 or c.end < c.start or c.end > size:
            raise InvalidChange(
                f"change {i}: range [{c.start}, {c.end}) is outside the document (length {size})"
            )
        if c.start < prev_end:
            raise InvalidChange(f"change {i}: ranges must be sorted and must not overlap")
        if _splits_pair(doc, c.start) or _splits_pair(doc, c.end):
            raise InvalidChange(f"change {i}: range [{c.start}, {c.end}) splits a character in half")
        prev_end = c.end

    parts: list[bytes] = []
    pos = 0
    for c in changes:
        parts.append(doc[2 * pos : 2 * c.start])
        parts.append(encode(c.insert))
        pos = c.end
    parts.append(doc[2 * pos :])
    return b"".join(parts)
