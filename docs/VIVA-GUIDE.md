# Commonplace — understand your Advanced OS project

Read sections 1–8 first. Then run the app and follow section 17. The later sections connect what you see to the code and the questions an examiner can ask.

## 1. What did we build?

We built a shared document editor. Two people can sign in, open the same document and write in it. Each person sees the other person's saved changes. They can see who is present, inspect earlier edits and ask a separate AI service for help with writing.

The Advanced OS problem is what happens when a server fails. A document stored only in one program's memory disappears when that program stops. Our original baseline did exactly that in testing. Eight clients made 200 edits successfully, but restarting the only document server returned that document to an empty version 0.

The improved project keeps an ordered edit log on three document servers. Each server has its own disk file. One is elected leader. It coordinates new changes. A change succeeds after a majority has recorded it and the leader has applied it. With three voters, a majority is two.

If one voter stops, the two survivors can continue. If two stop, the remaining voter must wait. This protects the shared document from two disconnected groups independently claiming to have saved incompatible changes.

A useful opening answer in the viva is this.

> Our project is a collaborative document editor written in Python. We use gRPC between the client, gateway, document replicas and AI service. Three document replicas use Raft to agree on the order of edits. Each persists a log in SQLite. Users have live updates, presence, version history and optional writing suggestions. We demonstrate that acknowledged edits survive leader failure and a full process restart.

Only claim a physical multi-machine deployment if you have actually run one. Our measured rehearsal uses separate processes on one laptop.

## 2. What does “distributed” mean here?

A process is a running program. A server is a process that waits for requests. A client is a process that sends requests. A node is one participating server or machine, depending on the deployment being discussed.

Our programs talk through network addresses such as localhost:50070. The hostname identifies the machine. The port identifies the service on that machine. Localhost means this same computer. It is convenient for testing several independent processes without several physical laptops.

The assignment's five logical nodes map to the following deployment.

| Logical node | Program | Its job |
|---|---|---|
| 1 | Assist and local model | Generate writing suggestions on CPU |
| 2 | Document voter 1 | Store a log and participate in consensus |
| 3 | Document voter 2 | Store an independent log and vote |
| 4 | Document voter 3 | Store an independent log and vote |
| 5 | Gateway and client windows | Authenticate users, route requests and display the editor |

The voters are identical programs with different addresses and data directories. Any of them can become leader. We do not hard-code “node 1 is always leader.”

Three processes on one laptop protect against an individual process crash in the demonstration. Three processes on that same laptop all stop if the laptop loses power. Running voters on separate machines addresses that larger failure domain.

## 3. What each part does

### The desktop interface

This is the window users see. It has a login form, document list, text editor, presence avatars, history panel, writing tools and system status. The screen is built in HTML and CSS for layout, with JavaScript for interaction. A Python webview displays it as a desktop window.

The JavaScript talks locally to the Python part of that same client. The Python client makes the remote gRPC calls. This gives us a graphical interface while keeping the application's network communication in gRPC. HTML and CSS describe the screen. The distributed application services are Python.

The window is a desktop application. A public gateway address can let that desktop application connect over the internet. A normal browser does not open the native client by visiting the gateway address.

### The client library

The GUI and terminal client share the same CollabClient implementation. It sends login, get, post, join and AI requests. It keeps a live copy of the current document and automatically handles stale edits.

The client gives every editing session a random client ID and numbers its operations in sequence. It sends one edit at a time for that client ID. Different clients can edit simultaneously.

### The gateway

The gateway is the front door. It checks credentials and tokens, attaches the authenticated author's name to edits, maintains user presence and forwards document requests to the elected leader. It forwards AI requests to Assist.

The desktop client needs only the gateway address. It can continue using that address when the document leader changes. The gateway knows all three voter addresses and can discover the replacement leader.

### The document service

Every voter offers a DocumentService. It accepts commands through its log, returns snapshots and history, and streams committed changes. In cluster mode, writes go through Raft. Authoritative reads also require a quorum-backed barrier.

### The state machine

The state machine is the document-editing logic. It checks IDs, revisions and text ranges, applies valid changes, records accepted operations and remembers duplicate IDs. “State” means the documents and history currently held by a replica. A command changes that state.

It is deterministic. Giving two copies the same starting state and the same commands in the same order produces the same result. It does not call the AI, read the clock or generate randomness while applying an edit. Raft supplies the shared order, and the state machine supplies shared editing rules.

