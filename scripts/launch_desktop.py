"""Start the local demo stack when needed, then open the graphical client."""
import argparse
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-only", action="store_true")
    parser.add_argument("--gateway", default="localhost:50070")
    parser.add_argument("--fake-llm", action="store_true")
    parser.add_argument("--model-path", type=Path)
    args = parser.parse_args()
    if not args.client_only and not listening(50070):
        if any(listening(p) for p in (50051, 50052, 50053, 50061)):
            raise RuntimeError("Some demo ports are already in use. Stop the earlier demo before starting a new stack.")
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        env = dict(os.environ)
        model = args.model_path or next((p for p in [ROOT / "models/qwen-1.5b", ROOT / "models/qwen-transformers"]
                                        if (p / "model.safetensors").exists()), None)
        command = [sys.executable, "scripts/cluster.py", "start"]
        if args.fake_llm or model is None:
            command.append("--fake-llm")
            print("Starting classroom demo with clearly labelled demo AI responses.", flush=True)
        else:
            if not all(importlib.util.find_spec(name) for name in ("torch", "transformers")):
                raise RuntimeError("Run Set up real AI.cmd once to install the model runtime.")
            env.update(ASSIST_PROVIDER="transformers", ASSIST_MODEL_PATH=str(model.resolve()))
            if "1.5" in str(model):
                env.setdefault("ASSIST_DTYPE", "bfloat16")
            print("Starting local CPU model and document cluster…", flush=True)
        with (logs / "launcher.log").open("w", encoding="utf8") as output:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                             start_new_session=os.name != "nt")
        deadline = time.monotonic() + 180
        while not (listening(50070) and listening(50061)):
            if process.poll() is not None:
                raise RuntimeError("Server startup failed. See logs/launcher.log and the service logs.")
            if time.monotonic() > deadline:
                raise RuntimeError("Startup is taking too long. See logs/launcher.log and logs/assist.log.")
            time.sleep(0.5)
    print("Opening Commonplace. Use Stop demo.cmd when the team is finished.", flush=True)
    return subprocess.call([sys.executable, "run.py", "desktop", "--gateway", args.gateway], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
