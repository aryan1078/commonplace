# Browser demo deployment

## Visitors

Open https://aryan1078.github.io/commonplace/ and sign in. Visitors need no Python, terminal, download or browser extension. The page contains the editor itself. The current host must be online.

## Host on this laptop

Double-click **Start online demo.cmd**. It bootstraps Python dependencies, starts three independent document replicas, Assist, the gateway and a browser edge. It then uses OpenSSH to create a free localhost.run HTTPS tunnel, with no hosting account. This repository-owner launcher also uses the already authenticated GitHub CLI to publish the current public endpoint on the demo-status branch. The stable GitHub editor discovers that endpoint on startup and after a connection failure. Visitors never receive a GitHub token. Read the public URL from the launcher or `logs/public-url.txt`. That URL serves the complete editor too, so it can be shared immediately.

The launcher checks the public health endpoint before announcing the URL. Keep the host awake, connected to the internet and running the launcher. Use **Stop demo.cmd** when finished. Documents remain in `data/node1`, `data/node2` and `data/node3`.

A free tunnel has no uptime promise. Its hostname can change after a restart or rotate during a long session. Test it immediately before recording or evaluation. The browser edge and login do not make the laptop an always-on cloud deployment.

## Keep the published editor connected

**Start online demo.cmd** includes `--publish-status aryan1078/commonplace`. The host needs an authenticated `gh` CLI with write access to this repository. The launcher watches the tunnel output, verifies each replacement address, updates `logs/public-url.txt`, and publishes only the HTTPS origin and update time to `endpoint.json` on the separate `demo-status` branch. These small updates do not rebuild Pages or trigger the main-branch test workflow.

The editor fetches this public file through GitHub's API when opening, and again after a failed connection. No GitHub credential is sent to the browser. In-memory browser sessions remain on the same Python edge when the tunnel changes. Browser request IDs prevent an acknowledged action from being applied twice after its HTTP reply is lost. An outstanding save is resolved before a newer draft is merged and sent.

GitHub's unauthenticated API and the free tunnel have rate and availability limits. Brief reconnection failures remain possible. Keep the current tab open and retry a failed save. A fresh browser page should use the stable Pages address when an older tunnel domain has expired.

For a different repository, use `python scripts/setup_browser.py --share --publish-status OWNER/REPOSITORY` and change the discovery address in `scripts/build_browser_site.py`. To run a free direct tunnel without GitHub publication, use `python scripts/setup_browser.py --share`. Read its latest address from `logs/public-url.txt` after a rotation.

The shared UI is copied into Pages with:

```powershell
.venv\Scripts\python.exe scripts/build_browser_site.py --api https://YOUR-CURRENT-TUNNEL.app.lhr.life
```

Commit the generated files under `docs/` when changing the interface. The configured origin is a fallback if the public discovery API cannot respond. Source files and endpoint files contain no passwords or tokens.

## Local and LAN fallback

Double-click **Start browser demo.cmd** to open http://localhost:8080. For a trusted LAN:

```powershell
python scripts/setup_browser.py --lan
```

Other laptops on that LAN open `http://HOST_PRIVATE_IP:8080` in a browser. Allow port 8080 through the Windows firewall only on the selected private network if prompted. Plain HTTP is for the controlled local network. Use the HTTPS tunnel for public access.

The original desktop remains available through **Start Commonplace.cmd**. For an already running remote gateway, use `python scripts/launch_desktop.py --client-only --gateway HOST_IP:50070`, with certificate-verified TLS for an internet connection.

## What is public

Only the browser edge is tunnelled. Browser requests use gRPC-Web; the edge uses native gRPC to the gateway. The browser cannot configure an arbitrary internal server. The gateway owns login and authorization. Browser keys and gateway tokens stay in memory and are revoked/expired through the normal session paths.

This release deliberately has a shared workspace. Alice, Bob and Carol are published demo accounts; all authenticated users can edit all documents. Do not store personal or confidential material in the public demo. For a private group, create accounts with `scripts/manage_users.py`, remove the demo accounts and restart the gateway. The session cap and sign-in throttling are classroom safeguards, not a production abuse-protection system.

## Moving to a server later

The same Python processes can run on a persistent Linux VM. Keep one data directory per voter, put the browser edge behind HTTPS, and keep internal gRPC ports private. Separate machines improve failure independence; three processes on one laptop do not survive failure of that laptop. No VM or paid service was provisioned.

GitHub Pages serves static assets and cannot run the Python services. Render's free filesystem is ephemeral and has no persistent disks, so it cannot preserve this release's SQLite recovery state. The working free route uses the laptop's compute and disks.

Sources checked November 17, 2026: [localhost.run basics](https://localhost.run/docs), [free domain rotation](https://localhost.run/docs/faq), [gRPC-Web](https://grpc.io/docs/platforms/web/basics/), [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages), [Render persistence](https://render.com/docs/free).