### The Raft implementation

Raft elects the leader, replicates the command log, detects missing heartbeats, determines which entries are committed and repairs a returning replica. It sits below the editing logic.

### SQLite

SQLite is an embedded database used as a durable file on each voter. It stores election state, indexed log entries and the committed boundary. Each voter owns its own database. The databases are independent. They are kept consistent by Raft messages.

### Assist and the model

Assist is a separate Python gRPC service. It receives a note or selected passage and asks a local CPU model to generate a response. Domain-specific prompts tell the model to help with collaborative notes. It supports grammar, continuation, summaries, rewrites and questions about the document. Grammar also includes explicit checks for common errors that a small model can miss.

The model does not vote and never writes directly to the document. A person accepts a suggestion, which becomes an ordinary edit through the same consensus path.

## 4. Login, passwords and tokens

An administrator creates users using scripts/manage_users.py. The project includes classroom accounts alice/alice123, bob/bob123 and carol/carol123. Those are demonstration credentials.

The client sends Login(username, password) to the gateway. The gateway checks a salted PBKDF2-SHA256 password hash. The users file stores a salt, hash and iteration count. It does not store the original password. The salt makes identical passwords produce different stored hashes. Repeated hashing makes guessing more expensive.

A successful login returns a random token. Later requests include that token. The gateway looks it up to identify the user. The normal lifetime is eight hours. Logout revokes it and closes that user's live document streams. Tokens are kept in gateway memory. Restarting the gateway requires signing in again.

The gateway writes the author's identity into every edit itself. It does not trust a client that claims to be another author.

TLS encrypts data travelling over the network and verifies the server certificate. Hashing a stored password and encrypting a network connection solve different problems. For a remote public endpoint, use TLS. The localhost classroom configuration uses an insecure gRPC channel on a controlled machine/network.

There is no public self-registration or per-document private sharing in this release. All authenticated workspace users can open the shared documents. Account management is an administrator operation.

## 5. What happens when I type?

Suppose the document currently says “Meeting notes” at version 5.

1. You type “ for Tuesday”. The screen immediately contains your local draft.
2. After a short pause, autosave computes the difference between the last acknowledged text and your draft. It sends the changed ranges, the document ID, base revision 5 and an operation ID.
3. The gateway validates your token and sets the author to your authenticated username.
4. The gateway forwards the command to the leader. A follower can return a leader hint so the gateway knows where to try next.
5. The leader records a Raft log entry on its disk and sends AppendEntries to followers.
6. A follower checks the preceding log index and term, records the new entry durably and acknowledges it.
7. Once a majority stores a current-term entry, the leader advances commitIndex. It applies all newly committed entries in order to its state machine.
8. A valid edit becomes document version 6. Only after application does a successful write response go back to the client.
9. Live subscribers receive the committed operation. Their clients apply it and display the same text. Followers learn the commit boundary in subsequent heartbeats and apply it too.

“All changes saved” means the GUI's pending draft has received the committed result. While saving or reconnecting, it displays a different status. A failed save keeps the local text so the user can retry.

Raft log positions and document versions are different numbers. An internal no-op or rejected command can occupy a log position without producing a visible document version. Creating a blank document is itself a recorded operation, so its first visible version may be 1.

## 6. Two people type at once

An edit is expressed relative to the text the author saw. A position is a location inside that version of the text. If Alice inserts text before Bob's cursor, Bob's old position needs adjustment.

Suppose Alice and Bob both see version 5. Alice's edit commits first and produces version 6. Bob then submits an edit against version 5. The state machine rejects the stale revision without changing the document. Bob's client fetches the edits after version 5, moves his intended positions past those edits and retries with the same operation ID. This position adjustment is called rebasing. If accepted, Bob's edit produces version 7.

For a simple example, the text is “Hello”. Alice adds “A ” at the beginning. Bob adds “ B” at the old end, position 5. After Alice's edit, the text is “A Hello”, so the old end has moved to position 7. Bob's client adjusts his insertion to 7 and the final text becomes “A Hello B”.

The rules also define ties. A later insertion at the same point goes after the earlier committed insertion. Deletion boundaries are adjusted so another user's text inserted at the edges is preserved. The implementation is a position-based conflict policy with deterministic rules. It does not understand the human meaning of contradictory rewrites, so people still review the resulting wording.

