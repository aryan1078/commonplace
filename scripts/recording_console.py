"""One numbered control window for the two-person video recording."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import demo_control as control

ROOT = Path(__file__).resolve().parents[1]


class RecordingConsole:
    def __init__(self, peers, doc, state_file, stop_file):
        self.peers, self.doc = peers, doc
        self.state_file, self.stop_file = state_file, stop_file
        self.recovery = None
        self.recovery_log = None
        (ROOT / "logs").mkdir(exist_ok=True)

    def status(self):
        control.display(control.states(self.peers, self.doc), self.doc)

    def fail(self):
        print("Stopping only the currently elected document voter. Its disk is kept.\n", flush=True)
        control.fail_leader(SimpleNamespace(peers=self.peers, doc=self.doc, state_file=self.state_file))

    def recover(self):
        if self.recovery and self.recovery.poll() is None:
            print("The recovered voter is already running. Choose 1 to inspect it.")
            return
        record = json.loads(self.state_file.read_text(encoding="utf8"))
        if control.local_voter(record["port"]):
            print("That voter is already running. Choose 1 to inspect it.")
            return
        if self.recovery_log:
            self.recovery_log.close()
        self.recovery_log = (self.state_file.parent / "recording-recovery.log").open("w", encoding="utf8")
        print(f"Restarting {record['address']} using its original disk:\n{record['data_dir']}\n"
              "Wait for the three replicas to agree...", flush=True)
        self.recovery = subprocess.Popen([
            sys.executable, str(ROOT / "scripts/demo_control.py"), "recover",
            "--state-file", str(self.state_file), "--stop-file", str(self.stop_file)],
            cwd=ROOT, stdout=self.recovery_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.recovery.poll() is not None:
                raise RuntimeError("Recovery stopped. See logs/recording-recovery.log.")
            items = control.states(self.peers, self.doc)
            if (all(item["role"] != "unreachable" for item in items)
                    and len({(item.get("revision"), item.get("digest")) for item in items}) == 1):
                control.display(items, self.doc)
                print("\nRecovery complete. This window keeps the recovered voter running.\n"
                      "Minimize this window to return to the editor. Use 0 when the recording is finished.")
                return
            time.sleep(.25)
        self.status()
        print("Recovery is still running. Choose 1 again after a few seconds.")

    def verify(self):
        print("Running the independent 200-edit failure/recovery check.\n"
              "This uses a separate test cluster and preserves your demo document.\n", flush=True)
        result = subprocess.call([sys.executable, str(ROOT / "scripts/verify_cluster.py")], cwd=ROOT)
        if result:
            raise RuntimeError("The verification did not pass. Keep the output and check it before recording.")

    def tests(self):
        print("Running the Python test suite. Do this before starting OBS recording.\n", flush=True)
        env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        with (ROOT / "logs/recording-tests.txt").open("w", encoding="utf8") as output:
            process = subprocess.Popen([sys.executable, "-m", "pytest", "-o", "addopts=", "-o",
                "faulthandler_timeout=25", "-vv"], cwd=ROOT, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf8", errors="replace")
            for line in process.stdout:
                print(line, end="", flush=True)
                output.write(line)
            result = process.wait()
        if result:
            raise RuntimeError("Some tests did not pass. Review the output before filming.")
        print("\nTest output saved. During the video, choose 5 to show its final lines.")

    def show_tests(self):
        path = ROOT / "logs/recording-tests.txt"
        if not path.exists():
            print("No saved test run yet. Choose 6 before recording, then use 5 during the video.")
            return
        print("Python tests — saved pre-recording run:\n")
        print("\n".join(path.read_text(encoding="utf8", errors="replace").splitlines()[-6:]))

    def stop(self):
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.write_text("stop\n", encoding="utf8")
        print("Stopping the demo services. Saved documents remain on disk.", flush=True)
        if self.recovery:
            try:
                self.recovery.wait(timeout=12)
            except subprocess.TimeoutExpired:
                record = json.loads(self.state_file.read_text(encoding="utf8"))
                control.stop_voter(record["port"])
                self.recovery.wait(timeout=5)
        if self.recovery_log:
            self.recovery_log.close()

    def run(self):
        actions = {"1": self.status, "2": self.fail, "3": self.recover,
                   "4": self.verify, "5": self.show_tests, "6": self.tests}
        while True:
            if os.name == "nt":
                os.system("cls")
            print(f"COMMONPLACE RECORDING CONTROLS\nDocument: {self.doc}\n\n"
                  "1  Show the three servers and the leader\n"
                  "2  Stop the current leader (for the failure demonstration)\n"
                  "3  Restart the stopped server on its original disk\n"
                  "4  Run the 200-edit failure and recovery check\n"
                  "5  Show the saved Python test result\n"
                  "6  Run Python tests now (before recording)\n"
                  "7  Change the video take number\n"
                  "0  Finish and stop the demo\n\n"
                  "Type ONE number and press Enter. No commands need to be pasted.\n"
                  "Keep this window open; minimize it when showing the browser.\n")
            choice = input("Your number: ").strip()
            if choice == "0":
                return
            try:
                if choice == "7":
                    take = int(input("Take number (1, 2, 3...): ").strip())
                    if not 1 <= take <= 99:
                        raise ValueError("Use a take number from 1 to 99.")
                    self.doc = f"video-demo-{take:02}"
                    print(f"Use the matching document name in the editor: Video Demo {take:02}")
                elif choice in actions:
                    actions[choice]()
                else:
                    print("Choose a number from 0 to 7.")
            except (RuntimeError, OSError, ValueError) as error:
                print(f"\nCould not complete this step: {error}")
            input("\nLeave this result visible for the video. Press Enter when you want the menu again.")


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peers", default="localhost:50051,localhost:50052,localhost:50053")
    parser.add_argument("--doc", default="video-demo-01")
    parser.add_argument("--state-file", type=Path, default=ROOT / "logs/recording-failure.json")
    parser.add_argument("--stop-file", type=Path, default=ROOT / "logs/stop-requested")
    args = parser.parse_args()
    console = RecordingConsole(args.peers.split(","), args.doc, args.state_file, args.stop_file)
    try:
        console.run()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        console.stop()


if __name__ == "__main__":
    main()
