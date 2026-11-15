import asyncio

import grpc
import pytest

from assist.config import Settings
from assist.providers.base import Provider
from assist.providers.fake import FakeProvider
from assist.server import AssistService
from assist.tasks.answer import (
    NOT_IN_DOCUMENT,
    OMITTED_MARKER,
    EmptyQuery,
    build_messages,
    get_llm_answer,
    trim_document,
)
from collab.v1 import assist_pb2, assist_pb2_grpc, common_pb2

NOTES = (
    "Team meeting, 30 Sept.\n"
    "We agreed to use Raft for replication. Krishna owns the Assist service.\n"
    "The next demo is on Friday at 4 pm."
)


def ask(provider, query, text=NOTES, revision=7):
    request = assist_pb2.GetLLMAnswerRequest(
        request_id="q1",
        query=query,
        context=common_pb2.DocumentSnapshot(doc_id="d", revision=revision, text=text),
    )
    return asyncio.run(get_llm_answer(provider, request, None))


class RecordingProvider(Provider):
    def __init__(self, answer="  An answer.  "):
        self.answer = answer
        self.messages = None

    async def complete(self, task, messages, **kwargs):
        self.messages = messages
        return self.answer

    async def stream(self, task, messages, **kwargs):
        yield ""


def test_fake_answers_from_the_document():
    reply = ask(FakeProvider(), "When is the next demo?")
    assert reply.answer == "The next demo is on Friday at 4 pm."
    assert (reply.request_id, reply.revision) == ("q1", 7)


def test_fake_says_when_the_document_has_no_answer():
    assert ask(FakeProvider(), "What is the budget?").answer == NOT_IN_DOCUMENT


def test_empty_document_skips_the_model():
    provider = RecordingProvider()
    assert ask(provider, "Anything?", text="  ").answer == NOT_IN_DOCUMENT
    assert provider.messages is None


def test_empty_query_is_rejected():
    with pytest.raises(EmptyQuery):
        ask(FakeProvider(), "   ")


def test_prompt_restricts_the_model_to_the_document():
    provider = RecordingProvider()
    assert ask(provider, "Who owns Assist?").answer == "An answer."
    system, user = provider.messages
    assert "only the document" in system["content"] and NOT_IN_DOCUMENT in system["content"]
    assert NOTES in user["content"] and user["content"].endswith("Question: Who owns Assist?")


def test_long_documents_keep_their_most_recent_part():
    text = "old words " * 2000 + "\nThe newest line."
    trimmed = trim_document(text, limit=500)
    assert trimmed.startswith(OMITTED_MARKER) and trimmed.endswith("The newest line.")
    assert len(trimmed) <= 500 + len(OMITTED_MARKER)
    assert not trimmed[len(OMITTED_MARKER):].startswith(("ld", "rds"))  # no half words
    assert trim_document("short") == "short"
    assert OMITTED_MARKER in build_messages("q", text)[1]["content"]


def test_grpc_endpoint():
    settings = Settings(
        provider="fake", base_url="", api_key="", model="", fast_model="", reasoning_effort=None,
        port=0, max_input_chars=1000, max_summary_chars=1000, default_timeout_s=5,
    )

    async def main():
        server = grpc.aio.server()
        assist_pb2_grpc.add_AssistServiceServicer_to_server(AssistService(FakeProvider(), settings), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = assist_pb2_grpc.AssistServiceStub(channel)
                reply = await stub.GetLLMAnswer(
                    assist_pb2.GetLLMAnswerRequest(
                        request_id="r", query="Who owns the Assist service?",
                        context=common_pb2.DocumentSnapshot(doc_id="d", revision=3, text=NOTES),
                    )
                )
                assert "Krishna" in reply.answer and reply.revision == 3
                with pytest.raises(grpc.aio.AioRpcError) as info:
                    await stub.GetLLMAnswer(assist_pb2.GetLLMAnswerRequest(request_id="r"))
                assert info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        finally:
            await server.stop(None)

    asyncio.run(main())


def test_paraphrased_refusal_becomes_the_exact_sentence():
    assert ask(RecordingProvider("The document does not say about the budget."), "Budget?").answer == NOT_IN_DOCUMENT
    assert ask(RecordingProvider("the document does not say"), "Budget?").answer == NOT_IN_DOCUMENT
    assert ask(RecordingProvider("Friday."), "When?").answer == "Friday."