The GUI also handles typing while an earlier save is waiting. It keeps those extra keystrokes as a draft, merges them over the acknowledged result using the same position rules, and saves the remaining difference.

## 7. Why operation IDs matter

Imagine a write commits, but its response is lost. The client cannot tell whether the server saved it. Sending the same insertion as a completely new operation could duplicate the words.

We identify an operation with a client ID and sequence number. Retrying the same operation keeps that ID. The state machine remembers the highest accepted sequence for each client in the document and skips an already applied operation. The duplicate tracking is reconstructed together with history during disk replay.

The assumption is one outstanding edit per client ID. The library enforces this with an asyncio lock. The guarantee concerns applying the same operation ID at most once. A timeout is still an uncertain outcome until the retry or history resolves it.

## 8. Raft from the beginning

### Follower, candidate and leader

A follower normally receives messages from the leader. A candidate is trying to become leader. A leader coordinates replication. These are roles a voter can change between.

The leader sends regular heartbeats. A heartbeat is an AppendEntries request that may contain no new edit commands. It lets followers know the leader is active and carries the commit boundary.

If a follower does not hear from a leader before its election deadline, it starts an election. Our deadlines are randomized between about 0.8 and 1.4 seconds. Randomness reduces the chance that every follower starts campaigning at exactly the same instant.

### Terms

A term is a numbered election period. Starting an election increases the term. A voter that receives a higher term steps down and updates its own term. This helps the cluster recognize outdated leaders and candidates.

One vote is available per voter per term. The current term and vote are persisted before replying, so a restart cannot let a voter forget and vote twice in the same term.

### Winning an election

A candidate votes for itself and sends RequestVote to the other voters. With three voters, one additional vote is enough to reach two. A candidate cannot win using only its own vote.

A voter checks the candidate's last log term and index. It grants a vote only if the candidate's log is at least as up to date and the voter has an available vote in that term. Last term is compared first, then last index. A longer log with an older last term is not automatically fresher.

If votes split, nobody may win that attempt. After another randomized timeout, a later election can resolve it. An isolated voter may increase its term repeatedly, but it cannot gain a majority alone.

### The log

A log is an ordered list of commands. Each entry has an index, term and command payload. Replicas must agree about the committed prefix of that list. The log contains commands to edit documents and internal no-ops used for coordination.

The leader's AppendEntries message names the entry immediately before the proposed entries. The follower verifies that preceding index and term. A mismatch means the follower needs repair. The leader moves that follower's nextIndex backward until it finds a shared prefix, then sends the missing suffix.

### nextIndex and matchIndex

The leader maintains these independently for each follower. nextIndex is the next log position to try sending. matchIndex is the highest position the follower has confirmed matching. These help a leader catch up a slow follower without forcing every replica to operate at the same speed.

### Commitment and application

Stored means an entry exists in a local log. Committed means consensus has established the entry as part of the agreed history. Applied means a replica has run that committed command through its state machine.

commitIndex is the highest committed log position a replica knows. appliedIndex is the highest position it has executed. A follower can briefly lag while catching up.

The leader advances commitment based on a majority for entries in its current term. It does not simply commit any old-term entry because two copies happen to contain it. Committing a current-term entry also commits the preceding prefix. The current-term restriction is an important Raft safety rule.

### Why a majority works

Any two majorities of a three-voter cluster share at least one voter. Election log-freshness checks and log-matching rules work with that intersection to protect committed history across leader changes. A quorum of two tolerates one unavailable voter. A five-voter cluster would need three and tolerate two.

### Why the former leader steps down

The implementation steps down after it loses recent contact with a majority. An isolated former leader cannot confirm new writes or authoritative reads. Its live streams can end, allowing the gateway to reconnect them to the replacement.

## 9. What survives each failure?

| Failure | What happens |
|---|---|
| One follower process stops | Leader and the other follower can keep committing |
| Leader process stops | The two survivors elect a replacement and the gateway discovers it |
| Two voter processes stop | The survivor cannot confirm writes or authoritative reads |
| A disconnected former leader remains reachable by a client | It cannot complete a quorum barrier and steps down after losing majority contact |
| A lagging voter returns | Leader repairs missing or conflicting uncommitted entries and sends commitment progress |
| All voter processes restart with the original disks | Committed commands replay to rebuild text, history and duplicate tracking, then a new election occurs |
| Voter data directories are deleted | Their durable data is gone. The prototype has no external backup restoration feature |
| Gateway restarts | Voter documents persist, but users sign in again because sessions were in gateway memory |
| AI service stops | Editing still has its own consensus path. AI requests report unavailable |
| Whole laptop stops with all services on it | All local processes stop. This is a shared host failure until the machine returns |

