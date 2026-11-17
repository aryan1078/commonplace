"""Bootstrap the host once. Browser visitors install nothing."""
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if sys.version_info[:2] != (3, 11):
    raise SystemExit("Install Python 3.11, then run this launcher again.")
python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if not python.exists():
    subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
inputs = [ROOT / "requirements.txt", ROOT / "requirements-web.txt", *sorted((ROOT / "proto").rglob("*.proto"))]
signature = hashlib.sha256(b"".join(p.read_bytes() for p in inputs)).hexdigest()
stamp = ROOT / ".venv/commonplace-web.sha256"
if not stamp.exists() or stamp.read_text() != signature:
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-web.txt")], check=True)
    subprocess.run([str(python), str(ROOT / "scripts/gen_proto.py")], check=True)
    stamp.write_text(signature, encoding="utf8")
sys.exit(subprocess.call([str(python), str(ROOT / "scripts/launch_web.py"), *sys.argv[1:]], cwd=ROOT))
