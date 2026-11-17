"""Publish only the public tunnel origin on a separate Git branch.

No passwords, tokens, document contents or local paths are published. Requires
the host's authenticated gh CLI and write access to the selected repository.
"""
import base64
from datetime import datetime, timezone
import json
import re
import subprocess
from urllib.parse import urlparse

BRANCH = "demo-status"


def api(path, method="GET", body=None):
    result = subprocess.run(["gh", "api", path, "--method", method, *(["--input", "-"] if body is not None else [])],
        input=json.dumps(body) if body is not None else None, text=True, encoding="utf8", capture_output=True)
    if result.returncode:
        raise RuntimeError(f"GitHub endpoint publication failed ({method} {path}). Check gh authentication and repository access.")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def publish(repo, url):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Use owner/repository for --publish-status.")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+(?:\.app)?\.lhr\.(?:life|rocks)", parsed.netloc) or parsed.path:
        raise ValueError("Only the current public tunnel origin can be published.")
    try:
        api(f"repos/{repo}/git/ref/heads/{BRANCH}")
    except RuntimeError:
        default = api(f"repos/{repo}")["default_branch"]
        sha = api(f"repos/{repo}/git/ref/heads/{default}")["object"]["sha"]
        api(f"repos/{repo}/git/refs", "POST", {"ref": f"refs/heads/{BRANCH}", "sha": sha})
    path = f"repos/{repo}/contents/endpoint.json"
    try:
        previous = api(f"{path}?ref={BRANCH}")
        current = json.loads(base64.b64decode(previous["content"]))
        if current.get("url") == url:
            return
    except RuntimeError:
        previous = {}
    data = {"url": url, "updated_at": datetime.now(timezone.utc).isoformat(), "hosting": "temporary laptop demo"}
    body = {"message": "Update temporary browser endpoint", "branch": BRANCH,
            "content": base64.b64encode((json.dumps(data) + "\n").encode()).decode()}
    if previous.get("sha"):
        body["sha"] = previous["sha"]
    api(path, "PUT", body)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("url")
    args = parser.parse_args()
    publish(args.repo, args.url)
