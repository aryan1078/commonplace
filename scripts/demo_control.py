"""Readable Windows recording controls for the existing three-voter demo.

status is read-only. fail-leader deliberately stops exactly one verified local
docnode. recover runs that voter on its original disk until Ctrl+C.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen/python"))
from cluster import status
import grpc


def states(peers, doc):
    result = []
    for peer in peers:
        try:
            result.append(status(peer, doc))
        except grpc.RpcError:
            result.append({"node": peer, "role": "unreachable"})
    return result


def display(items, doc):
    print(f"\nDocument: {doc}")
    print(f"{'ADDRESS':<23} {'ROLE':<13} {'TERM':>5} {'COMMIT':>8} {'APPLIED':>8} {'VERSION':>8}  TEXT DIGEST")
    for item in items:
        print(f"{item['node']:<23} {item['role']:<13} {str(item.get('term', '-')):>5} "
              f"{str(item.get('commit_index', '-')):>8} {str(item.get('applied_index', '-')):>8} "
              f"{str(item.get('revision', '-')):>8}  {item.get('digest', '-')[:16]}")
    live = [item for item in items if item["role"] != "unreachable"]
    if len(live) == 3 and len({(item.get("revision"), item.get("digest")) for item in live}) == 1:
        print("All three replicas agree on the document version and text digest.")
    elif len(live) < 3:
        print(f"{len(live)} of 3 voters reachable. Two voters are needed for a majority.")
    else:
        print("Replicas are still catching up. Run status again.")


def powershell(command):
    if os.name != "nt":
        raise RuntimeError("Process control in this recording helper is for Windows.")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, encoding="utf8", errors="replace")
    if result.returncode:
        raise RuntimeError("Could not inspect/control the local voter. Keep the servers running under this Windows account.")
    return result.stdout.strip()


def local_voter(port):
    value = powershell(
        f"$connection=Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($connection) { $taskProcess=Get-CimInstance Win32_Process -Filter "
        "('ProcessId = '+$connection.OwningProcess); "
        "[pscustomobject]@{pid=$connection.OwningProcess;command=$taskProcess.CommandLine}|ConvertTo-Json -Compress }; exit 0")
    if not value:
        return None
    item = json.loads(value)
    command = (item.get("command") or "").replace("\\", "/")
    expected = str(ROOT / "run.py").replace("\\", "/")
    if expected.lower() not in command.lower() or not re.search(r"\bdocnode\b", command) or not re.search(rf"--port\s+{int(port)}\b", command):
        raise RuntimeError(f"Port {port} is occupied by a process outside this project's docnode. Nothing was stopped.")
    return item


def stop_voter(port):
    item = local_voter(port)
    if item:
        powershell(f"Stop-Process -Id {int(item['pid'])} -Force -ErrorAction Stop")
    return item


def fail_leader(args):
    before = states(args.peers, args.doc)
    display(before, args.doc)
    if any(item["role"] == "unreachable" for item in before):
        raise RuntimeError("Start with all three voters reachable before demonstrating a leader failure.")
    leaders = [item for item in before if item["role"] == "leader"]
    if len(leaders) != 1:
        raise RuntimeError("Wait for exactly one elected leader, then retry.")
    leader = leaders[0]
    host, port = leader["node"].rsplit(":", 1)
    if host not in ("localhost", "127.0.0.1"):
        raise RuntimeError("Only local voters can be controlled by this helper.")
    process = local_voter(int(port))
    if not process:
        raise RuntimeError("The leader listener could not be found. Retry status.")
    tokens = [token.strip('"') for token in shlex.split(process["command"], posix=False)]
    def flag(name):
        return tokens[tokens.index(name) + 1]
    data = Path(flag("--data-dir"))
    if not data.is_absolute():
        data = ROOT / data
    if not data.is_dir():
        raise RuntimeError("The original voter data directory was not found. Nothing was stopped.")
    record = {"port": int(port), "address": flag("--address"), "peers": flag("--peers"),
              "data_dir": str(data.resolve()), "doc": args.doc, "previous_term": int(leader["term"])}
    args.state_file.parent.mkdir(parents=True, exist_ok=True)
    args.state_file.write_text(json.dumps(record, indent=2), encoding="utf8")
    stop_voter(int(port))
    print(f"\nStopped elected leader {leader['node']} (PID {process['pid']}). Its disk was kept.", flush=True)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        after = states(args.peers, args.doc)
        if any(item["role"] == "leader" and int(item.get("term", 0)) > record["previous_term"] for item in after):
            display(after, args.doc)
            print("Replacement leader elected in a higher term. Return to the editor and save a new line.")
            return
        time.sleep(.2)
    raise RuntimeError("No replacement was observed yet. Keep the recording and run status again.")


def recover(args):
    record = json.loads(args.state_file.read_text(encoding="utf8"))
    if local_voter(record["port"]):
        raise RuntimeError("That voter is already running. Use status to inspect it.")
    data = Path(record["data_dir"])
    if not data.is_dir():
        raise RuntimeError("The saved disk directory is missing. Recovery was not started.")
    command = [sys.executable, str(ROOT / "run.py"), "docnode", "--port", str(record["port"]),
               "--address", record["address"], "--peers", record["peers"], "--data-dir", str(data)]
    print(f"Restarting {record['address']} on its original disk:\n{data}\n"
          "Keep this recovery terminal open. Use the other terminal for status.\n"
          "At the end, press Ctrl+C here before Stop demo.cmd.\n", flush=True)
    process = subprocess.Popen(command, cwd=ROOT)
    try:
        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # The verified port identifies the real Python child even when
                # a Windows virtual-environment launcher adds a wrapper process.
                stop_voter(record["port"])
                process.wait(timeout=5)


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "fail-leader", "recover"))
    parser.add_argument("--doc", default="video-demo-01")
    parser.add_argument("--peers", default="localhost:50051,localhost:50052,localhost:50053")
    parser.add_argument("--state-file", type=Path, default=ROOT / "logs/recording-failure.json")
    args = parser.parse_args()
    args.peers = args.peers.split(",")
    try:
        if args.action == "status":
            display(states(args.peers, args.doc), args.doc)
        elif args.action == "fail-leader":
            fail_leader(args)
        else:
            recover(args)
    except (RuntimeError, ValueError, OSError) as error:
        print(f"\nRecording control: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
