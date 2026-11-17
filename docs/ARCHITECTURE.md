# Architecture

Commonplace has a browser editor, a Python gRPC-Web edge, an authenticated gateway, three voting document replicas and a separate writing-assistance service. An optional desktop window shares the same interface. Remote application calls use gRPC or gRPC-Web.

## Browser path

The browser sends unary binary gRPC-Web requests to BrowserService.Call, defined in browser.proto. Its small protobuf envelope carries an allowlisted UI action and JSON arguments. The Python edge owns a separate DesktopSession for each random browser session key. It calls the existing typed gateway gRPC client, which maintains live document subscriptions. The browser polls its session every 900 ms; internal subscriptions remain streaming gRPC. The browser is not a Raft voter.

Gateway passwords are verified by the existing authentication service. Gateway tokens stay in Python memory; each tab holds only a random edge key in JavaScript memory. The edge caps sessions, expires idle sessions, limits request size, restricts cross-origin requests and fixes the internal gateway address. It never exposes an arbitrary proxy destination. This is a shared classroom workspace, with public demo accounts and no per-document permissions.

GitHub Pages hosts the static editor assets. A temporary localhost.run HTTPS tunnel reaches the Python edge on the host laptop. Three durable replica databases and model inference stay on that host. The same edge can serve the UI itself, so its direct HTTPS URL also works. A Sonora unary-response compatibility override emits standard gRPC-Web trailers; the browser integration tests verify the wire framing.

## The five logical nodes

| Node | Runs | Owns |
|---|---|---|
| 1 | Assist and local inference | Model weights and request context |
| 2–4 | One document voter each | Independent SQLite log and election state |
| 5 | Gateway, browser edge and client interface | Login sessions, presence and live document views |

The process demo places these on one host. Running voters on separate hosts changes their configured addresses and failure domains.

## Write path

The client sends text changes with a document ID, base revision and operation ID. The gateway checks the token and supplies the authenticated author. Its document client finds the current leader and follows leadership hints after a failure.

The leader persists an entry and replicates through AppendEntries. Followers validate the preceding index and term before acknowledging a durable append. The leader advances commitment through a current-term entry replicated to a majority, then applies the committed prefix to the deterministic state machine. The client receives success after application.

Rejected stale commands do not change document text. Clients fetch the intervening history, rebase positions and retry. Repeated operation IDs are suppressed. Log replay rebuilds text, history and duplicate counters together.

## Election and recovery

Followers use randomized election deadlines and persist their term and vote before replying. A candidate needs a majority and a sufficiently up-to-date log. Higher terms cause step-down. A leader also steps down after losing recent majority contact.

Each follower has its own nextIndex and matchIndex at the leader. Missing entries are resent and conflicting uncommitted suffixes are repaired. Startup replays the locally persisted committed prefix. A new leader appends a no-op to establish commitment in its term.

Authoritative reads commit a no-op barrier before returning state. Status diagnostics deliberately report each replica's local progress so lag and recovery are visible. Live subscriptions resume at the last delivered document revision after leader replacement.

## Login, presence and AI

The gateway verifies salted PBKDF2 password hashes, issues expiring tokens and revokes streams on logout. Presence and cursors describe gateway connections and are rebuilt on reconnect.

Assist loads a local CPU model and receives collaborative-note prompts and document context. Grammar supplements model output with explicit checks for common errors. Suggestions carry a revision and text anchor. A user accepts a suggestion through the ordinary replicated edit path. Inference runs outside consensus.

## Read the implementation

- `services/docnode/src/docnode/raft.py` — elections, durable replication and replay
- `services/docnode/src/docnode/statemachine.py` — document rules and duplicate tracking
- `services/gateway/src/gateway/docs.py` — leader discovery and subscription recovery
- `clients/collab_client/desktop.py` — graphical-client bridge and draft handling
- `clients/collab_client/textops.py` — position mapping and rebasing
- `clients/collab_client/browser.py` — gRPC-Web edge, isolated sessions and UI serving
- `clients/collab_client/ui/browser.js` — browser bridge and binary wire framing
- `proto/collab/v1/` — service contracts

The cluster has fixed membership and retains its entire log. Sessions live in the gateway's memory. The controlled local demo trusts internal RPCs; remote client connections support certificate-verified TLS. [Observed checks](results.md)
