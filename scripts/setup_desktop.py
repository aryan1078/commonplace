"""One-time isolated desktop setup, called by the Windows launcher."""
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
python = ROOT / ".venv/Scripts/python.exe"
if sys.version_info[:2] != (3, 11):
    raise SystemExit("Install Python 3.11 and run this launcher with Python 3.11.")
if not python.exists():
    subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
requirements = [ROOT / "requirements.txt", ROOT / "requirements-desktop.txt"]
signature = hashlib.sha256(b"".join(p.read_bytes() for p in requirements)).hexdigest()
stamp = ROOT / ".venv/commonplace-desktop.sha256"
if not stamp.exists() or stamp.read_text() != signature:
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements[0]), "-r", str(requirements[1])], check=True)
    subprocess.run([str(python), str(ROOT / "scripts/gen_proto.py")], check=True)
    stamp.write_text(signature)
if "--setup-only" in sys.argv:
    raise SystemExit(0)
sys.exit(subprocess.call([str(python), str(ROOT / "scripts/launch_desktop.py"), *sys.argv[1:]], cwd=ROOT))
