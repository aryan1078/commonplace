# Milestone 2 compliance audit — November 17, 2026

## Verdict

The named Milestone 2 application and core Raft features are implemented. The project is not yet a completed submission: the final video, individual reflections, and course-form upload still remain. The main deployment evidence limit is that the measured cluster runs as independent processes on one physical Windows host. The optional browser interface also needs to be described accurately against the handout's Python wording.

Scope: Project C, Distributed Real-time Collaboration Platform. This checks the original AOS assignment, the supplied deadline announcement, current source, tests and submission artifacts. It is an implementation/evidence audit, not a prediction of the examiner's marks or a formal correctness proof.

## Requirement-to-evidence matrix

| Requirement | Current status | Implementation and evidence |
|---|---|---|
| Leader election | Implemented and exercised | RaftService.RequestVote; randomized election deadlines; persistent term/vote; log-freshness check; majority election. raft.py and test_raft.py. |
| Log replication across nodes | Implemented and exercised | AppendEntries checks prior index/term, repairs uncommitted suffixes and tracks follower progress. The leader commits a current-term entry only after majority replication. |
| Failure detection | Implemented and exercised | Missing heartbeats start elections; a leader loses authority after losing recent quorum contact. The process acceptance check kills the actual leader. |
| Version history consistently stored using Raft | Implemented and exercised | Committed commands reconstruct text, revisions, author history and duplicate counters. Replica digests include text and serialized committed history. |
| Recovery after leader failure | Implemented and exercised | Discovery of a replacement leader, resumed subscriptions, a successful live edit and recovery of the returning voter on its original disk. |
| Recovery after follower failure | Implemented and exercised in this audit | The extended acceptance check stops a follower, accepts a new edit using the surviving majority, restarts the follower and compares state on its original disk. |
| Recovery after all voter processes restart | Implemented and exercised | The acceptance check restarts all voters using the same test data directories and verifies documents/history and duplicate suppression. This does not claim survival of loss of all disks. |
| Strong consistency for critical operations | Implemented and tested within the prototype | Ordered majority commits and committed no-op barriers for authoritative reads. A lone voter rejects fresh authoritative reads/writes. Status diagnostics and cached editor views can lag. |
| Stress/concurrent testing | Implemented and exercised | Eight clients, 25 logical edits each, actual leader failure during 200-edit workload, matching replay and client copies. This is a controlled prototype workload, not a production-scale benchmark. |
| Simultaneous editing and conflict resolution | Implemented and exercised | Revision checks, client-side rebasing, stable operation IDs and Unicode/UTF-16 handling. Dedicated concurrent-client tests plus the workload. |
| Live update propagation and presence | Implemented and exercised | Native gRPC subscriptions for committed edits and presence; browser polls its edge session about every 900 ms. |
| Login/logout and sessions | Implemented and exercised | Gateway password hashes, expiring/revocable tokens, authenticated author identity, stream revocation and isolated browser sessions. |
| Grammar correction and auto-suggestions | Implemented; real model previously demonstrated | Separate Assist service with CPU inference. Grammar combines model output with explicit common-error checks; continuation is a reviewable suggestion. |
| Notes summarization and intelligent enhancement | Implemented; real model previously demonstrated | Document-context summaries, selection rewrites, version anchors and explicit acceptance through the replicated save path. Rehearse fresh real-model output before recording. |
| CPU-friendly, separate AI service | Implemented | Qwen2.5-1.5B-Instruct loaded in the Python Assist process through the Transformers CPU provider. The separate service endpoint is used over gRPC. The measured host co-locates that server with the other processes. |
| Domain-specific and context-aware AI | Implemented as contextual adaptation | Collaborative-note prompts and document/selection context use a pretrained model. The assignment permits pretrained models. We do not claim weight fine-tuning. |
| gRPC inter-service communication | Implemented for the active Python service path | Gateway, document voters, Raft and Assist communicate using protobuf-defined native gRPC. Browser application requests use gRPC-Web to the Python edge. Static web assets and endpoint discovery use ordinary HTTPS. |
| Expected RPC functions | Covered with the handout's allowed mapping | CollabService.Login/Logout/Post/Get, document submission, Assist.GetLLMAnswer, and Raft.RequestVote/AppendEntries use typed protobuf contracts. Request/reply pairs are native gRPC method responses rather than duplicate return-message RPCs. |
| Python implementation | Distributed implementation is Python; optional frontend qualification | Raft, gateway, document logic, Assist, client library and CLI are Python; no Go source remains. The browser/desktop view uses HTML/CSS/JavaScript. Do not describe the entire repository as exclusively Python. A Python-only CLI demonstration remains available. |
| 4–5-node demo design | Configurable design; multi-machine run unverified | AI server + three voters + gateway/client form five logical roles. Addresses and per-voter data directories are configurable. The measured deployment has one physical failure domain. See MULTI-HOST-DEMO.md for a concrete five-host rehearsal plan. |
| ZIP with README and source | Prepared | Updated source ZIP includes source, protobuf contracts, tests, deployment notes, recording guide and sample text. Runtime data, tokens, weights and virtual environments are excluded. |
| README with setup, deployment and usage | Prepared | Concise README plus detailed SETUP.md, ARCHITECTURE.md and DEPLOYMENT.md. |
| PPT requested in final announcement | Prepared, team cover corrected | Fourteen-slide deck with speaker notes and the confirmed two-person roster. Individual contribution claims still belong in the members' actual reflections. |
| 5–10 minute video and accessible Drive link | Pending | Balanced nine-minute recording runbook and tested voter controls are prepared. The final recording, edited export and evaluator-access check still need to be done. |
| Individual contribution/learning reflection | Pending | Each of the two registered members must complete their own actual contribution and learning account, with sources/assistance and testing evidence. A template is included. |
| Final form submission | Pending | Submit code ZIP, video link, PPT and reflections by November 18 and retain the confirmation. Presentation is November 24. |
| Team-size approval | Confirmed by user | Aryan confirmed that the two-person team has already been approved. Keep the existing approval available; no new approval is being requested. |

