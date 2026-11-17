# Laptop, LAN and free public access

## Working local deployment

Install Python 3.11. Double-click Start Commonplace.cmd. It creates an isolated virtual environment on first launch, installs the desktop dependencies, starts three voters, Assist and the gateway, and opens the sign-in window. Keep the laptop awake. Stop demo.cmd asks the launcher to stop its own services without deleting the disks.

The initial classroom accounts are alice/alice123, bob/bob123 and carol/carol123. AI output is marked as demo output when no local model is configured. Use the README model setup for real inference. You can open Start Commonplace.cmd again for another client window.

## Another laptop on the same LAN

Run the cluster on the first laptop. On the second laptop install the project and desktop dependencies, then run `python scripts/launch_desktop.py --client-only --gateway HOST_IP:50070`. HOST_IP is the first laptop's private LAN address. The login form's Server connection also accepts this address. Use different usernames in the two windows and open the same document.

Windows Firewall must allow incoming TCP 50070 on the chosen private demo network. Review that rule on the host computer. The local-only voter addresses remain localhost because the three voters run on the host. Other clients need only the gateway port. For untrusted networks use TLS or a private tunnel.

This is a five-logical-node process deployment. To demonstrate independent machine failures, place the three voters on separate machines and use their reachable addresses in the same fixed --peers list.

## Free public route using the laptop

Tailscale's Personal plan is currently free, and Funnel is available on all plans. Funnel can publish a raw TCP endpoint. We preserve TLS end to end so Python gRPC can negotiate HTTP/2. This lets the desktop client reach the gateway from outside the LAN. The laptop still provides the compute and disk and must stay online. This route needs a Tailscale account, installed client, a signed-in device and Funnel enabled for the account. It has not been activated in this workspace.

After the account steps, use the device hostname shown by Tailscale in place of YOUR_HOST.YOUR_TAILNET.ts.net. Generate a certificate for that hostname and start an additional TLS gateway. It uses the same document voters and AI service.

```powershell
New-Item -ItemType Directory -Force deploy/certs
tailscale cert --cert-file=deploy/certs/server.crt --key-file=deploy/certs/server.key YOUR_HOST.YOUR_TAILNET.ts.net
python run.py gateway --host 127.0.0.1 --port 50071 --docnodes localhost:50051,localhost:50052,localhost:50053 --assist localhost:50061 --tls-cert deploy/certs/server.crt --tls-key deploy/certs/server.key
```

Keep that gateway terminal open. In another host terminal run:

```powershell
tailscale funnel --bg --tcp=443 tcp://127.0.0.1:50071
```

Raw forwarding lets the Python gateway negotiate the HTTP/2 protocol required by gRPC and present its certificate directly. Keep the private key local. Renew the certificate as needed using Tailscale's certificate instructions.

Use the hostname printed by Tailscale. On another computer run the desktop, set Server connection to the printed hostname with :443 and enable TLS. The public endpoint is a gRPC gateway for the desktop client. Visiting it in a browser does not display the desktop interface. Test login, editing, a leader failure and reconnect through that endpoint before using it for evaluation. Stop sharing using the corresponding Funnel off command or `tailscale funnel reset` when the demo is over.

Before sharing publicly, use scripts/manage_users.py to replace the published classroom accounts with your own accounts and restart the gateway. The workspace intentionally lets every authenticated user edit the shared documents. Public access exposes only the gateway, while voter and AI ports remain private. TLS certificate verification stays enabled in the desktop client.

Funnel setup and any public exposure require the account owner's action. No account, public endpoint or cloud bill was created here.

## Free cloud VM alternative

Oracle advertises Always Free compute, subject to its current limits, account eligibility and regional capacity. That can host the Python processes and persistent disks. This needs an Oracle account and an available instance. Confirm the console explicitly marks the selected resources Always Free and avoid a paid upgrade. We did not provision a VM. A laptop/LAN demonstration is the ready fallback.

Render's free web services have ephemeral filesystems and cannot attach persistent disks. That does not satisfy this release's durable SQLite recovery deployment. Its free static hosting also cannot run the Python voters and local model.

## Sources checked November 17, 2026

- Tailscale pricing https://tailscale.com/pricing
- Funnel availability and limits https://tailscale.com/docs/features/tailscale-funnel
- TCP forwarding command https://tailscale.com/docs/reference/tailscale-cli/funnel
- Oracle Free Tier https://www.oracle.com/cloud/free/
- Render free service persistence https://render.com/docs/free

Protocol behavior was checked against the Tailscale source at https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go . Its TLS-terminated generic TCP mode advertises no application protocol, so the documented route forwards TCP to a TLS-enabled Python gateway. Certificate instructions https://tailscale.com/docs/reference/tailscale-cli#cert .
