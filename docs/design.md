# Design

Distributed real-time collaboration platform (handout option C). Everything is
Python; every call between processes is gRPC (`proto/collab/v1/*.proto`).

## Architecture

```
 node 5: clients (CLI)                 node 1: LLM server
 ┌────────────────────┐                ┌─────────────────────────────┐
 │ collab_client      │                │ assist (AssistService)      │
 │ shell/demo/simulate│                │   └─ Ollama, qwen2.5:3b/1.5b│
 └─────────┬──────────┘                └──────────────▲──────────────┘
           │ CollabService (gRPC)                     │ AssistService (gRPC)
 ┌─────────▼───────────────────────────────────────────┴──┐
 │ gateway: auth, tokens, Join sessions, presence, routing │
 └─────────┬───────────────────────────────────────────────┘
           │ DocumentService (gRPC)
 ┌─────────▼───────────────────────────┐
 │ docnode: Log ─▶ StateMachine         │  (Milestone 2: three docnodes,
 │          (LocalLog today, RaftLog)   │   the Log replicated by Raft)
 └─────────────────────────────────────┘
```

| Service | Source | Port | Role |
|---|---|---|---|
| docnode | `services/docnode/src/docnode` | 50051 | Documents, history, the replicated state machine |
| assist | `services/assist/src/assist` | 50061 | LLM features; stateless, never changes a document |
| gateway | `services/gateway/src/gateway` | 50070 | The only service clients see |
| client | `clients/collab_client` | – | Library + CLI |

The docnode is the only place document state lives. The gateway holds only
per-connection state (tokens, Join sessions, presence), which is deliberately
not replicated: it describes connections to that gateway and is rebuilt when
clients reconnect.

## Handout functions → RPCs

| Handout | Our RPC | Notes |
|---|---|---|
| `login(username, password) -> (status, token?)` | `CollabService.Login` | `LoginResponse{status, token, expires_at_unix_ms}` |
| `logout(token) -> status` | `CollabService.Logout` | Also closes the token's Join streams |
| `post(token, type, data) -> status` | `CollabService.Post` | `type` = which `data` oneof is set: `edit` or `cursor` |
| `get(token, type, params) -> (status, [(id, data)])` | `CollabService.Get` | `params` oneof: `snapshot`, `history`, `presence`, `documents`; reply is `repeated Item{id, data}` |
| `processBusinessRequest(requestId, payload, context)` | `DocumentService.SubmitOperations` (called by the gateway for `Post(edit)`) | The request id is the operation's `op_id`; the payload its changes; the context its `base_revision` and user |
| `getLLMAnswer(requestId, query, context) -> (requestId, answer)` | `AssistService.GetLLMAnswer` | `context` is a `DocumentSnapshot`; reached by clients through `CollabService.Assist(ask)` |
| `requestVote(...)`, `appendEntries(...)` | `RaftService` (Milestone 2) | `proto/collab/v1/raft.proto` |

Live updates use two server streams in addition: `Join` (the document's
operations and presence) and `Assist` (streamed LLM output).

Every client-facing reply carries a `Status` enum (`OK`, `INVALID_CREDENTIALS`,
`UNAUTHENTICATED`, `STALE_REVISION`, `INVALID_ARGUMENT`, `UNAVAILABLE`,
`NOT_FOUND`) instead of gRPC errors, so clients handle one set of outcomes.

## Conflict rules

A document is a sequence of revisions: revision 0 is empty, every accepted
operation adds exactly one. An operation names the revision it was made
against (`base_revision`) and its changes as UTF-16 ranges in that revision.

1. **Accept only at the current revision.** If `base_revision` is older, the
   whole batch is rejected (`ABORTED` → `STALE_REVISION` with the current
   revision) and nothing changes.
2. **The client rebases.** `CollabClient.edit` fetches the operations it
   missed (`Get(history)`), moves each of its positions past them
   (`textops.rebase`) and resends. Ties are fixed: an insertion at the same
   point as an earlier one goes after it; a deletion never swallows text
   inserted at its edges; an edit inside text someone deleted collapses to
   that point.
