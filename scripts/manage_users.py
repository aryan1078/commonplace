"""Adds, removes and lists the users who can log in to the gateway.

    python scripts/manage_users.py list
    python scripts/manage_users.py add dave            (asks for the password)
    python scripts/manage_users.py add dave --password s3cret
    python scripts/manage_users.py remove dave

Only salted PBKDF2 hashes are stored (config/users.json by default). Restart
the gateway after a change; it reads the file at start-up.
"""

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "gateway" / "src"))

from gateway.auth import hash_password, load_users, save_users  # noqa: E402

DEFAULT_FILE = ROOT / "config" / "users.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="add a user or change a password")
    add.add_argument("username")
    add.add_argument("--password", help="omit to be asked (keeps it out of shell history)")
    remove = sub.add_parser("remove", help="remove a user")
    remove.add_argument("username")
    sub.add_parser("list", help="list usernames")
    args = parser.parse_args(argv)

    users = load_users(args.file)
    if args.command == "list":
        print("\n".join(users) if users else "(no users)")
        return 0
    if args.command == "remove":
        if users.pop(args.username, None) is None:
            print(f"no user {args.username!r}", file=sys.stderr)
            return 1
        save_users(args.file, users)
        print(f"removed {args.username}")
        return 0

    password = args.password or getpass.getpass(f"password for {args.username}: ")
    if not password:
        print("the password must not be empty", file=sys.stderr)
        return 1
    existed = args.username in users
    users[args.username] = hash_password(password)
    save_users(args.file, users)
    print(f"{'updated' if existed else 'added'} {args.username}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
