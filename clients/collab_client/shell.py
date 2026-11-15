"""`shell`: an interactive client. Type `help` for the commands.

Positions typed in the shell are character positions in the text as shown by
`show`; the shell converts them to the UTF-16 positions the API uses.
Edits by other users arrive live and are announced between prompts.
"""

import asyncio
import getpass
import shlex

from collab.v1 import assist_pb2, gateway_pb2

from .client import CollabClient, CollabError, DocumentView
from .textops import Change, utf16_len, utf16_offset

HELP = """\
open <doc>                 open (join) a document
show                       print the text with its revision
append <text>              add text at the end ("\\n" for a new line)
insert <pos> <text>        insert at a character position
delete <start> <end>       delete characters [start, end)
cursor <pos> [<end>]       move your cursor / select a range
history [n]                the last n operations (default 10)
who                        who is in the document
docs                       all documents
grammar                    LLM grammar check of the document
enhance <start> <end> [concise|formal|clarify|expand]
                           LLM rewrite of a range
accept <n>                 apply suggestion n from the last grammar/enhance
summarize [short|medium|detailed]
complete                   LLM autocomplete at the end of the document
ask <question>             ask the LLM about the document
logout                     log out and quit
help, quit"""

MODES = {
    "concise": assist_pb2.ENHANCE_MODE_CONCISE,
    "formal": assist_pb2.ENHANCE_MODE_FORMAL,
    "clarify": assist_pb2.ENHANCE_MODE_CLARIFY,
    "expand": assist_pb2.ENHANCE_MODE_EXPAND,
}
LENGTHS = {
    "short": assist_pb2.SUMMARY_LENGTH_SHORT,
    "medium": assist_pb2.SUMMARY_LENGTH_MEDIUM,
    "detailed": assist_pb2.SUMMARY_LENGTH_DETAILED,
}


