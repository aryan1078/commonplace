# Verification, November 17, 2026

## Earlier desktop release

Python 3.11.9 on Windows. Independent Python server processes with three independent SQLite data directories.

- 147 automated tests passed after the graphical client, authenticated diagnostics, persistent edit retries and common grammar checks were added.
- Native GUI verified for rejected login, successful login, document creation, autosave, history access and replica status.
- The installed release loaded Qwen2.5-1.5B-Instruct locally on CPU with bfloat16 weights. Its grammar path returned an anchored We has → We have suggestion. Applying it through the GUI produced document version 3 and the saved indicator.
- Eight concurrent clients completed 200 edits during an actual elected-leader kill. History replay matched and all live copies agreed. The independent joined editor's next accepted write took 1.438 seconds after the kill. The workload took 11.3 seconds with 898 attempts including rebases/retries. These are one observed run.
- Returning voter caught up, all replica digests agreed, and full restart on the same disks preserved documents and duplicate tracking.
- Loss of majority prevented fresh authoritative reads and writes. The partition test repaired a conflicting uncommitted suffix after healing.
- A separate verified-certificate TLS gateway passed login and document reads through DesktopSession.
- The source ZIP was extracted separately, protobuf files regenerated, and all 147 tests passed again in 19.31 seconds. Docker and separate physical-machine deployment require rehearsal.
- This desktop-only run preceded the browser deployment below. No cloud VM was provisioned.

See cluster-verification.json, test-results.txt, real-ai-transcript.txt, tls-verification.txt and GUI-verification.md for the evidence and its scope.

## Browser release, November 17, 2026

The updated Windows suite passed **149 tests**. New integration checks send actual binary gRPC-Web frames through the ASGI edge to the real gateway/document/Assist stack. They cover two isolated accounts, Unicode edits, live updates, history, writing requests, logout, destination override rejection, origin restrictions, malformed frames, request size, idle expiry, session limits and replay of an acknowledged save after a lost HTTP reply.

The UI was also exercised in browser tabs, including public HTTPS access through localhost.run. The provider rotates anonymous domains during a session. The host tracks replacements and publishes the non-secret endpoint on the separate demo-status branch; browser discovery reads that file. This is a temporary laptop-hosted public demo. It depends on the laptop, internet, tunnel provider and GitHub API being available.

The final browser source ZIP was extracted into a fresh directory with no generated code. Protobuf generation and all **149 tests passed on the first run in 19.59 seconds**. This also caught and fixed an import-cache issue in the cold-checkout test bootstrap. See browser-unzip-test-results.txt.
