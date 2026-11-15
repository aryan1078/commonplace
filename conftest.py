"""Generates the protobuf code before the tests run, if it is missing.

gen/ is not committed, so a fresh checkout would otherwise fail every test
with an ImportError instead of a useful message.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if not (ROOT / "gen" / "python" / "collab" / "v1" / "gateway_pb2.py").exists():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_proto.py")], check=True)
