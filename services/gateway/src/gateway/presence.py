"""Tracks who is connected to each document and where their cursors are.

Presence lives only in the gateway's memory. It is not replicated or stored:
if the gateway restarts, clients join again and announce themselves. It is
allowed to be lossy: every update carries the full participant list, so a
missed update is corrected by the next one.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

# Colours given to participants, in order.
PALETTE = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9", "#f08c00", "#0c8599", "#e03131", "#5f3dc4"]

# A participant who edited within this window is shown as "editing".
EDITING_WINDOW_MS = 5000


@dataclass(frozen=True)
class Cursor:
    revision: int
    anchor: int
    head: int


@dataclass(frozen=True)
class Participant:
    session_id: str
    name: str
    color: str = ""
    cursor: Cursor | None = None  # None until the first cursor update
    last_edit_unix_ms: int = 0  # 0 if the participant has not edited yet
    editing: bool = False  # computed when the list is handed out


# Receives the full, current participant list. Called synchronously, so it
# must not block (queue the update and return).
Notify = Callable[[list[Participant]], None]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class _Member:
    participant: Participant
    notify: Notify


class Hub:
    """Rooms of participants, one per document. Used from one event loop."""

    def __init__(self, now_ms: Callable[[], int] = _now_ms):
        self._now_ms = now_ms
        self._rooms: dict[str, dict[str, _Member]] = {}  # doc_id -> session_id -> member

    def join(self, doc_id: str, participant: Participant, notify: Notify) -> Callable[[], None]:
        """Adds a participant (the hub picks its colour) and tells everyone,
        including the newcomer. Returns `leave`, which is safe to call twice."""
        room = self._rooms.setdefault(doc_id, {})
        participant = replace(participant, color=_free_color(room))
        room[participant.session_id] = _Member(participant, notify)
        self._broadcast(room)

        left = False

        def leave() -> None:
            nonlocal left
            if not left:
                left = True
                self._leave(doc_id, participant.session_id)

        return leave

    def update_cursor(self, doc_id: str, session_id: str, cursor: Cursor) -> bool:
        """Records where a participant's cursor is. False if not in the room."""
        return self._update(doc_id, session_id, lambda p: replace(p, cursor=cursor))

    def mark_edited(self, doc_id: str, session_id: str) -> bool:
        """Records that a participant just made an edit."""
        now = self._now_ms()
        return self._update(doc_id, session_id, lambda p: replace(p, last_edit_unix_ms=now))

    def participants(self, doc_id: str) -> list[Participant]:
        """The document's participants, sorted by name."""
        return self._list(self._rooms.get(doc_id, {}))

    def _leave(self, doc_id: str, session_id: str) -> None:
        room = self._rooms.get(doc_id, {})
        room.pop(session_id, None)
        if not room:
            self._rooms.pop(doc_id, None)
            return
        self._broadcast(room)

    def _update(self, doc_id: str, session_id: str, change: Callable[[Participant], Participant]) -> bool:
        room = self._rooms.get(doc_id, {})
        member = room.get(session_id)
        if member is None:
            return False
        member.participant = change(member.participant)
        self._broadcast(room)
        return True

    def _broadcast(self, room: dict[str, _Member]) -> None:
        participants = self._list(room)
        for member in list(room.values()):
            member.notify(participants)

    def _list(self, room: dict[str, _Member]) -> list[Participant]:
        now = self._now_ms()
        ps = [
            replace(
                m.participant,
                editing=bool(m.participant.last_edit_unix_ms)
                and now - m.participant.last_edit_unix_ms < EDITING_WINDOW_MS,
            )
            for m in room.values()
        ]
        return sorted(ps, key=lambda p: (p.name, p.session_id))


def _free_color(room: dict[str, _Member]) -> str:
    """The first palette colour nobody in the room is using."""
    used = {m.participant.color for m in room.values()}
    for color in PALETTE:
        if color not in used:
            return color
    return PALETTE[len(room) % len(PALETTE)]
