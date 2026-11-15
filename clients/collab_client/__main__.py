"""The command-line client (node 5).

    python run.py client shell [--user alice] [--doc notes]
    python run.py client demo
    python run.py client simulate --users 8 --edits 25
"""

import argparse
import asyncio
import os

from .demo import run_demo
from .shell import run_shell
from .simulate import run_simulation


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="client", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default=os.getenv("COLLAB_GATEWAY", "localhost:50070"),
                        help="gateway address (env COLLAB_GATEWAY)")
    sub = parser.add_subparsers(dest="command", required=True)
    shell = sub.add_parser("shell", help="interactive editing session")
    shell.add_argument("--user")
    shell.add_argument("--password", help="omit to be asked")
    shell.add_argument("--doc", help="document to open right away")
    sub.add_parser("demo", help="scripted walkthrough of every feature")
    sim = sub.add_parser("simulate", help="concurrent random edits + consistency check")
    sim.add_argument("--users", type=int, default=8)
    sim.add_argument("--edits", type=int, default=25)
    sim.add_argument("--seed", type=int)
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    if args.command == "shell":
        return await run_shell(args.gateway, args.user, args.password, args.doc)
    if args.command == "demo":
        return await run_demo(args.gateway)
    print(f"simulating {args.users} users x {args.edits} edits on one document via {args.gateway} ...")
    report = await run_simulation(args.gateway, args.users, args.edits, args.seed)
    print("\n".join(report.lines()))
    return 0 if report.consistent else 1


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(run(parse_args(argv)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
