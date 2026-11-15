from gateway.presence import EDITING_WINDOW_MS, Cursor, Hub, Participant


class Recorder:
    def __init__(self):
        self.last: list[Participant] = []
        self.n = 0

    def __call__(self, participants):
        self.last, self.n = participants, self.n + 1


class Clock:
    def __init__(self, ms=1_700_000_000_000):
        self.ms = ms

    def __call__(self):
        return self.ms


def test_join_leave_and_colours():
    h = Hub()
    a, b = Recorder(), Recorder()
    leave_a = h.join("doc", Participant("s1", "Asha"), a)
    leave_b = h.join("doc", Participant("s2", "Bala"), b)

    assert len(a.last) == 2 and len(b.last) == 2
    assert a.last[0].color != a.last[1].color

    leave_b()
    leave_b()  # safe twice
    assert [p.name for p in a.last] == ["Asha"]
    leave_a()
    assert h.participants("doc") == []


def test_cursor_and_edit_updates_are_broadcast():
    clock = Clock()
    h = Hub(now_ms=clock)
    a, b = Recorder(), Recorder()
    h.join("doc", Participant("s1", "Asha"), a)
    h.join("doc", Participant("s2", "Bala"), b)

    h.update_cursor("doc", "s2", Cursor(revision=3, anchor=4, head=9))
    bala = a.last[1]
    assert bala.cursor is not None and bala.cursor.head == 9

    h.mark_edited("doc", "s1")
    assert b.last[0].last_edit_unix_ms == clock.ms and b.last[0].editing

    clock.ms += EDITING_WINDOW_MS  # time passes: no longer "editing"
    assert not h.participants("doc")[0].editing


def test_rooms_are_separate():
    h = Hub()
    a, b = Recorder(), Recorder()
    h.join("doc1", Participant("s1", "Asha"), a)
    h.join("doc2", Participant("s2", "Bala"), b)
    assert len(a.last) == 1 and len(b.last) == 1
    assert not h.update_cursor("doc1", "s2", Cursor(0, 0, 0))  # wrong room: ignored
    assert a.n == 1
