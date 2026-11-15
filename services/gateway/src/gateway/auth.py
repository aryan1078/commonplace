"""Users, passwords and login tokens.

Passwords are stored as salted PBKDF2-SHA256 hashes (200,000 iterations), so
a leaked users.json does not reveal them. Hashing is deliberately slow, so it
runs in a worker thread instead of blocking the event loop that serves every
other client. A login for an unknown username is checked against a dummy
hash, so it takes as long as a wrong password and response times do not
reveal which usernames exist.

Tokens are random (secrets.token_urlsafe), held only in the gateway's memory
and expire after a fixed time. Logging out revokes a token at once and closes
every Join stream opened with it.
"""

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ITERATIONS = 200_000
SALT_BYTES = 16
DEFAULT_TOKEN_TTL_S = 8 * 3600


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> dict:
    """A users.json record for this password."""
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return {"salt": salt.hex(), "hash": digest.hex(), "iterations": iterations}


def verify_password(password: str, record: dict) -> bool:
    expected = bytes.fromhex(record["hash"])
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(record["salt"]), int(record["iterations"])
    )
    return hmac.compare_digest(digest, expected)  # constant time


def load_users(path: Path) -> dict[str, dict]:
    """username -> hash record. A missing file means no users."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("users", {})


def save_users(path: Path, users: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"users": dict(sorted(users.items()))}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # never leaves a half-written file behind


class UserStore:
    def __init__(self, users: dict[str, dict]):
        self._users = users
        # Same cost as a real record, so unknown names take as long as known ones.
        self._dummy = hash_password(secrets.token_urlsafe(16))

    async def check(self, username: str, password: str) -> bool:
        record = self._users.get(username)
        ok = await asyncio.to_thread(verify_password, password, record or self._dummy)
        return ok and record is not None


@dataclass
class Session:
    token: str
    username: str
    expires_at: float  # seconds since 1970
    _on_revoke: list[Callable[[], None]] = field(default_factory=list, repr=False)


class TokenStore:
    def __init__(self, ttl_s: float = DEFAULT_TOKEN_TTL_S, clock: Callable[[], float] = time.time):
        self._ttl_s = ttl_s
        self._clock = clock
        self._sessions: dict[str, Session] = {}

    def issue(self, username: str) -> Session:
        session = Session(secrets.token_urlsafe(32), username, self._clock() + self._ttl_s)
        self._sessions[session.token] = session
        return session

    def validate(self, token: str) -> Session | None:
        """The live session for this token, or None (unknown, expired or revoked)."""
        session = self._sessions.get(token)
        if session is None:
            return None
        if self._clock() >= session.expires_at:
            self.revoke(token)  # expired: also ends its Join streams
            return None
        return session

    def seconds_left(self, session: Session) -> float:
        return max(0.0, session.expires_at - self._clock())

    def revoke(self, token: str) -> bool:
        """Logs a token out. Returns False if it was not valid."""
        session = self._sessions.pop(token, None)
        if session is None:
            return False
        for callback in session._on_revoke:
            callback()
        return True

    def on_revoke(self, session: Session, callback: Callable[[], None]) -> Callable[[], None]:
        """Calls callback when the session ends. Returns an unregister function."""
        session._on_revoke.append(callback)

        def unregister() -> None:
            if callback in session._on_revoke:
                session._on_revoke.remove(callback)

        return unregister
