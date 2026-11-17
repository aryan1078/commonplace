"""Generates the protobuf code before the tests run, if it is missing.

gen/ is not committed, so a fresh checkout would otherwise fail every test
with an ImportError instead of a useful message.
"""

import subprocess
import sys
from importlib import invalidate_caches
from pathlib import Path

ROOT = Path(__file__).resolve().parent

generated = ROOT / "gen" / "python"
expected = [generated / proto.relative_to(ROOT / "proto").with_name(proto.stem + "_pb2.py")
            for proto in (ROOT / "proto").rglob("*.proto")]
if any(not path.exists() for path in expected):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_proto.py")], check=True)
    # pytest adds pythonpath entries before loading this file. On a cold ZIP
    # extraction Python may already have cached gen/python as nonexistent.
    invalidate_caches()