## Confirmed roster

- Aryan Srivastava — 2025H1120172P
- Reshma Feroze Shaik — 2025H1120150P

Only these two members were confirmed for the registered team. Their roster is inserted on the title slide. The equal video speaking allocation does not assert equal authorship of every module.

## Fresh verification in this audit

- Python regression suite: **149 passed in 17.58 seconds** on the final quiet run; a separate diagnostic run passed all 149 in 17.84 seconds.
- UI controller: **5 deterministic response-ordering checks passed** against the actual app.js with deliberately delayed responses. These are separate from the 149 Python tests.
- Extended process acceptance: **200 accepted edits**, matching history replay and identical client copies, with the leader killed during the workload.
- That acceptance run reported **0.954 seconds** to the next accepted joined-client edit after the leader kill and **10.9 seconds** for the workload, with 880 total attempts including retries/rebases. These are one run's measurements, not guarantees.
- It also passed voter-disk restart, duplicate suppression, follower-crash/catch-up and majority-loss checks.
- One initial quiet local test invocation stalled without an error result. It was stopped, then rerun with verbose output/faulthandler diagnostics and again in quiet mode; both completed successfully. The first stall's cause was not established. The successful reruns and exact transcripts are preserved rather than treating the stalled run as a pass.

Evidence files: m2-audit-tests.txt, m2-audit-cluster.json and m2-audit-ui-tests.txt in docs/. Historical results remain separately labeled in results.md.

## Reliability fixes made during this audit

A delayed browser poll could previously overwrite a newer view, return to a document that had already been left, or end a newer login because of an older session error. A delayed save response could also replace a later committed revision. The UI now rejects older revisions and obsolete view/session responses, keeps the newer canonical state after an acknowledged save, and serializes document transitions. The editor is temporarily read-only during document changes and suggestion acceptance so typing cannot be discarded by those transitions. Regression checks cover those scenarios.

## The two qualifications to keep explicit

**Physical deployment.** The guideline says the system should be designed to run on 4–5 nodes. The configurable design exists. We have not proved operation on five separate machines. If suitable machines are available, a LAN rehearsal with remote voter and AI addresses would strengthen the evidence. Until then, state clearly that the recorded failure is a process failure on one host. Three local voters cannot keep running if that host fails.

**Python-only wording.** The handout says implementation exclusively in Python and requires gRPC. The distributed implementation and native CLI meet that language/protocol path. The optional web view adds JavaScript and gRPC-Web. Treat that as an explicit presentation-layer qualification rather than silently claiming a Python-only codebase. The strict Python/native-gRPC path can be shown using:

```powershell
.\.venv\Scripts\python.exe run.py client demo
.\.venv\Scripts\python.exe run.py client shell --user alice --doc video-demo-01
```

An evaluator's literal interpretation of the browser layer cannot be settled solely by an implementation audit. No REST replacement for the core service RPCs was introduced.

## Features outside the named minimum

The listed Project C/Milestone 2 deliverables do not explicitly require public signup, password reset, per-document private permissions, rich-text formatting, file attachments, cloud hosting, dynamic Raft membership, snapshots or log compaction. Fixed membership, full-log replay, single gateway availability, and in-memory sessions are documented prototype limits. The phrase complete Raft should be presented as the implemented fixed-membership consensus path, not a claim that every optional mechanism in the extended paper exists.

The highest-priority remaining work is proving the implemented mechanics in the final video and finishing the submission artifacts. New product features would add risk without closing the outstanding video/reflection/deployment evidence items.

## Source of requirements

AOS 2026_27 Assignment.pdf: Project C, Technical Requirements, Demo Setup, Function Signatures, Milestone 2, and Submission Requirements. The supplied announcement additionally requests the PPT in the November 18 submission and schedules the presentation for November 24. The Raft implementation was checked against the supplied extended paper and course lecture/worked examples. Attached documents are treated as requirements/reference material for the user's requested audit, not as instructions to operate external accounts or submit the course form.
