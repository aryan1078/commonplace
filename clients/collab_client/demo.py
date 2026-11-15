"""`demo`: a scripted walkthrough of every feature, narrated for the video.

Three users log in, open one document, edit it (two of them on the same
revision at the same moment), watch each other's presence, use every LLM
feature, and finally one logs out, which closes their live stream.
"""

import asyncio
import uuid

from collab.v1 import assist_pb2, gateway_pb2

from .client import CollabClient, CollabError, DocumentView
from .textops import Change, utf16_len, utf16_offset

S = gateway_pb2

NOTES = (
    "Project sync, 16 Nov.\n"
    "We replicate every document with Raft across three nodes. "
    "The LLM runs on its own server and only gives suggestions.\n"
    "Decision: the demo is on Tuesday at 4 pm and i will record the video.\n"
)


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def show(view: DocumentView, who: str) -> None:
    print(f"  [{who}] revision {view.revision}: {view.text!r}")


def who(view: DocumentView) -> str:
    parts = []
    for p in view.participants:
        cursor = f" cursor@{p.cursor.head}" if p.HasField("cursor") else ""
        parts.append(f"{p.name}({p.color}{cursor}{', editing' if p.editing else ''})")
    return ", ".join(parts)


async def llm(title: str, coro) -> None:
    """Runs one LLM step; a slow or missing model must not stop the demo."""
    try:
        await coro
    except (CollabError, asyncio.TimeoutError) as err:
        print(f"  {title} failed: {err}")


