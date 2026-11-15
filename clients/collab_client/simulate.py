"""`simulate`: many users editing one document at once, then a consistency check.

Each simulated user logs in, joins the same fresh document and makes random
inserts and deletes against whatever revision it currently sees, so edits
collide constantly and most of them go through the stale-rebase-resend path.
At the end three things must hold:

  1. the final revision is exactly users * edits (every edit applied once);
  2. replaying the history from an empty text reproduces the final text;
  3. every client's live copy (built only from its Join stream) is identical.
"""

import asyncio
import random
import time
import uuid
from dataclasses import dataclass

from .client import CollabClient, CollabError, DocumentView
from .textops import Change, apply_changes, utf16_len

WORDS = ["lorem ", "ipsum ", "raft ", "grpc ", "🎉", "नमस्ते ", "\n", "x"]
DEMO_USERS = [("alice", "alice123"), ("bob", "bob123"), ("carol", "carol123")]


@dataclass
class SimulationReport:
    doc_id: str
    expected_revision: int
    final_revision: int
    replay_matches: bool
    clients_agree: bool
    attempts: int  # total Post attempts, including rebases and retries
    seconds: float

    @property
    def consistent(self) -> bool:
        return (self.final_revision == self.expected_revision
                and self.replay_matches and self.clients_agree)

    def lines(self) -> list[str]:
        return [
            f"document          {self.doc_id}",
            f"final revision    {self.final_revision} (expected {self.expected_revision})",
            f"history replay    {'matches' if self.replay_matches else 'DIFFERS'}",
            f"client copies     {'identical' if self.clients_agree else 'DIFFER'}",
            f"attempts          {self.attempts} for {self.expected_revision} edits "
            f"({self.attempts - self.expected_revision} rebases/retries)",
            f"time              {self.seconds:.1f}s",
            "CONSISTENT" if self.consistent else "INCONSISTENT",
        ]


def random_change(r: random.Random, view: DocumentView) -> Change:
    text = view.text
    size = utf16_len(text)
    # Pick character boundaries (never inside an emoji), then convert to UTF-16.
    i = r.randint(0, len(text))
    start = utf16_len(text[:i])
    if text and r.random() < 0.3:
        j = min(len(text), i + r.randint(1, 4))
        return Change(start, utf16_len(text[:j]), "")
    return Change(start, min(start, size), r.choice(WORDS))


async def run_simulation(address: str, users: int, edits: int, seed: int | None = None,
                         credentials: list[tuple[str, str]] = DEMO_USERS) -> SimulationReport:
    doc_id = f"sim-{uuid.uuid4().hex[:8]}"
    r = random.Random(seed)
    clients = [CollabClient(address) for _ in range(users)]
    views: list[DocumentView] = []
    began = time.monotonic()
    try:
        for i, client in enumerate(clients):
            name, password = credentials[i % len(credentials)]
            reply = await client.login(name, password)
            if reply.status != 0:
                raise CollabError(reply.status, f"login as {name}")
        views = [await client.join(doc_id) for client in clients]

        async def user(view: DocumentView, rng: random.Random) -> int:
            attempts = 0
            for _ in range(edits):
                await asyncio.sleep(rng.uniform(0, 0.01))
                result = await view.edit(random_change(rng, view))
                attempts += result.attempts
            return attempts

        rngs = [random.Random(r.random()) for _ in views]
        attempts = sum(await asyncio.gather(*(user(v, g) for v, g in zip(views, rngs))))

        expected = users * edits
        snapshot = await clients[0].snapshot(doc_id)
        for view in views:  # let every live copy catch up
            await view.wait_for_revision(snapshot.revision, timeout=30)

        replayed = b""
        for committed in await clients[0].history(doc_id):
            replayed = apply_changes(replayed, [
                Change(c.range.start, c.range.end, c.insert) for c in committed.operation.changes])
        return SimulationReport(
            doc_id=doc_id,
            expected_revision=expected,
            final_revision=snapshot.revision,
            replay_matches=replayed.decode("utf-16-le") == snapshot.text,
            clients_agree=all(v.text == snapshot.text and v.revision == snapshot.revision for v in views),
            attempts=attempts,
            seconds=time.monotonic() - began,
        )
    finally:
        for view in views:
            await view.close()
        for client in clients:
            await client.close()
