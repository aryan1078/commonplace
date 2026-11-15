"""Generates the Python gRPC code for every .proto file into gen/python.

    python scripts/gen_proto.py

Uses the protoc bundled with grpcio-tools, so nothing else needs installing
and it works the same on Windows, Linux and macOS. The output folder is wiped
first, so code for a deleted .proto file never lingers.
"""

import shutil
import sys
from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "proto"
OUT_DIR = ROOT / "gen" / "python"


def main() -> int:
    protos = sorted(PROTO_DIR.rglob("*.proto"))
    if not protos:
        print(f"no .proto files under {PROTO_DIR}", file=sys.stderr)
        return 1

    shutil.rmtree(OUT_DIR, ignore_errors=True)
    OUT_DIR.mkdir(parents=True)

    # grpc_tools ships the well-known types (google/protobuf/*.proto).
    well_known = Path(protoc.__file__).parent / "_proto"
    args = [
        "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"-I{well_known}",
        f"--python_out={OUT_DIR}",
        f"--pyi_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
        *(str(p) for p in protos),
    ]
    code = protoc.main(args)
    if code != 0:
        print(f"protoc failed with exit code {code}", file=sys.stderr)
        return code

    # Make the generated folders regular packages, so tools that do not
    # understand namespace packages (and pytest's rootdir logic) are happy.
    for folder in [OUT_DIR, *(p for p in OUT_DIR.rglob("*") if p.is_dir())]:
        if folder != OUT_DIR:
            (folder / "__init__.py").touch()

    print(f"generated code for {len(protos)} proto files in {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