An uncommitted edit may disappear during repair. The client must wait for acknowledgment before treating its draft as saved. In the failure demo, distinguish “text is visible in the editor” from “the save has been acknowledged.”

## 10. Disk recovery in detail

Each voter uses a SQLite file in its own data directory. SQLite transactions make related local writes atomic. WAL mode maintains a write-ahead log. synchronous FULL requests strong durability behavior from SQLite and the operating system.

The stored state includes currentTerm, votedFor, commitIndex, indexed entries and the node's fixed identity/membership. A directory is tied to that configuration to avoid accidentally using another voter's disk.

On startup the server begins with an empty in-memory state machine and replays its committed prefix in order. That rebuilds all document text, accepted author history and duplicate counters from one source. Rejected stale or malformed commands are deterministic outcomes, so replay continues after them. Uncommitted entries wait for reconciliation with the elected leader.

This release retains the entire log. It does not implement snapshots, compaction or snapshot transfer. That is easy to explain and verify for the assignment workload, but disk usage and replay time grow as the project runs longer.

## 11. Reads can also be wrong

Strong consistency means operations behave like one agreed sequence. If an edit has succeeded, a later authoritative read must reflect that edit or a later state. This property is often discussed as linearizability for the critical operations.

A missing heartbeat is a failure suspicion. A server cannot immediately tell whether a peer has crashed, is slow or is separated by the network. Majority rules protect safety while timeouts help the system make progress.

It is possible for an old leader to be alive but disconnected from the majority. It may still have an outdated document in memory. Answering a read immediately from that memory would let a user see an older state as if it were current.

Our authoritative document reads use a quorum-backed barrier. The leader commits a no-op in the current term and waits until it has applied that prefix before returning the read. A no-op changes no document text. It confirms a current consensus point. This is a simple read-safety approach with extra log and replication overhead.

The system-status panel serves a different purpose. It deliberately displays each replica's local observations so we can see lag and recovery. Those values are diagnostic. Briefly different applied indices or document versions can be expected during catch-up. Compare digests at the same document revision after convergence to verify agreement.

## 12. gRPC, protobuf and asynchronous Python

RPC means remote procedure call. It lets one program ask another program to run an operation with defined input and output messages. gRPC provides the transport, generated client/server interfaces, status handling and streaming.

Protocol Buffer files under proto/collab/v1 describe message fields and service methods. The generation script produces Python message classes and stubs. A stub is the client's callable interface to the remote service. Generated files are rebuilt when the contracts change.

Important methods are the following.

| Method | What it does |
|---|---|
| Login / Logout | Start or revoke a user session |
| Post | Send an edit or cursor update |
| Get | Read a document snapshot, history, presence or document list |
| Join | Keep a stream open for live edits and presence |
| Assist | Request a writing tool and receive its result |
| ClusterStatus | Fetch authenticated replica diagnostics through the gateway |
| SubmitOperations | Send a batch to the document log |
| GetSnapshot / GetHistory / Subscribe | Document state, ordered operations and live committed updates |
| RequestVote | Ask for a vote in a term |
| AppendEntries | Replicate entries or deliver a heartbeat |

A unary RPC has one request and one response. A server stream starts with a request and can deliver many responses over time. Join and Subscribe use streams to keep clients updated. Polling the local GUI state simply reads the Python client's live copy; it is not a replacement for the gRPC update stream.

asyncio lets a Python service wait for several network calls without blocking all other work. One event loop owns the consensus state. A slow peer RPC is awaited without holding a state-mutation lock. Password hashing and model inference run in worker threads because they perform CPU work. Model requests are serialized because the model instance should not generate concurrently without coordination.

## 13. Presence, cursors and UTF-16

Presence means who is currently in a document. The gateway tracks active Join sessions and sends participant lists to clients. Cursor updates carry the selection range and the document revision it refers to. Editing status is temporary activity information.

Presence describes live connections to the gateway. We rebuild it when people reconnect. We do not put every cursor movement in the durable Raft edit log.

