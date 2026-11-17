# Five-host LAN rehearsal (prepared, not yet executed)

This deployment plan checks the assignment's 4–5-node design on separate machines. Existing measured results use independent processes on one laptop. These instructions do not claim that a real five-machine rehearsal has happened.

Use five machines on the same trusted LAN with Python 3.11. Replace the example IPs consistently with their actual LAN addresses:

| Machine | Example IP | Role |
|---|---|---|
| 1 | 192.168.1.10 | Assist and CPU model |
| 2 | 192.168.1.11 | Document voter 1 |
| 3 | 192.168.1.12 | Document voter 2 |
| 4 | 192.168.1.13 | Document voter 3 |
| 5 | 192.168.1.14 | Gateway, browser edge and client windows |

Clone/unzip the current source on each host. In the project folder, create a virtual environment, install core requirements and generate protobuf code:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/gen_proto.py
```

Machine 1 also runs **Set up real AI.cmd** to install the CPU-model runtime and download weights. Machine 5 additionally installs `requirements-web.txt`.

Start a fresh LAN deployment with the new data directories below. The current laptop databases record their original voter identity/configuration, so they must not be silently reassigned to new IP addresses. After the LAN cluster is created, preserve its addresses and its data directories through the crash/recovery demonstration.

## Machine 1: AI service

```powershell
$env:ASSIST_PROVIDER='transformers'
$env:ASSIST_MODEL_PATH=(Resolve-Path .\models\qwen-1.5b).Path
$env:ASSIST_DTYPE='bfloat16'
$env:ASSIST_THREADS='4'
.\.venv\Scripts\python.exe run.py assist
```

## Machine 2: first voter

```powershell
.\.venv\Scripts\python.exe run.py docnode --host 0.0.0.0 --port 50051 --address 192.168.1.11:50051 --peers 192.168.1.11:50051,192.168.1.12:50051,192.168.1.13:50051 --data-dir data/lan-node1
```

## Machine 3: second voter

```powershell
.\.venv\Scripts\python.exe run.py docnode --host 0.0.0.0 --port 50051 --address 192.168.1.12:50051 --peers 192.168.1.11:50051,192.168.1.12:50051,192.168.1.13:50051 --data-dir data/lan-node2
```

## Machine 4: third voter

```powershell
.\.venv\Scripts\python.exe run.py docnode --host 0.0.0.0 --port 50051 --address 192.168.1.13:50051 --peers 192.168.1.11:50051,192.168.1.12:50051,192.168.1.13:50051 --data-dir data/lan-node3
```

## Machine 5: gateway and browser edge

In one terminal:

```powershell
$env:GATEWAY_AI_MODE='Local CPU language model'
.\.venv\Scripts\python.exe run.py gateway --host 0.0.0.0 --port 50070 --docnodes 192.168.1.11:50051,192.168.1.12:50051,192.168.1.13:50051 --assist 192.168.1.10:50061
```

In another terminal:

```powershell
.\.venv\Scripts\python.exe run.py web --host 0.0.0.0 --port 8080 --gateway localhost:50070
```

Browsers on the trusted LAN open `http://192.168.1.14:8080`. The two demo accounts remain independent browser sessions. The Python-only client can instead connect with:

```powershell
.\.venv\Scripts\python.exe run.py client --gateway 192.168.1.14:50070 shell --user alice --doc lan-demo
```

Allow required TCP traffic on the selected private LAN: 50051 on voter hosts, 50061 on the AI host, and 8080 on the browser host. Port 50070 is needed for native clients connecting from another host. The core local prototype trusts internal service traffic; keep those ports on the controlled LAN.

## What to verify and record

1. Confirm a single leader and three reachable voters. From the project folder on machine 5:

```powershell
.\.venv\Scripts\python.exe scripts/cluster.py status --peers 192.168.1.11:50051,192.168.1.12:50051,192.168.1.13:50051 --doc lan-demo
```

2. Sign in as Alice and Bob, create/open `lan-demo`, save edits and verify presence/history.
3. Verify a real AI summary/rewrite from the separate AI host.
4. Stop the elected voter's own foreground terminal with Ctrl+C. Keep the other hosts running. The recording helper intentionally controls only localhost voters; do not use it to guess remote process IDs.
5. Show a replacement leader in a higher term, save a new edit and show it in the other client.
6. Restart the stopped voter with exactly the same command and original `data/lan-nodeN` directory. Compare document revision and digest after catch-up.
7. Save the actual commands, addresses, output and footage. Distinguish a stopped service from a failed physical host in the explanation.

If separate machines are unavailable, retain the honest one-host process demo. This guide establishes a concrete configured deployment plan; successful remote operation remains a rehearsal item until it is actually run.
