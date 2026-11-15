import asyncio

from assist.providers.base import Provider
from assist.tasks.autocomplete import autocomplete
from collab.v1 import assist_pb2


class Streaming(Provider):
    def __init__(self, *pieces):
        self.pieces = pieces

    async def complete(self, task, messages, **kwargs):
        return ""

    async def stream(self, task, messages, **kwargs):
        for p in self.pieces:
            yield p


def complete(before, *pieces):
    request = assist_pb2.AutocompleteRequest(context=assist_pb2.TextContext(request_id="a", before=before))

    async def collect():
        return "".join([r.delta async for r in autocomplete(Streaming(*pieces), request, None)])

    return asyncio.run(collect())


def test_adds_the_missing_space_after_a_word():
    assert complete("so before then", "I should", " check") == " I should check"


def test_does_not_double_a_typed_space():
    assert complete("so before then ", " I should") == "I should"
    assert complete("so before then ", " ", "I should") == "I should"


def test_keeps_punctuation_and_mid_word_continuations():
    assert complete("Hello", ", world") == ", world"
    assert complete("Done.", "Next") == " Next"
