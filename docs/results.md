# Verified graphical release, November 17, 2026

Python 3.11.9 on Windows. Independent Python server processes with three independent SQLite data directories.

- 147 automated tests passed after the graphical client, authenticated diagnostics, persistent edit retries and common grammar checks were added.
- Native GUI verified for rejected login, successful login, document creation, autosave, history access and replica status.
- The installed release loaded Qwen2.5-1.5B-Instruct locally on CPU with bfloat16 weights. Its grammar path returned an anchored We has → We have suggestion. Applying it through the GUI produced document version 3 and the saved indicator.
- Eight concurrent clients completed 200 edits during an actual elected-leader kill. History replay matched and all live copies agreed. The independent joined editor's next accepted write took 1.438 seconds after the kill. The workload took 11.3 seconds with 898 attempts including rebases/retries. These are one observed run.
- Returning voter caught up, all replica digests agreed, and full restart on the same disks preserved documents and duplicate tracking.
- Loss of majority prevented fresh authoritative reads and writes. The partition test repaired a conflicting uncommitted suffix after healing.
- A separate verified-certificate TLS gateway passed login and document reads through DesktopSession.
- The source ZIP was extracted separately, protobuf files regenerated, and all 147 tests passed again in 19.31 seconds. Docker and separate physical-machine deployment require rehearsal.
- Public sharing has been researched and documented. No public endpoint or cloud account was provisioned.

See cluster-verification.json, test-results.txt, real-ai-transcript.txt, tls-verification.txt and GUI-verification.md for the evidence and its scope.
