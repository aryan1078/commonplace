# Distributed collaborative editor

Advanced Operating Systems CS G623, Project C, November 18, 2026.

## Graphical interface

Double-click **Start Commonplace.cmd** on Windows with Python 3.11 installed. The first launch creates a virtual environment and installs the client dependencies. It starts the local services and opens a graphical sign-in window. Sign in as alice/alice123 or bob/bob123 for the classroom demo. Create a document, open it in a second window and type. The interface has autosave, online participants, version history, writing tools and authenticated replica status. **Stop demo.cmd** stops launcher-owned services while preserving the disks.

Without model files, the assistant explicitly labels its responses as demo output. Run **Set up real AI.cmd** to install the local Transformers backend and download Qwen2.5-1.5B-Instruct. Stop and restart the demo afterward. The launcher selects bfloat16 CPU inference for this model. A smaller 0.5B model and the earlier quantized backend remain available. Grammar combines explicit common-error checks with contextual model suggestions. Users review all suggested changes.

For a remote gateway run `python scripts/launch_desktop.py --client-only --gateway HOST:50070`. The login form also has server-address and TLS controls. The native client speaks gRPC over the network. See deploy/DEPLOYMENT.md for LAN deployment and the optional free public tunnel.

The detailed viva guide is supplied alongside the code and explains the interface, every service, one edit's full journey, conflict resolution, Raft, persistence, model limitations and exam questions.

Python terminal editor with live collaboration, presence, version history and a separate AI service. Three independent document voters implement Raft over gRPC with durable SQLite logs. The gateway discovers the leader and resumes committed subscriptions after failover.

## Windows setup

Use Python 3.11 from the project directory.

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
python scripts/gen_proto.py
python -m pytest
python scripts/verify_cluster.py
python scripts/cluster.py start --fake-llm
```

The verification script starts an independent cluster on free ports and temporary disks. It kills the elected leader during concurrent edits, retries duplicate IDs, catches up a returning voter, restarts all disks and checks majority loss. It cleans up its owned processes.

In a second activated terminal:

```powershell
python run.py client demo
python run.py client simulate --users 8 --edits 25 --seed 42
python run.py client shell --user alice --doc notes
python scripts/cluster.py status --doc notes
```

Demo users alice, bob and carol have passwords alice123, bob123 and carol123. Shell commands include show, insert, delete, cursor, history, who, docs, grammar, accept, complete, summarize, enhance, ask and logout. Use help for arguments. Positions count UTF-16 code units.

## Real CPU model

Transformers runs inference inside the separate Python Assist process. Its remote interface is gRPC. Download the official model before recording.

```powershell
python -m pip install -r requirements-transformers.txt
python scripts/download_model.py
$env:ASSIST_PROVIDER = "transformers"
$env:ASSIST_MODEL_PATH = (Resolve-Path models/qwen-transformers).Path
$env:ASSIST_THREADS = "4"
python scripts/cluster.py start
```

Qwen2.5-0.5B-Instruct uses CPU with approximately 2 GB float32 weights plus inference memory. Task prompts adapt it to collaborative notes. Users review suggestions and acceptance follows the regular replicated edit path. Responses are generated completely before returning through the Assist stream.

An optional quantized backend uses requirements-ai.txt and `python scripts/download_model.py --gguf`. Set ASSIST_PROVIDER=llama_cpp and ASSIST_MODEL_PATH to models/qwen.gguf. The Windows wheel download failed during rehearsal. Follow https://llama-cpp-python.readthedocs.io/en/latest/ for CPU wheels. The older Ollama option uses HTTP to its inference runtime.

## Failure demonstration

Run status to find the elected leader. The launcher prints each PID. Kill that voter with `Stop-Process -Id <PID> -Force`, leaving the gateway, clients and other voters alive. Show the replacement leader, higher term and another edit from the existing shell. Logs are under logs/node1.log through node3.log.

Restart the failed node with its original address and data directory. For node 1:

```powershell
python run.py docnode --port 50051 --address localhost:50051 --peers localhost:50051,localhost:50052,localhost:50053 --data-dir data/node1
```

Node 2 uses 50052 and data/node2. Node 3 uses 50053 and data/node3. Compare diagnostic digests after catch-up. Ctrl+C stops launcher-owned processes. Stop a separately restarted voter yourself. Reusing the disks preserves history. Run one voter per data directory with the same fixed membership addresses.

Two voters are needed for writes and authoritative reads. A timeout leaves the outcome uncertain. Clients retry the same operation ID. Diagnostics expose local state for replica comparison and are not authoritative reads.

## Five logical nodes and Docker

Node 1 runs Assist and local inference. Nodes 2–4 run one voter each. Node 5 runs gateway and clients. The measured deployment uses independent processes on one host. For separate machines replace localhost with reachable IP addresses and configure the ports. Each voter takes its own --address, identical --peers and independent --data-dir. Run gateway with `--docnodes HOST2:50051,HOST3:50051,HOST4:50051 --assist HOST1:50061`. Clients use `--gateway HOST5:50070`.

Compose defines independent durable volumes and defaults to llama_cpp with models/qwen.gguf mounted. Docker was unavailable here and needs a build rehearsal. Set ASSIST_PROVIDER=fake for an infrastructure-only run.

```powershell
docker compose -f deploy/docker-compose.yml up --build
docker compose -f deploy/docker-compose.yml run --rm client demo
docker compose -f deploy/docker-compose.yml kill node1
docker compose -f deploy/docker-compose.yml up -d node1
docker compose -f deploy/docker-compose.yml down
```

Retain the volumes for recovery.

## Code and design

proto/collab/v1 contains all remote contracts. docnode/raft.py implements elections, durable append, majority commit and replay. statemachine.py contains deterministic editing and duplicate suppression. gateway/docs.py routes calls and resumes streams. assist/providers contains CPU and external adapters. clients/collab_client provides the shell and workloads. scripts/verify_cluster.py exercises actual process failures.

SQLite WAL with synchronous FULL persists term, vote, commit boundary and entries before acknowledgments. Startup replays the committed prefix, reconstructing history and deduplication. Elections use randomized 0.8–1.4 second timeouts. Heartbeats run every 0.1 seconds with bounded peer deadlines. Log freshness uses term then index. Higher terms cause step-down. Per-peer next/match indices repair conflicting uncommitted suffixes. Majority commitment advances only through a current-term entry. No-ops on election and authoritative reads establish quorum barriers. Stale or invalid commands consume log entries without visible document revisions. Network waits occur outside state mutations on the asyncio loop.

Membership is fixed at three. History and logs grow without compaction or snapshot transfer. Gateway sessions live in memory and a gateway restart requires login again. The tested failover covers document voters. Transport is insecure gRPC for a controlled demo network, with authentication at the gateway and trusted internal RPCs.

## References and provenance

This extends the supplied team Python baseline. Raft follows Ongaro and Ousterhout, In Search of an Understandable Consensus Algorithm (Extended Version), Figure 2 and sections 5 and 8, https://raft.github.io/raft.pdf . Model sources are https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct and https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF (Apache 2.0). Retain upstream licenses. Document AI assistance and actual member contributions according to course rules.
