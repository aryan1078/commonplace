# Collab Platform: a shared document editor with an AI assistant

Course project for **Advanced Operating Systems (CS G623)**, option C:
*Distributed Real-time Collaboration Platform*.

---

## 1. What is this project?

Think of a very small **Google Docs** that runs in the terminal:

* Several people log in and open **the same document at the same time**.
* When one person types, **everyone else sees the change immediately**.
* If two people change the document **at the exact same moment**, nothing is
  lost and nobody's copy gets out of sync.
* You can see **who else is in the document**, where their cursor is, and
  whether they are typing right now.
* A built-in **AI assistant** can fix grammar, finish your sentence, rewrite
  a sentence, summarize the document, and answer questions about it.
* Every change is kept, so you can see the **full history** of a document.

The AI runs **on your own computer** (no internet or API key needed), using a
small model called **Qwen 2.5** through a free program called **Ollama**.

---

## 2. How it works, in plain words

The system is split into four programs. Each one could run on a different
computer; they talk to each other over the network using **gRPC** (a standard
way for programs to call each other's functions over a network).

```
   You (the client)
        │  log in, type, read, ask the AI
        ▼
   ┌──────────┐   documents   ┌──────────┐
   │ gateway  │──────────────▶│ docnode  │   stores every document and its history,
   │          │               └──────────┘   decides which edits are accepted
   │          │   AI requests ┌──────────┐
   │          │──────────────▶│  assist  │──▶ Ollama (the AI model)
   └──────────┘               └──────────┘
```

| Program | What it does | Like... |
|---|---|---|
| **client** | The program you use. Type commands, see the document. | The app on your phone |
| **gateway** | The front door. Checks your password, passes your edits on, tells everyone about changes, keeps track of who is online. | A receptionist |
| **docnode** | Keeps the documents. Decides whether each edit is allowed and stores the history. | A filing clerk |
| **assist** | The AI helper. Only *suggests* changes; it never edits a document itself. | An advisor |

These map onto the demo setup the assignment asks for: node 1 is the AI
server (assist + Ollama), the application servers are gateway + docnode, and
node 5 is the clients.

### What happens when two people edit at the same time?

Every document has a **revision number**. A new document is at revision 0, and
every accepted change adds 1.

1. Alice and Bob both see revision 5.
2. Alice sends her change first. It is accepted, so the document is now at revision 6.
3. Bob's change was made on revision 5, which is now out of date, so the server
   says **"stale"** and changes nothing.
4. Bob's client automatically fetches Alice's change, shifts Bob's change to
   the right place, and sends it again. It is accepted as revision 7.

Both changes survive, and everyone ends up with exactly the same text. Each
change also carries a unique ID, so if a message is sent twice (for example
after a network hiccup) it is still applied only once.

### How does logging in work?

* Users and passwords are in `config/users.json`. Passwords are **never stored
  as plain text**, only as secure hashes.
* After logging in you get a **token** (like a temporary pass). Every request
  must show it. It expires after 8 hours.
* **Logging out** cancels the token immediately and disconnects you.

Ready-made demo users:

| Username | Password |
|---|---|
| alice | alice123 |
| bob | bob123 |
| carol | carol123 |

---

## 3. What you need

* **Windows 10/11** (Linux and macOS work too; see the notes below).
* **Python 3.11 or newer**. Check with `python --version`.
* **Ollama**, for the real AI. Optional: everything also works with a
  built-in *fake* AI that gives fixed answers.
* About **3 GB of free disk space** for the AI models.
* **Docker Desktop**, only if you want to run it with Docker (optional).

---

## 4. Setup (one time only)

Open **PowerShell** and go to the project folder (the one containing this README):

```powershell
cd C:\path\to\collab-platform-main
```

**Step 1: Create a private Python environment** (keeps this project's
packages separate from the rest of your computer):

```powershell
python -m venv .venv
.venv\Scripts\activate
```

You should now see `(.venv)` at the start of the prompt. **Do this
`activate` step again every time you open a new terminal.**

> If PowerShell says "running scripts is disabled", run this once and try again:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Step 2: Install the packages:**

```powershell
python -m pip install -r requirements.txt
```

**Step 3: Generate the network code** from the API definitions in `proto/`:

```powershell
python scripts/gen_proto.py
```

Expected output: `generated code for 6 proto files in gen\python`

**Step 4: Install the AI model** (skip this if you only want the fake AI):

1. Download and install Ollama from <https://ollama.com/download>. It keeps
   running in the background after installation.
2. Download the two models (about 3 GB in total, takes a few minutes):

   ```powershell
   ollama pull qwen2.5:3b
   ollama pull qwen2.5:1.5b
   ```

   (`qwen2.5:3b` does most of the work; the smaller `qwen2.5:1.5b` is used for
   autocomplete, where speed matters most.)

Setup is done.

---

## 5. Running it

You need **two terminals**: one runs the servers, the other runs the client.
Activate the environment (`.venv\Scripts\activate`) in both.

### Terminal 1: start the servers

```powershell
python scripts/start_local.py
```

Or, without the real AI (fixed answers, no Ollama needed, starts instantly):

```powershell
python scripts/start_local.py --fake-llm
```

You should see:

```
  docnode  listening on :50051  (log: logs/docnode.log)
  assist   listening on :50061  (log: logs/assist.log)
  gateway  listening on :50070  (log: logs/gateway.log)

All services up. ...
Press Ctrl+C to stop.
```

Leave this window open. Press **Ctrl+C** in it to stop everything.

### Terminal 2: use the client

There are three ways to use the client.

#### a) The demo: watch every feature in about a minute

```powershell
python run.py client demo
```

This plays a scripted story with three users (alice, bob and carol) and prints
what happens at each step:

1. A wrong password is rejected; then the three users log in.
2. All three open the same document and see each other online.
3. Alice types meeting notes; Bob and Carol receive them instantly.
4. Bob moves his cursor; Alice sees where it is.
5. **Alice and Bob edit at the same moment.** One edit is rejected as stale,
   fixed automatically and resent. Both edits survive and all copies match.
6. The document's history is shown (who changed what).
7. The AI checks the grammar and one suggestion is accepted.
8. The AI rewrites a sentence more concisely.
9. The AI summarizes the notes.
10. The AI suggests how to continue the text.
11. Questions are asked about the document. One is answered; for the other the
    AI correctly says "The document does not say."
12. Bob logs out: his connection is closed and his old token no longer works.

It ends with `alice, carol and the server agree: True`.

#### b) The interactive shell: use it yourself

```powershell
python run.py client shell --user alice --doc notes
```

It asks for the password (`alice123`), then shows an `alice>` prompt. Example
session:

```
alice> append Meeting on Friday. i will bring the slides.
  ok -> revision 1
alice> show
--- notes @ revision 1 ---
Meeting on Friday. i will bring the slides.
---
alice> grammar
  1. 'i' -> 'I'  Capitalization of pronoun
alice> accept 1
  applied -> revision 2
alice> ask When is the meeting?
  The meeting is on Friday.
alice> logout
```

**Try it with two people:** open a third terminal and run
`python run.py client shell --user bob --doc notes` (password `bob123`).
When Alice edits, Bob's window shows `* alice edited -> revision ...`. Type
`show` to see the new text and `who` to see who is online.

All shell commands:

| Command | What it does |
|---|---|
| `open <doc>` | Open a document (it is created if it does not exist) |
| `show` | Print the document and its revision number |
| `append <text>` | Add text at the end (`\n` starts a new line) |
| `insert <pos> <text>` | Insert text at a position (0 = the very beginning) |
| `delete <start> <end>` | Delete the characters from `start` up to (not including) `end` |
| `cursor <pos> [<end>]` | Move your cursor, or select a range; others see it with `who` |
| `history [n]` | The last *n* changes and who made them |
| `who` | Who is in the document, their cursor, and whether they are typing |
| `docs` | List all documents |
| `grammar` | AI: find grammar and spelling mistakes |
| `enhance <start> <end> [concise\|formal\|clarify\|expand]` | AI: rewrite part of the text |
| `accept <n>` | Apply suggestion number *n* from the last `grammar` or `enhance` |
| `summarize [short\|medium\|detailed]` | AI: summarize the document |
| `complete` | AI: suggest how to continue the text |
| `ask <question>` | AI: answer a question using only the document |
| `help` | Show the commands |
| `logout` / `quit` | Leave |

Positions count characters from 0. For example, in `Hello world`, `delete 0 6`
removes `Hello ` (including the space).

#### c) The stress test: many users at once

```powershell
python run.py client simulate --users 8 --edits 25
```

8 simulated users each make 25 random edits **to the same document at the
same time**, so their edits constantly collide. Afterwards it checks three things:

* the document has exactly 8 × 25 = 200 changes (nothing lost, nothing doubled);
* replaying the history from an empty document gives exactly the final text;
* all 8 users ended with exactly the same text.

It prints `CONSISTENT` if all three hold, otherwise `INCONSISTENT`.

---

## 6. Running with Docker (optional)

Docker runs each program in its own container, like separate machines. Start
Docker Desktop first.

```powershell
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml run --rm client demo
docker compose -f deploy/docker-compose.yml run --rm client simulate --users 8 --edits 25
docker compose -f deploy/docker-compose.yml run --rm client shell --user alice --doc notes
docker compose -f deploy/docker-compose.yml down
```

The first command builds and starts the servers in the background, the next
three run the client, and the last one stops everything.

By default the containers use **the Ollama installed on your computer**, so do
setup step 4 first. Other options:

* No AI model at all: run `$env:ASSIST_PROVIDER = "fake"` before the first command.
* Ollama inside Docker too (downloads the models again, about 3 GB):

  ```powershell
  $env:ASSIST_BASE_URL = "http://ollama:11434/v1"
  docker compose -f deploy/docker-compose.yml --profile ollama up -d --build
  ```

---

## 7. Running on separate computers

Each program can be started on its own. Replace `HOST` with the IP address of
the machine running that program:

```powershell
python run.py docnode --port 50051                                         # application server
python run.py assist                                                       # AI server (needs Ollama)
python run.py gateway --docnodes HOST:50051 --assist HOST:50061            # application server
python run.py client --gateway HOST:50070 demo                             # client machine
```

To point the AI server at Ollama on another machine, or to change the models
or time limits, copy `.env.example` to `.env` and edit it. Every setting is
explained inside that file.

---

## 8. Managing users

```powershell
python scripts/manage_users.py list            # show all users
python scripts/manage_users.py add dave        # add a user (asks for a password)
python scripts/manage_users.py remove dave     # remove a user
```

Restart the servers afterwards so the gateway reads the new list.

---

## 9. Running the tests

```powershell
python -m pytest
```

This runs 139 automatic checks in about 20 seconds and ends with
`139 passed`. They do not need Ollama: they start the whole system inside the
test with the fake AI. They cover the editing rules, the
"two copies stay identical" guarantee, logins and logout, presence, every AI
feature (including problems found with the real model), the client, the demo,
the shell and the stress test.

---

## 10. What is in each folder

```
collab-platform-main/
├── README.md               this file
├── run.py                  starts any program: python run.py docnode|assist|gateway|client
├── requirements.txt        the Python packages needed
├── .env.example            optional settings (copy to .env to change them)
├── Dockerfile              how to build the Docker image
├── deploy/
│   └── docker-compose.yml  runs everything with Docker
├── docs/
│   └── design.md           detailed technical design (for the report and viva)
├── proto/collab/v1/        the API: what each program offers the others
│   ├── gateway.proto         what clients can call: Login, Logout, Post, Get, Join, Assist
│   ├── document.proto        the document service
│   ├── assist.proto          the AI service
│   ├── presence.proto        who is online, cursors
│   ├── common.proto          shared building blocks (an edit, a text range, ...)
│   └── raft.proto            reserved for Milestone 2 (Raft)
├── services/
│   ├── docnode/            the document service (the editing rules live in statemachine.py)
│   ├── gateway/            the front door (auth.py, presence.py, service.py)
│   └── assist/             the AI service (one file per feature in tasks/)
├── clients/collab_client/  the client: library (client.py), shell, demo, simulate
├── config/users.json       demo users (password hashes only)
├── scripts/
│   ├── gen_proto.py        generates the network code into gen/
│   ├── start_local.py      starts all servers on this computer
│   └── manage_users.py     adds and removes users
└── tests/                  tests that run the whole system together
```

These folders are created on your computer and are not part of the project:
`.venv/` (installed packages), `gen/` (generated code, recreate it with
`python scripts/gen_proto.py`) and `logs/` (one log file per server).

---

## 11. Assignment requirements: where to find them

| Requirement | Where |
|---|---|
| Python only, gRPC for all communication | Every program; API in `proto/` |
| `login`, `logout`, `post`, `get` | `CollabService` in `proto/collab/v1/gateway.proto` |
| `getLLMAnswer(requestId, query, context)` | `AssistService.GetLLMAnswer` in `assist.proto` (shell: `ask`) |
| Simultaneous editing with conflict resolution | `services/docnode/.../statemachine.py`, `clients/.../client.py` (`edit`) |
| Real-time updates to all users | The `Join` stream (shell: edits appear live) |
| Presence (who is online or editing) | `services/gateway/.../presence.py` (shell: `who`) |
| AI: grammar and suggestions, summarization, enhancement | `services/assist/.../tasks/` |
| Local, CPU-friendly AI on its own server | `assist` + Ollama with Qwen 2.5 |
| Version history | `GetHistory` (shell: `history`) |
| Raft consensus, fault tolerance (Milestone 2) | **Not done yet.** It will plug into `services/docnode/.../oplog.py` |

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `Generated code is missing` | Run `python scripts/gen_proto.py` |
| `ModuleNotFoundError: No module named 'grpc'` | The environment is not active: run `.venv\Scripts\activate` |
| `ports already in use` when starting | The servers are already running somewhere. Run `python scripts/start_local.py --stop`, then start again |
| AI features say `UNAVAILABLE` or `not reachable` | Ollama is not running or the models are missing. Run `ollama list`; it should show `qwen2.5:3b` and `qwen2.5:1.5b`. Or use `--fake-llm` |
| `ollama` is "not recognized" | Close and reopen the terminal after installing Ollama, or run it by its full path: `& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list` |
| The AI is slow | Normal on a laptop CPU: 2 to 20 seconds per request |
| An AI suggestion is wrong | Small local models make mistakes. Suggestions are only applied if you `accept` them |
| Login fails for a new user | Restart the servers after `manage_users.py` |
| Something else | Look in `logs/gateway.log`, `logs/docnode.log` or `logs/assist.log` |

**Linux / macOS:** the commands are the same, except: activate with
`source .venv/bin/activate`, and you may need `python3` instead of `python`.

---

## 13. Words used in this project

| Word | Meaning |
|---|---|
| **gRPC** | A standard way for programs to call each other's functions over a network |
| **Revision** | The version number of a document; every accepted change adds 1 |
| **Stale edit** | A change made on an old revision; the client adjusts it and sends it again |
| **Token** | A temporary pass you get when logging in; shown with every request |
| **Presence** | Who is in a document, where their cursor is, and whether they are typing |
| **LLM** | Large Language Model: the AI that reads and writes text |
| **Ollama** | A free program that runs AI models on your own computer |
| **Raft** | A method for keeping copies of data identical on several servers, so the system keeps working if one crashes (Milestone 2) |
