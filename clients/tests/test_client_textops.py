import random

from collab_client.textops import Change, apply_changes, map_position, rebase, utf16_len


def run(text: str, changes) -> str:
    return apply_changes(text.encode("utf-16-le"), changes).decode("utf-16-le")


def test_position_moves_past_earlier_changes():
    theirs = [Change(0, 0, "abc"), Change(5, 7, "")]
    assert map_position(2, theirs, after_inserts=True) == 5
    assert map_position(9, theirs, after_inserts=True) == 10
    assert map_position(6, theirs, after_inserts=True) == 8  # inside deleted text
    assert map_position(6, theirs, after_inserts=False) == 8


def test_tie_with_insertion_at_same_point():
    theirs = [Change(3, 3, "XY")]
    assert map_position(3, theirs, after_inserts=True) == 5
    assert map_position(3, theirs, after_inserts=False) == 3


def test_concurrent_inserts_at_same_place_both_survive():
    base = "hello"
    theirs = [Change(5, 5, " world")]
    ours = [Change(5, 5, "!")]
    assert run(run(base, theirs), rebase(ours, theirs)) == "hello world!"


def test_deletion_does_not_swallow_text_inserted_at_its_edges():
    base = "abcdef"
    theirs = [Change(2, 2, "<"), Change(4, 4, ">")]
    ours = [Change(2, 4, "")]  # delete "cd"
    assert run(run(base, theirs), rebase(ours, theirs)) == "ab<>ef"


def test_edit_inside_deleted_text_collapses_safely():
    base = "abcdef"
    theirs = [Change(1, 5, "")]  # someone deleted "bcde"
    ours = [Change(2, 3, "X")]  # we replaced "c"
    assert run(run(base, theirs), rebase(ours, theirs)) == "aXf"


def test_utf16_positions_with_emoji():
    base = "🎉ab"
    theirs = [Change(0, 0, "😀")]
    ours = [Change(3, 3, "!")]  # between a and b
    assert run(run(base, theirs), rebase(ours, theirs)) == "😀🎉a!b"
    assert utf16_len("😀🎉") == 4


def test_random_rebases_always_produce_valid_changes():
    r = random.Random(7)
    for _ in range(2000):
        base = "".join(r.choice("ab🎉 ") for _ in range(r.randint(0, 12)))
        units = utf16_len(base)

        def edit():
            out, pos = [], 0
            for _ in range(r.randint(1, 3)):
                start = r.randint(pos, units)
                end = r.randint(start, units)
                out.append(Change(start, end, r.choice(["", "x", "yz"])))
                pos = end
            return out

        def ok(changes):  # never cut the emoji in half
            text = base.encode("utf-16-le")
            return all(not (0 < p < units and 0xDC00 <= int.from_bytes(text[2*p:2*p+2], "little") <= 0xDFFF)
                       for c in changes for p in (c.start, c.end))

        theirs, ours = edit(), edit()
        if not (ok(theirs) and ok(ours)):
            continue
        after = run(base, theirs)
        moved = rebase(ours, theirs)
        prev = 0
        for c in moved:
            assert prev <= c.start <= c.end <= utf16_len(after)
            prev = c.end
        run(after, moved)  # applies cleanly
