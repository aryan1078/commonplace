# Collab Platform

A distributed real-time collaboration platform (AOS CS G623, project option C):
several users edit the same documents at once, see each other's edits and
cursors live, and get help from a local LLM (grammar, autocomplete,
enhancement, summaries, and questions about the document). Everything is
Python and every call between services is gRPC.

See [docs/design.md](docs/design.md) for the architecture, conflict rules,
authentication and LLM design.

| Service | What it does | Port |
|---|---|---|
| `docnode` | Stores documents and their version history; decides which edits are accepted | 50051 |
| `assist` | The LLM server: a local CPU model through Ollama | 50061 |
| `gateway` | What clients talk to: login, edits, reads, live updates, presence, LLM requests | 50070 |
| `client` | Command-line client: interactive shell, scripted demo, load simulation | – |

## Setup (Windows)

Needs Python 3.11 or newer.

```powershell
cd collab-platform-main
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts/gen_proto.py
```

On Linux/macOS activate with `source .venv/bin/activate`; everything else is the same.

`gen_proto.py` generates the gRPC code into `gen/python` (rerun it after
changing a `.proto` file). The tests also generate it if it is missing.

### The local LLM (Ollama)

1. Install Ollama from <https://ollama.com/download> (Windows installer; it
   runs in the background afterwards).
2. Download the two models (about 3 GB together):

   ```powershell
   ollama pull qwen2.5:3b
   ollama pull qwen2.5:1.5b
   ```

That is all: the Assist service uses `http://localhost:11434/v1` with these
models by default. To change anything (another machine, other models, a
longer timeout) copy `.env.example` to `.env` and edit it.

No model at hand? Use `--fake-llm` below: every feature still works, with
canned answers.

## Running

Start every service, each as its own process, with logs in `logs/`:

```powershell
python scripts/start_local.py              # with Ollama
python scripts/start_local.py --fake-llm   # without a model
```

Press Ctrl+C to stop them (or run `python scripts/start_local.py --stop` from
another terminal). Then, in a second terminal (with the venv activated):

```powershell
python run.py client demo
python run.py client simulate --users 8 --edits 25
python run.py client shell --user alice --doc notes
```

Each service can also be started by hand, for example on separate machines:

```powershell
python run.py docnode --port 50051
python run.py assist                       # settings from .env / environment
python run.py gateway --port 50070 --docnodes HOST:50051 --assist HOST:50061
python run.py client --gateway HOST:50070 shell
```

### Docker

```powershell
docker compose -f deploy/docker-compose.yml up --build
docker compose -f deploy/docker-compose.yml run --rm client demo
```

This starts Ollama (and downloads the models once into a volume), assist,
docnode and gateway; the client runs on demand. Set `ASSIST_PROVIDER=fake`
in the environment to skip the model.

## Using the client

Demo users: **alice / alice123**, **bob / bob123**, **carol / carol123**.
Manage users with:

```powershell
python scripts/manage_users.py list
python scripts/manage_users.py add dave
python scripts/manage_users.py remove dave
```

(restart the gateway afterwards).

**`demo`** walks through every feature with narration: a failed and three
successful logins, three users joining one document, live edits, cursors and
"editing" status, two users editing the same revision at the same moment
(one is rejected as stale, rebased and resent; both edits survive), version
history, every LLM feature, and a logout that closes that user's live stream.

**`simulate --users N --edits M`** runs N users making M random edits each
on one document at the same time, then checks that the final revision is
exactly N×M, that replaying the history reproduces the text, and that every
client's live copy is identical. It prints `CONSISTENT` or `INCONSISTENT`.

**`shell`** is an interactive session. Open two shells as different users on
the same document to see edits arrive live. Commands:

| Command | |
|---|---|
| `open <doc>` | open (join) a document |
| `show` | print the text and revision |
| `append <text>` / `insert <pos> <text>` / `delete <start> <end>` | edit (`\n` for a new line) |
| `cursor <pos> [<end>]` | move your cursor or select |
| `history [n]` | last n operations, with who made them |
| `who` / `docs` | people in the document / all documents |
| `grammar` | LLM grammar check of the document |
| `enhance <start> <end> [concise\|formal\|clarify\|expand]` | LLM rewrite of a range |
| `accept <n>` | apply suggestion n from the last `grammar`/`enhance` |
| `summarize [short\|medium\|detailed]` / `complete` | LLM summary / continuation |
| `ask <question>` | answer from the document only |
| `logout` / `quit` | |

Positions are character positions in the text as `show` prints it.

## Tests

```powershell
python -m pytest
```

Unit tests for the text rules, state machine (including the replica-agreement
test), subscriptions, presence, auth and every LLM task, plus end-to-end
tests that run docnode, assist (fake model) and gateway in-process and drive
them with the real client, demo, shell and simulation.

## Layout

```
proto/collab/v1/        gRPC API (common, document, assist, gateway, presence, raft)
services/docnode/       document service: text rules, state machine, log, server
services/assist/        LLM service: prompts, providers (ollama/openai_compat/fake)
services/gateway/       CollabService: auth, presence, routing
clients/collab_client/  client library and CLI
config/users.json       password hashes of the demo users
scripts/                gen_proto, start_local, manage_users
deploy/                 docker-compose.yml
docs/design.md          design notes
run.py                  starts any service from source
```
