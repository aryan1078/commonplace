"""Launch and inspect the three-voter demo. Use Ctrl+C to stop owned processes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen/python"))
import grpc
from collab.v1 import raft_pb2, raft_pb2_grpc


def status(address, doc):
    with grpc.insecure_channel(address) as channel:
        reply = raft_pb2_grpc.RaftServiceStub(channel).Status(raft_pb2.StatusRequest(doc_id=doc), timeout=1)
        from google.protobuf.json_format import MessageToDict
        return MessageToDict(reply, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "status"])
    parser.add_argument("--peers", default="localhost:50051,localhost:50052,localhost:50053")
    parser.add_argument("--doc", default="notes")
    parser.add_argument("--fake-llm", action="store_true")
    args = parser.parse_args()
    peers = args.peers.split(",")
    if args.action == "status":
        for peer in peers:
            try:
                print(json.dumps(status(peer, args.doc)))
            except grpc.RpcError:
                print(json.dumps({"node": peer, "role": "unreachable"}))
        return
    commands = [
        (f"node{i+1}", ["docnode", "--port", peer.rsplit(":", 1)[1], "--address", peer,
                        "--peers", args.peers, "--data-dir", f"data/node{i+1}"])
        for i, peer in enumerate(peers)
    ]
    commands += [("assist", ["assist"]), ("gateway", ["gateway", "--docnodes", args.peers])]
    processes, files = [], []
    stop_request = ROOT / "logs" / "stop-requested"
    stop_request.unlink(missing_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    try:
        for name, command in commands:
            output = open(ROOT / "logs" / f"{name}.log", "w", encoding="utf8")
            files.append(output)
            env = dict(os.environ)
            if args.fake_llm:
                env["ASSIST_PROVIDER"] = "fake"
            env["GATEWAY_AI_MODE"] = ("Demo responses · no language model" if args.fake_llm else
                                     "Local CPU language model" if env.get("ASSIST_PROVIDER") in ("transformers", "llama_cpp")
                                     else "Configured writing service")
            process = subprocess.Popen([sys.executable, "-u", str(ROOT / "run.py"), *command],
                cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            processes.append(process)
            print(f"{name} PID {process.pid}", flush=True)
        print("Client: python run.py client shell --user alice --doc notes", flush=True)
        print("Status: python scripts/cluster.py status --doc notes", flush=True)
        while True:
            time.sleep(1)
            if stop_request.exists():
                break
            # Individual voters may be deliberately killed for the demonstration.
            if any(p.poll() is not None for p in processes[-2:]):
                raise RuntimeError("gateway or assist stopped; inspect logs")
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        for output in files:
            output.close()


if __name__ == "__main__":
    main()