3. **Exactly once.** Every operation has an `op_id` = (client_id, seq). The
   state machine stores the highest seq applied per client and skips anything
   at or below it, so a retry after a timeout, a rebase or (in Milestone 2) a
   leader failover can never apply twice. One client therefore sends one edit
   at a time (the library enforces it).
4. **All or nothing.** A batch of several operations is checked completely
   before any of it is applied.
5. **Valid text.** Ranges must be sorted, non-overlapping, inside the text,
   and must not cut a surrogate pair (emoji) in half.

Positions are UTF-16 code units (the unit editors such as CodeMirror use);
the docnode stores text as UTF-16-LE bytes so a position indexes it directly.

## Determinism

`StateMachine.apply` reads no clock, no randomness and no network, and every
rejection is a deterministic outcome (`StaleError`, `InvalidOperation`), not a
failure. So replicas fed the same batches in the same order end identical and
make identical decisions. `test_replicas_agree` checks exactly this: two
state machines receive the same 300 random batches (including stale,
duplicate and invalid ones) for 20 seeds and must agree at every step, and
replaying the history must reproduce the text. This is the property the Raft
log relies on: the gateway-facing `Log` interface (`oplog.py`) has a local
implementation today and a replicated one in Milestone 2, with no other
change.

`Subscribe` streams observe the state machine without being part of it:
each subscriber has a bounded queue (1024) and a subscriber that falls behind
is dropped (`UNAVAILABLE`, subscribe again from the last revision) rather than
slowing down writers.

## Presence

`gateway/presence.py` keeps one room per document: participants (one per
Join stream), a colour from a fixed palette, the cursor/selection (from
`Post(cursor)`, with the revision it refers to) and the time of the last
edit; a participant is `editing` if that was in the last 5 seconds. Every
change broadcasts the full list, so presence can be lossy: a Join stream
whose queue is full simply skips a presence update and gets the next one.
Document operations are never dropped this way.

## Authentication

* `config/users.json` holds salted PBKDF2-SHA256 hashes (200,000 iterations),
  managed with `scripts/manage_users.py`. Demo users: alice/alice123,
  bob/bob123, carol/carol123.
* Hashing runs in a worker thread (`asyncio.to_thread`) so a login never
  blocks other clients. Unknown usernames are checked against a dummy hash
  of the same cost, so timing does not reveal which usernames exist, and the
  reply is the same `INVALID_CREDENTIALS` either way.
* Tokens are `secrets.token_urlsafe(32)`, kept in gateway memory, and expire
  after 8 hours (`GATEWAY_TOKEN_TTL_S`). Every call except Login checks the
  token. Logout revokes it and closes its Join streams at once; an expiring
  token closes its streams when it expires.
* The gateway sets every operation's `user_id` (and `doc_id`) itself, so a
  client cannot edit as someone else. Cursor updates are accepted only for
  the caller's own Join session.

## LLM

* **Separate server, local CPU model.** The Assist service is its own process
  (node 1) and talks to Ollama through its OpenAI-compatible API. Defaults:
  `qwen2.5:3b` for grammar, enhancement, summaries and questions and
  `qwen2.5:1.5b` for autocomplete, both quantized models that run on a laptop
  CPU. `ASSIST_PROVIDER=fake` gives canned answers for tests;
  `openai_compat` can point at any hosted API.
* **Domain-specific.** Every prompt is written for collaborative notes:
  grammar fixes that keep meaning and tone, summaries that keep names,
  decisions, dates and action items, rewrites that keep facts and Markdown.
* **Context-aware.** Requests carry the document text (and for grammar,
  enhance and autocomplete, the text before and after the selection) and the
  revision it came from. `GetLLMAnswer` answers *only* from the document and
  replies "The document does not say." when the answer is not there; long
  documents are trimmed to their most recent part (notes grow at the end).
* **Never changes documents.** Suggestions carry a `TextAnchor` (doc,
  revision, range) and the original text. Accepting one is an ordinary edit
  through the conflict rules above, so the LLM is never on the replicated
  path and can never make replicas diverge.
* **Robust to model output.** Models are never asked for positions; they
  quote the text to change and `anchoring.py` finds it, narrows it to whole
  changed words and drops fixes that cannot be found. JSON replies are
  validated with pydantic (`schemas.py`), with one retry on malformed JSON.
