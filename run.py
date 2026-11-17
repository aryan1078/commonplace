"""Runs any part of the system from source.

    python run.py docnode  [--port 50051]
    python run.py assist
    python run.py gateway  [--port 50070] [--docnodes host:port] [--assist host:port]
    python run.py client   [--gateway host:port] shell | demo | simulate ...

Each service lives in its own source folder; this script puts them (and the
generated protobuf code) on sys.path, so nothing has to be installed as a
package and the same command works on Windows and Linux.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_ROOTS = [
    ROOT / "gen" / "python",
    ROOT / "services" / "docnode" / "src",
    ROOT / "services" / "gateway" / "src",
    ROOT / "services" / "assist" / "src",
    ROOT / "clients",
]
COMMANDS = {
    "docnode": "docnode.__main__",
    "assist": "assist.__main__",
    "gateway": "gateway.__main__",
    "client": "collab_client.__main__",
    "desktop": "collab_client.desktop",
    "web": "collab_client.browser",
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip())
        return 2
    if not (ROOT / "gen" / "python" / "collab").exists():
        print("Generated code is missing. Run:  python scripts/gen_proto.py", file=sys.stderr)
        return 1

    # Documents and LLM answers can hold any character (emoji, Devanagari...).
    # On Windows, output redirected to a file or pipe defaults to the ANSI code
    # page, where printing them would crash; UTF-8 never does.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    sys.path[:0] = [str(p) for p in SOURCE_ROOTS]
    name = sys.argv[1]
    module = __import__(COMMANDS[name], fromlist=["main"])
    return module.main(sys.argv[2:]) or 0


if __name__ == "__main__":
    sys.exit(main())
