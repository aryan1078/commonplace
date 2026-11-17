"""Keep the browser edge (and optional free tunnel) alive until Stop demo.cmd."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

from launch_desktop import main as start_services, listening
from publish_browser_endpoint import publish

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--share", action="store_true", help="Create a temporary public HTTPS URL, no account required")
    parser.add_argument("--lan", action="store_true", help="Listen on all network interfaces")
    parser.add_argument("--fake-llm", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--publish-status", metavar="OWNER/REPOSITORY", help="Use authenticated gh to keep a public endpoint registry current")
    args = parser.parse_args()
    if listening(8080):
        raise RuntimeError("Port 8080 is already in use. Stop the earlier browser demo first.")
    tunnel_binary = shutil.which("ssh") if args.share else None
    if args.share and not tunnel_binary:
        raise RuntimeError("The free public demo needs OpenSSH. Enable the Windows OpenSSH Client or use the LAN option.")
    start_services(["--servers-only", *(["--fake-llm"] if args.fake_llm else [])])
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    origin_file = logs / "public-origins.json"
    origin_file.write_text("[]", encoding="utf8")
    discovery = f"https://api.github.com/repos/{args.publish_status}/contents/endpoint.json?ref=demo-status" if args.publish_status else ""
    stop = logs / "stop-requested"
    stop.unlink(missing_ok=True)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    processes = []
    try:
        with (logs / "browser.log").open("w", encoding="utf8") as output:
            web = subprocess.Popen([sys.executable, "run.py", "web", "--host", "0.0.0.0" if args.lan else "127.0.0.1",
                "--origin-file", str(origin_file), "--discovery", discovery],
                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, **flags)
        processes.append(web)
        deadline = time.monotonic() + 30
        while not listening(8080):
            if web.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("The browser server did not start. See logs/browser.log.")
            time.sleep(.25)
        url = "http://localhost:8080"
        if tunnel_binary:
            tunnel_log = logs / "tunnel.log"
            with tunnel_log.open("w", encoding="utf8") as output:
                tunnel = subprocess.Popen([tunnel_binary, "-F", "none", "-o", "StrictHostKeyChecking=accept-new",
                    "-o", f"UserKnownHostsFile={logs / 'tunnel-known-hosts'}", "-o", "BatchMode=yes",
                    "-o", "PreferredAuthentications=none", "-o", "ServerAliveInterval=30",
                    "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=15",
                    "-R", "80:127.0.0.1:8080", "nokey@localhost.run"],
                    cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, **flags)
            processes.append(tunnel)
            deadline = time.monotonic() + 60
            while True:
                matches = re.findall(r"https://[a-z0-9-]+(?:\.app)?\.lhr\.(?:life|rocks)", tunnel_log.read_text(encoding="utf8", errors="replace"))
                if matches:
                    url = matches[-1]
                    break
                if tunnel.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("The public tunnel did not connect. Restart without --share for localhost, or use --lan. See logs/tunnel.log.")
                time.sleep(.5)
            # A printed hostname alone is not proof that the tunnel is serving.
            with urlopen(f"{url}/healthz", timeout=20) as response:
                if response.status != 200 or b'"commonplace-web"' not in response.read():
                    raise RuntimeError("The public URL did not reach Commonplace. Restart with --lan.")
            (logs / "public-url.txt").write_text(url, encoding="utf8")
            origin_file.write_text(json.dumps([url]), encoding="utf8")
            if args.publish_status:
                publish(args.publish_status, url)
            print("This temporary URL changes after a restart. Keep this laptop awake and connected.", flush=True)
        print(f"Open Commonplace: {url}\nVisitors need only a browser. Use Stop demo.cmd when finished.", flush=True)
        if not args.no_open:
            webbrowser.open(url)
        while not stop.exists():
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("The browser server or tunnel stopped. See logs/browser.log and logs/tunnel.log.")
            if tunnel_binary:
                matches = re.findall(r"https://[a-z0-9-]+(?:\.app)?\.lhr\.(?:life|rocks)", tunnel_log.read_text(encoding="utf8", errors="replace"))
                if matches and matches[-1] != url:
                    replacement = matches[-1]
                    try:
                        with urlopen(f"{replacement}/healthz", timeout=10) as response:
                            if response.status != 200 or b'"commonplace-web"' not in response.read():
                                raise RuntimeError("New tunnel is not ready yet.")
                        origins = json.loads(origin_file.read_text(encoding="utf8"))
                        temporary = origin_file.with_suffix(".tmp")
                        temporary.write_text(json.dumps(list(dict.fromkeys([*origins, replacement]))[-20:]), encoding="utf8")
                        temporary.replace(origin_file)
                        if args.publish_status:
                            publish(args.publish_status, replacement)
                        url = replacement
                        (logs / "public-url.txt").write_text(url, encoding="utf8")
                        print(f"Tunnel address updated: {url}", flush=True)
                    except Exception as error:
                        print(f"Waiting to publish the new tunnel: {error}", flush=True)
                        time.sleep(4)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
