"""Starts every service on this machine, for development and the demo.

    python scripts/start_local.py              # LLM through a local Ollama server
    python scripts/start_local.py --fake-llm   # canned LLM answers, no model needed
    python scripts/start_local.py --stop       # stop services left running elsewhere

Each service runs as its own process (as it would on its own node) with its
log in logs/<service>.log. Press Ctrl+C to stop them all.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
PID_FILE = LOGS / "pids.txt"

DOCNODE_PORT, ASSIST_PORT, GATEWAY_PORT = 50051, 50061, 50070


def services(fake_llm: bool) -> list[tuple[str, list[str], dict, int]]:
    """(name, run.py arguments, extra environment, port) for each service."""
    assist_env = {"ASSIST_PROVIDER": "fake"} if fake_llm else {}
    return [
        ("docnode", ["docnode", "--port", str(DOCNODE_PORT)], {}, DOCNODE_PORT),
        ("assist", ["assist"], {"ASSIST_PORT": str(ASSIST_PORT), **assist_env}, ASSIST_PORT),
        ("gateway", ["gateway", "--port", str(GATEWAY_PORT), "--docnodes", f"localhost:{DOCNODE_PORT}",
                     "--assist", f"localhost:{ASSIST_PORT}"], {}, GATEWAY_PORT),
    ]


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def stop(procs: list[subprocess.Popen]) -> None:
    for p in reversed(procs):  # gateway first, document service last
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    PID_FILE.unlink(missing_ok=True)


def stop_from_pid_file() -> int:
    if not PID_FILE.exists():
        print("nothing to stop")
        return 0
    for pid in PID_FILE.read_text().split():
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
            else:
                os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    PID_FILE.unlink(missing_ok=True)  # the launcher may already have removed it
    print("stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fake-llm", action="store_true", help="use canned LLM answers instead of Ollama")
    parser.add_argument("--stop", action="store_true", help="stop services started by an earlier run")
    args = parser.parse_args()
    if args.stop:
        return stop_from_pid_file()

    if not (ROOT / "gen" / "python" / "collab").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_proto.py")], check=True)
    LOGS.mkdir(exist_ok=True)
    busy = [name for name, _, _, port in services(args.fake_llm) if port_open(port)]
    if busy:
        print(f"ports already in use for: {', '.join(busy)}. Stop them first (--stop).")
        return 1

    # Our own process group on Windows, so Ctrl+C reaches only this script,
    # which then stops the services in order.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    procs: list[subprocess.Popen] = []
    try:
        for name, run_args, env, port in services(args.fake_llm):
            log = open(LOGS / f"{name}.log", "w", encoding="utf-8")
            procs.append(subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "run.py"), *run_args],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, **env, "PYTHONUNBUFFERED": "1"}, creationflags=flags,
            ))
            deadline = time.monotonic() + 20
            while not port_open(port):
                if procs[-1].poll() is not None or time.monotonic() > deadline:
                    print(f"{name} did not start; see logs/{name}.log")
                    stop(procs)
                    return 1
                time.sleep(0.2)
            print(f"  {name:<8} listening on :{port}  (log: logs/{name}.log)")
        PID_FILE.write_text("\n".join(str(p.pid) for p in procs))

        llm = "fake (canned answers)" if args.fake_llm else "Ollama (see logs/assist.log)"
        print(f"\nAll services up. LLM: {llm}. Try, in another terminal:")
        print("  python run.py client demo")
        print("  python run.py client simulate --users 8 --edits 25")
        print("  python run.py client shell --user alice --doc notes")
        print("\nPress Ctrl+C to stop.")
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        dead = [name for (name, *_), p in zip(services(args.fake_llm), procs) if p.poll() is not None]
        print(f"\n{', '.join(dead)} stopped unexpectedly; see logs/. Stopping the rest.")
        return 1
    except KeyboardInterrupt:
        print("\nstopping...")
        return 0
    finally:
        stop(procs)


if __name__ == "__main__":
    sys.exit(main())
