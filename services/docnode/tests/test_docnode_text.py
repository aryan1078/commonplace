import pytest

from docnode.text import Change, InvalidChange, apply, decode, encode, length


def run(doc: str, *changes: Change) -> str:
    return decode(apply(encode(doc), changes))


@pytest.mark.parametrize(
    "doc, changes, want",
    [
        ("hello", [Change(5, 5, " world")], "hello world"),
        ("hello world", [Change(5, 11, "")], "hello"),
        ("hello world", [Change(6, 11, "there")], "hello there"),
        # several changes; positions refer to the original
        ("abcdef", [Change(0, 1, "X"), Change(2, 2, "-"), Change(4, 6, "")], "Xb-cd"),
        # two inserts at the same point keep their order
        ("ab", [Change(1, 1, "1"), Change(1, 1, "2")], "a12b"),
        ("same", [], "same"),
    ],
    ids=["insert", "delete", "replace", "several", "same-point", "empty"],
)
def test_insert_delete_replace(doc, changes, want):
    assert run(doc, *changes) == want


def test_positions_are_utf16():
    doc = "🎉 party"  # the emoji is 2 UTF-16 units
    assert length(doc) == 8
    assert run(doc, Change(3, 3, "big ")) == "🎉 big party"
    assert run("नमस्ते", Change(6, 6, "!")) == "नमस्ते!"


@pytest.mark.parametrize(
    "changes",
    [
        [Change(0, 99, "")],  # past end
        [Change(-1, 0, "")],  # negative
        [Change(3, 2, "")],  # reversed
        [Change(0, 4, ""), Change(3, 5, "")],  # overlapping
        [Change(4, 4, "x"), Change(1, 1, "y")],  # unsorted
        [Change(1, 1, "x")],  # splits the emoji
        [Change(0, 1, "")],  # ends inside the pair
    ],
    ids=["past-end", "negative", "reversed", "overlapping", "unsorted", "splits-emoji", "ends-inside-pair"],
)
def test_invalid_changes_are_rejected(changes):
    with pytest.raises(InvalidChange):
        apply(encode("🎉 abc"), changes)


def test_apply_does_not_modify_input():
    doc = encode("abc")
    apply(doc, [Change(0, 3, "xyz")])
    assert decode(doc) == "abc"