An emoji can occupy two UTF-16 code units even though a person sees one symbol. Browser-style text controls use UTF-16 positions. Python normally indexes Unicode code points. We convert carefully so an edit does not split an emoji in half. The server validates text ranges and clients share the same unit convention.

## 14. What the AI does and where it can fail

Grammar asks for quoted original text, a replacement and an explanation. The server locates the quote in the selected passage and produces an anchored suggestion. The model does not invent a numerical cursor offset.

Autocomplete proposes text at the cursor. Summarization receives document text and a requested length. Enhancement rewrites the selected passage in a chosen style. Q&A receives a question and document context with instructions to answer from that context.

Every suggestion records the document ID, revision and range it was based on. When accepting one, the client adjusts for subsequent edits and checks that the expected original text still matches. If someone has rewritten that passage, it asks for a fresh suggestion.

The model is pretrained. Domain-specific behavior comes from collaborative-note prompts and the current document context. We did not train a new language model. The Transformers backend runs local inference inside the Python Assist process, which exposes gRPC. The alternative Ollama adapter uses HTTP to its inference runtime, so be precise about which deployment is being demonstrated.

The current launcher supports the larger Qwen2.5-1.5B-Instruct model with bfloat16 CPU inference. A real rehearsal produced contextual rewrites and document-based answers. Grammar combines model suggestions with explicit checks for errors such as “we has” and lowercase “i”.

The small 0.5B model tested earlier produced an invented date in autocomplete and changed part of a summary's meaning. A successful RPC does not establish that its answer is correct. People review its suggestions. Consensus guarantees agreement on accepted operations, including an accepted AI suggestion. It cannot guarantee factual correctness of the words.

## 15. Code map for reading the project

| Path relative to project root | Read it to understand |
|---|---|
| run.py | How each Python program starts |
| proto/collab/v1/*.proto | Remote service contracts and messages |
| scripts/gen_proto.py | Generating protobuf Python code |
| scripts/cluster.py | Launching voters, AI and gateway and inspecting status |
| clients/collab_client/desktop.py | GUI bridge, autosave diffs, history and AI acceptance |
| clients/collab_client/ui/ | The actual screen layout, styles and controls |
| clients/collab_client/client.py | Login, edit retries and live document copies |
| clients/collab_client/textops.py | Position mapping, applying changes and rebasing |
| services/gateway/src/gateway/auth.py | Password verification and token lifetime |
| gateway/service.py | User-facing RPCs, author identity and AI routing |
| gateway/docs.py | Leader discovery, bounded retries and resumed subscriptions |
| gateway/presence.py | Rooms, online participants and cursors |
| services/docnode/src/docnode/raft.py | Raft election, replication, durability and replay |
| docnode/statemachine.py | Deterministic editing rules, versions and duplicate tracking |
| docnode/oplog.py | The Log interface and the baseline LocalLog |
| docnode/server.py | Document gRPC methods and read barriers |
| docnode/subscribe.py | Bounded subscriber queues and delivery |
| docnode/convert.py | Converting protobuf messages to internal editing types |
| services/assist/src/assist/tasks/ | Prompts and logic for each writing tool |
| assist/anchoring.py | Locating the original text for a suggestion |
| assist/schemas.py | Validating structured model output |
| assist/providers/ | Fake, external-runtime and local CPU inference adapters |
| scripts/verify_cluster.py | Actual process-kill and disk-restart checks |
| services/*/tests, clients/tests, tests | Unit, integration and client tests |
| deploy/ | Container topology and deployment instructions |

Generated stubs are infrastructure. For the viva, spend your time on the authored Raft implementation, state machine, gateway routing and client conflict rules.

## 16. Tests and what they establish

Unit tests check small rules such as text range validation, emoji boundaries, stale revisions, duplicates, persisted voting and log freshness. Integration tests run actual gRPC services and clients together. The partition test blocks communication with the old leader while the other two elect and commit, then heals the connection and checks repair.

The process verification script starts independent Python processes on free ports and independent temporary disks. It kills the elected leader during an eight-client workload, checks all 200 edits, tests a duplicate retry, restarts the failed voter, compares replicas, restarts all voter processes on the same disks and then tests majority loss.

The baseline comparison is valuable evidence. It shows why durable replication was needed and what the new checks add. Test results are evidence for the scenarios run. They do not establish that every possible distributed execution has been formally proven safe.