async def run_demo(address: str) -> int:
    doc_id = f"demo-{uuid.uuid4().hex[:6]}"
    alice, bob, carol = CollabClient(address), CollabClient(address), CollabClient(address)
    views: list[DocumentView] = []
    try:
        step("1. Login (authentication)")
        bad = await carol.login("carol", "wrong-password")
        print(f"  carol with a wrong password -> {gateway_pb2.Status.Name(bad.status)}")
        for client, name in ((alice, "alice"), (bob, "bob"), (carol, "carol")):
            reply = await client.login(name, f"{name}123")
            if reply.status != S.OK:
                print(f"  login as {name} failed: {gateway_pb2.Status.Name(reply.status)}")
                return 1
            print(f"  {name} logged in, token {reply.token[:8]}...")

        step(f"2. Everyone opens document {doc_id} (Join stream)")
        a, b, c = (await alice.join(doc_id), await bob.join(doc_id), await carol.join(doc_id))
        views = [a, b, c]
        await a.wait_for(lambda v: len(v.participants) == 3)
        print(f"  presence seen by alice: {who(a)}")

        step("3. Alice types the meeting notes; everyone receives them live")
        typed = await a.edit(Change(0, 0, NOTES))
        for v in views:
            await v.wait_for_revision(typed.revision)
        show(b, "bob sees")

        step("4. Cursors and 'editing' status (presence)")
        await bob.move_cursor(b, utf16_len(NOTES) - 1)
        await a.wait_for(lambda v: any(p.name == "bob" and p.HasField("cursor") for p in v.participants))
        print(f"  presence seen by alice: {who(a)}")

        step("5. Alice and Bob edit the SAME revision at the same moment")
        base = a.revision
        title_end = utf16_offset(NOTES, NOTES.index("\n"))
        ra, rb = await asyncio.gather(
            alice.edit(doc_id, [Change(title_end, title_end, " (weekly)")], base, a.session_id),
            bob.edit(doc_id, [Change(utf16_len(NOTES), utf16_len(NOTES), "Action: bob books the room.\n")],
                     base, b.session_id),
        )
        print(f"  both were based on revision {base}")
        print(f"  alice's edit: revision {ra.revision} after {ra.attempts} attempt(s)")
        print(f"  bob's edit:   revision {rb.revision} after {rb.attempts} attempt(s)")
        print("  (the second one was rejected as STALE_REVISION, rebased onto the new text and resent)")
        final = max(ra.revision, rb.revision)
        for v in views:
            await v.wait_for_revision(final)
        show(c, "carol sees")
        print(f"  all three copies identical: {a.text == b.text == c.text}")

        step("6. Version history")
        for op in (await carol.history(doc_id))[-3:]:
            inserted = "".join(ch.insert for ch in op.operation.changes)
            print(f"  revision {op.revision} by {op.operation.user_id}: inserted {inserted[:40]!r}")
        status, docs = await carol.get("documents")
        print(f"  documents on the cluster: {', '.join(f'{i} (rev {d.revision})' for i, d in docs)}")

        step("7. LLM: grammar check, then accept the first suggestion")

        async def grammar() -> None:
            suggestions = await alice.check_grammar(a)
            for s in suggestions:
                print(f"  {s.original!r} -> {s.replacement!r} ({s.reason})")
            if suggestions:
                s = suggestions[0]
                r = s.anchor.range
                result = await alice.edit(doc_id, [Change(r.start, r.end, s.replacement)], s.anchor.revision, a.session_id)
                await a.wait_for_revision(result.revision)
                print(f"  accepted as an ordinary edit -> revision {result.revision}")
        await llm("grammar", grammar())

        step("8. LLM: enhance a sentence (concise)")

        async def enhance() -> None:
            sentence = "The LLM runs on its own server and only gives suggestions."
            start = utf16_offset(a.text, a.text.index(sentence))
            suggestions = await alice.enhance(a, start, start + utf16_len(sentence), assist_pb2.ENHANCE_MODE_CONCISE)
            for s in suggestions:
                print(f"  {s.original!r} -> {s.replacement!r}")
            if not suggestions:
                print("  (the model suggests no change)")
        await llm("enhance", enhance())

        step("9. LLM: summarize the notes (streamed)")

        async def summarize() -> None:
            print("  ", end="")
            async for e in carol.assist_stream(doc_id, summarize=assist_pb2.SummarizeRequest(
                    length=assist_pb2.SUMMARY_LENGTH_SHORT)):
                print(e.summary.delta, end="", flush=True)
            print()
        await llm("summarize", summarize())

        step("10. LLM: autocomplete at the end of the document (streamed)")

        async def complete() -> None:
            ctx = a.text_context(utf16_len(a.text), utf16_len(a.text))
            print("  ...", end="")
            async for e in alice.assist_stream(doc_id, autocomplete=assist_pb2.AutocompleteRequest(context=ctx)):
                print(e.autocomplete.delta, end="", flush=True)
            print()
        await llm("autocomplete", complete())

        step("11. LLM: questions answered only from the document (getLLMAnswer)")

        async def ask() -> None:
            for question in ("When is the demo?", "What is the budget?"):
                answer = (await bob.ask(doc_id, question)).answer
                print(f"  Q: {question}\n  A: {answer.answer}  (based on revision {answer.revision})")
        await llm("ask", ask())

        step("12. Bob logs out: his live stream is closed and his token stops working")
        old_token = bob.token
        print(f"  logout -> {gateway_pb2.Status.Name(await bob.logout())}")
        await b.wait_for(lambda v: v.closed is not None)
        print(f"  bob's Join stream closed: {gateway_pb2.Status.Name(b.closed.status)} ({b.closed.reason})")
        bob.token = old_token  # replay the old token on purpose
        status, _ = await bob.get("documents")
        print(f"  bob replays his old token -> {gateway_pb2.Status.Name(status)}")
        await a.wait_for(lambda v: len(v.participants) == 2)
        print(f"  presence seen by alice: {who(a)}")

        step("Done")
        snap = await alice.snapshot(doc_id)
        ok = a.text == c.text == snap.text
        print(f"  final revision {snap.revision}; alice, carol and the server agree: {ok}")
        return 0 if ok else 1
    finally:
        for v in views:
            await v.close()
        for client in (alice, bob, carol):
            await client.close()