class Shell:
    def __init__(self, client: CollabClient):
        self.client = client
        self.view: DocumentView | None = None
        self.suggestions: list[assist_pb2.Suggestion] = []

    def on_event(self, event: gateway_pb2.JoinEvent) -> None:
        kind = event.WhichOneof("event")
        if kind == "operation" and event.operation.operation.user_id != self.client.username:
            op = event.operation
            print(f"\n  * {op.operation.user_id} edited -> revision {op.revision}")
        elif kind == "closed":
            print(f"\n  * stream closed: {gateway_pb2.Status.Name(event.closed.status)} {event.closed.reason}")

    def need_view(self) -> DocumentView:
        if self.view is None or self.view.closed is not None:
            raise CollabError(gateway_pb2.NOT_FOUND, "open a document first: open <doc>")
        return self.view

    def pos(self, arg: str) -> int:
        """A character position typed by the user -> UTF-16 position."""
        text = self.need_view().text
        return utf16_offset(text, max(0, min(int(arg), len(text))))

    async def edit(self, change: Change) -> None:
        result = await self.need_view().edit(change)
        note = f" (rebased/retried, {result.attempts} attempts)" if result.attempts > 1 else ""
        print(f"  ok -> revision {result.revision}{note}")
        await self.view.wait_for_revision(result.revision)

    async def run_command(self, line: str) -> bool:
        """Runs one command. Returns False to quit."""
        cmd, _, rest = line.strip().partition(" ")
        args = shlex.split(rest) if rest and cmd not in ("append", "insert", "ask") else rest.split()
        c = self.client

        if cmd in ("quit", "exit"):
            return False
        if cmd == "help":
            print(HELP)
        elif cmd == "open":
            if self.view:
                await self.view.close()
            self.view = await c.join(args[0], self.on_event)
            print(f"  opened {args[0]} at revision {self.view.revision} (session {self.view.session_id})")
        elif cmd == "show":
            v = self.need_view()
            print(f"--- {v.doc_id} @ revision {v.revision} ---\n{v.text}\n---")
        elif cmd == "append":
            text = rest.replace("\\n", "\n")
            await self.edit(Change(utf16_len(self.need_view().text), utf16_len(self.view.text), text))
        elif cmd == "insert":
            where, _, text = rest.partition(" ")
            p = self.pos(where)
            await self.edit(Change(p, p, text.replace("\\n", "\n")))
        elif cmd == "delete":
            await self.edit(Change(self.pos(args[0]), self.pos(args[1]), ""))
        elif cmd == "cursor":
            v = self.need_view()
            anchor = self.pos(args[0])
            head = self.pos(args[1]) if len(args) > 1 else anchor
            print(f"  {gateway_pb2.Status.Name(await c.move_cursor(v, anchor, head))}")
        elif cmd == "history":
            v = self.need_view()
            n = int(args[0]) if args else 10
            for op in (await c.history(v.doc_id, max(0, v.revision - n))):
                changes = ", ".join(f"[{ch.range.start}:{ch.range.end}]->{ch.insert!r}" for ch in op.operation.changes)
                print(f"  rev {op.revision:>4} {op.operation.user_id:<8} {changes}")
        elif cmd == "who":
            v = self.need_view()
            status, items = await c.get("presence", doc_id=v.doc_id)
            for _, p in items:
                cursor = f" cursor {p.cursor.anchor}-{p.cursor.head}" if p.HasField("cursor") else ""
                me = " (you)" if p.session_id == v.session_id else ""
                print(f"  {p.name}{me} {p.color}{cursor}{' editing' if p.editing else ''}")
        elif cmd == "docs":
            status, items = await c.get("documents")
            for doc_id, d in items:
                print(f"  {doc_id:<24} revision {d.revision:>5}  {d.length} chars")
        elif cmd == "grammar":
            self.suggestions = await c.check_grammar(self.need_view())
            self.print_suggestions()
        elif cmd == "enhance":
            v = self.need_view()
            mode = MODES[args[2]] if len(args) > 2 else MODES["concise"]
            self.suggestions = await c.enhance(v, self.pos(args[0]), self.pos(args[1]), mode)
            self.print_suggestions()
        elif cmd == "accept":
            s = self.suggestions[int(args[0]) - 1]
            r = s.anchor.range
            result = await c.edit(self.view.doc_id, [Change(r.start, r.end, s.replacement)],
                                  s.anchor.revision, self.view.session_id)
            print(f"  applied -> revision {result.revision}")
            await self.view.wait_for_revision(result.revision)
        elif cmd == "summarize":
            v = self.need_view()
            length = LENGTHS[args[0]] if args else LENGTHS["medium"]
            async for e in c.assist_stream(v.doc_id, summarize=assist_pb2.SummarizeRequest(length=length)):
                print(e.summary.delta, end="", flush=True)
            print()
        elif cmd == "complete":
            v = self.need_view()
            end = utf16_len(v.text)
            print(v.text[-60:], end="")
            async for e in c.assist_stream(v.doc_id, autocomplete=assist_pb2.AutocompleteRequest(
                    context=v.text_context(end, end))):
                print(e.autocomplete.delta, end="", flush=True)
            print()
        elif cmd == "ask":
            answer = (await c.ask(self.need_view().doc_id, rest)).answer
            print(f"  {answer.answer}\n  (based on revision {answer.revision})")
        elif cmd == "logout":
            print(f"  {gateway_pb2.Status.Name(await c.logout())}")
            return False
        elif cmd:
            print(f"  unknown command {cmd!r}; type help")
        return True

    def print_suggestions(self) -> None:
        if not self.suggestions:
            print("  no suggestions")
        for i, s in enumerate(self.suggestions, 1):
            print(f"  {i}. {s.original!r} -> {s.replacement!r}  {s.reason}")


async def run_shell(address: str, username: str | None, password: str | None, doc: str | None) -> int:
    async with CollabClient(address) as client:
        username = username or await asyncio.to_thread(input, "username: ")
        password = password or await asyncio.to_thread(getpass.getpass, "password: ")
        reply = await client.login(username, password)
        if reply.status != gateway_pb2.OK:
            print(f"login failed: {gateway_pb2.Status.Name(reply.status)}")
            return 1
        print(f"logged in as {username}. Type help for commands.")
        shell = Shell(client)
        if doc:
            await shell.run_command(f"open {doc}")
        while True:
            try:
                line = await asyncio.to_thread(input, f"{username}> ")
            except (EOFError, KeyboardInterrupt):
                break
            try:
                if not await shell.run_command(line):
                    break
            except CollabError as err:
                print(f"  error: {err}")
            except (IndexError, ValueError, KeyError):
                print("  bad arguments; type help")
        if shell.view:
            await shell.view.close()
        return 0
