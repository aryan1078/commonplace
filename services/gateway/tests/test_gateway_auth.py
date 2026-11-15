import asyncio

from gateway.auth import ITERATIONS, TokenStore, UserStore, hash_password, load_users, save_users, verify_password


def test_hash_is_salted_and_verifies():
    a, b = hash_password("secret"), hash_password("secret")
    assert a["iterations"] == ITERATIONS == 200_000
    assert a["salt"] != b["salt"] and a["hash"] != b["hash"]
    assert verify_password("secret", a) and not verify_password("Secret", a)


def test_user_store_checks_passwords():
    store = UserStore({"alice": hash_password("alice123", iterations=1000)})
    assert asyncio.run(store.check("alice", "alice123"))
    assert not asyncio.run(store.check("alice", "wrong"))
    assert not asyncio.run(store.check("mallory", "alice123"))  # unknown user: dummy hash


def test_users_file_round_trip(tmp_path):
    path = tmp_path / "config" / "users.json"
    assert load_users(path) == {}
    save_users(path, {"bob": hash_password("x", iterations=10)})
    assert list(load_users(path)) == ["bob"]
    assert path.read_text().endswith("\n")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_tokens_expire_and_revoke():
    clock = Clock()
    tokens = TokenStore(ttl_s=60, clock=clock)
    s = tokens.issue("alice")
    assert len(s.token) >= 40 and tokens.validate(s.token) is s

    closed = []
    unregister = tokens.on_revoke(s, lambda: closed.append("a"))
    tokens.on_revoke(s, lambda: closed.append("b"))
    unregister()
    assert tokens.revoke(s.token) and closed == ["b"]
    assert tokens.validate(s.token) is None and not tokens.revoke(s.token)

    s2 = tokens.issue("bob")
    clock.t += 61
    assert tokens.validate(s2.token) is None  # expired
