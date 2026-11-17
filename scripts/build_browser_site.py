"""Copy the shared UI to GitHub Pages with a non-secret gRPC-Web endpoint."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def build(api):
    parsed = urlparse(api)
    if api and (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Use the HTTPS origin of your browser server, without a path or credentials.")
    source, destination = ROOT / "clients/collab_client/ui", ROOT / "docs"
    for name in ("index.html", "style.css", "app.js", "browser.js"):
        text = (source / name).read_text(encoding="utf8")
        if name == "index.html":
            text = text.replace('<html lang="en">', '<html lang="en" data-client="browser">')
        (destination / name).write_text(text, encoding="utf8", newline="\n")
    (destination / "browser-config.js").write_text(
        "// Public classroom endpoint; no credentials. Rebuild after restarting the tunnel.\n"
        f"window.COMMONPLACE_API = {json.dumps(api.rstrip('/'))};\n"
        'window.COMMONPLACE_DISCOVERY = "https://api.github.com/repos/aryan1078/commonplace/contents/endpoint.json?ref=demo-status";\n', encoding="utf8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    build(parser.parse_args().api)