The GUI tests additionally check login rejection, two authenticated editors working together, document creation/history, logout, draft merging and rejection of a stale AI suggestion. The running desktop has also been inspected interactively.

## 17. A viva rehearsal you can perform

First start the cluster and desktop using START-HERE. Sign in as Alice, create a document, type one sentence and wait for “All changes saved.” Open another client as Bob and select the same document. Explain why both clients need the same document ID.

Type in each window and show both copies. Open history and identify authors. Open System status and identify the current leader. The leader can be any replica, so read its actual role before stopping a process.

Kill the elected voter process using the launcher PID. Keep the gateway and clients running. Explain that the two surviving voters form a majority. Show a new leader and a higher term. Type again and wait for an acknowledged save. Restart the failed voter with its original address and data directory, then show it catching up.

Run the process verification script for the repeatable 200-edit and full-disk-restart evidence. Show a real writing suggestion and explain that accepting it creates a normal replicated edit. Finish by describing the measured deployment and the actual limitations.

Do not stop processes you cannot identify as belonging to the demo. Do not delete data directories when demonstrating recovery. Restart means reopening the same durable state.

## 18. Questions to practise answering aloud

**Why Raft?** We need one agreed order of edits across replicas and automatic leader replacement. Raft provides election, replication and safety rules that we implement directly.

**Why three voters?** Two form a majority and one may fail while progress continues. With two voters, losing one loses the majority.

**Why gRPC?** It gives explicit typed contracts, Python code generation and streams for live edits and AI responses. The assignment also requires it.

**Does a follower accept a client write?** In cluster mode it rejects leadership responsibility and can return a leader address. The gateway discovers and contacts the current leader.

**Why persist votes?** Otherwise a restarted voter could forget an earlier vote and vote twice in the same term.

**What if the candidate's log is longer but old?** Compare the last term first, then the index. Length alone is insufficient.

**What if the leader fails after recording an entry on only its own disk?** That entry is uncommitted. It may be overwritten. The client must not have received a successful committed result for it.

**What if the reply is lost after commitment?** The outcome is uncertain to the client. Retry the same operation ID. The state machine suppresses duplicate application.

**What if two users change the same version?** The first valid edit advances the revision. The later stale edit fetches history, rebases its positions and retries.

**Is this a CRDT?** The implementation uses leader-ordered commands, revision checks and client-side rebasing. It does not implement a CRDT data type.

**Why are log indices and document versions different?** The global log includes internal no-ops and rejected commands and can contain edits for multiple documents. A document revision counts its accepted operations.

**Why can we replay the state machine?** Its rules are deterministic and the committed command order is persisted. Replaying that prefix reconstructs documents and history.

**Why not read from any follower?** A follower may lag. Our authoritative read uses a leader quorum barrier. Diagnostics can show local follower state so we can observe catch-up.

**What happens to an old leader in a partition?** It cannot complete a majority operation, loses quorum contact and steps down. The majority can elect a replacement. Conflicting uncommitted suffixes are repaired on reunion.

**Does AI participate in consensus?** It generates suggestions outside the consensus path. An accepted suggestion becomes an ordinary command. The generated response is not independently regenerated on every voter.

**Is the LLM domain trained?** We use a pretrained local model with collaborative-note prompts and supplied document context. We did not fine-tune model weights.

**What are the main limitations?** Fixed membership, full-log growth/replay, a single gateway with memory-only sessions, trusted internal RPCs and model-output inaccuracies. The process demo shares one physical host.

**How would you improve it after the deadline?** Add snapshots and log compaction, secure internal channels for a real network, gateway redundancy with a deliberate session design, stronger authorization, larger evaluation workloads and a more accurate CPU model. Each needs its own tests.

**Which parts did you personally implement?** Give your actual work and evidence. Read the code and reproduce the tests. Record AI assistance honestly. Do not claim personal authorship or understanding that you cannot demonstrate.

## 19. Before the presentation

Be able to explain one edit from keystroke to disk and back to another client. Be able to explain the difference between stored, committed and applied. Practise identifying the actual leader and recovering a node on its original disk. Read your project's current results file so the numbers you quote match the tested release.

The paper reference is Ongaro and Ousterhout, *In Search of an Understandable Consensus Algorithm*, extended version. Figure 2 summarizes the core algorithm. Sections 5.2–5.4 explain elections, replication and safety. Section 8 discusses client interaction and safe reads. Use the supplied paper alongside the code as you study.
