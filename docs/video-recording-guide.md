# Commonplace recording runbook

For the simpler one-window recording setup, use [RECORDING-QUICK-START.md](RECORDING-QUICK-START.md) and [recording-read-along.txt](recording-read-along.txt). The `recording-kit` folder contains numbered launchers. Its controls menu runs the commands automatically; the separate-terminal instructions below remain available as an advanced alternative.

For Aryan and Reshma, sitting together at one laptop. Target edited duration: **9:00**, with **4:30 allocated to each person**. The script has six turns each and nearly the same number of spoken words. A natural reading is better than forcing the timestamps. Keep the final export between the assignment's 5 and 10 minutes. The timestamps exclude idle waits that you cut later.

## What remains before November 18

The browser editor, login, version history, local AI integration, Raft implementation, slides, README and source ZIP are prepared. The browser release passed 149 tests on Windows/Linux, plus process-level failure/recovery verification and a fresh-archive test. The actual submission has not been made.

Remaining work:

1. Start the host and rehearse this exact recording sequence once.
2. Record and edit the 5–10 minute demonstration.
3. Each registered team member completes their own contribution/learning reflection with actual work and evidence. The script's speaking split is a filming arrangement; reflections describe actual contributions.
4. Confirm the PPT and reflection carry the correct team details, then upload the current code ZIP, video Drive link, PPT and reflection through the course form. Check evaluator access to the video and retain the submission confirmation.
5. Continue viva preparation for the November 24 presentation. The PPT is needed for the November 18 submission even though the presentation is later.

Treat November 18 as the deadline. The notice's November 20 medical-emergency extension is conditional.

The current host voters were stopped when this runbook was prepared. Start them before testing the editor. The real model weights are already present on this computer.

## Filming arrangement

- Sit side by side, both facing the webcam. Place the laptop so both heads and shoulders fit, at similar distances from the microphone. Raise the camera toward eye level if practical and use light from in front of you.
- Use a small rectangular webcam overlay, around **320×180** in a 1920×1080 recording. Do not reserve a screen column.
- Start with the overlay bottom-left. Move it to upper-left for the browser System status shot so its button and right-hand status panel remain visible. Put it bottom-right for full-screen terminal shots. Make these moves between sections and cut the adjustment footage.
- Aryan can remain the main browser operator. Reshma keeps the script and terminal commands ready. Hand the mouse to the other person when useful; the even split applies to speaking, not the number of clicks. Do not talk over each other.
- Keep the script on a phone or on paper, outside the captured display. Avoid reading long passages while staring down. Practise one paragraph, look up, then speak naturally.

## OBS setup, step by step

1. Install OBS from https://obsproject.com/download if needed. Start its Auto-Configuration Wizard and choose recording as your use case.
2. Use 30 fps. If the laptop display is 1920×1080, use that for base and output resolution. Otherwise use the display's native resolution rather than enlarging a low-resolution screen. Make a short test before choosing the final output.
3. In Settings → Output, choose a recording folder you can find, **MKV** format, and a suitable recording-quality preset such as High Quality. If a hardware H.264 encoder is offered, prefer it to leave CPU capacity for the language model. Do not stream.
4. Add a scene named **Camera**. Add **Video Capture Device**, select the laptop webcam, and frame both people. Choose the microphone explicitly under Settings → Audio. Use one microphone input; leave the webcam's optional custom audio off unless you intend to use it instead.
5. Add a scene named **Demo**. Add **Display Capture** for the laptop display. Add the webcam using **Add Existing**, place it above Display Capture in the source list, and resize it to the small rectangle. Display Capture records the browser and terminals as you switch between them. Keep the microphone active in both scenes.
6. Mute Desktop Audio if you do not need computer sounds. Check that both voices move the microphone meter and that loud speech does not hit red. Avoid capturing the same microphone twice.
7. In Settings → Hotkeys, assign and test scene switches such as Ctrl+Alt+1 for Camera and Ctrl+Alt+2 for Demo, plus a recording shortcut that does not conflict with the application. Or switch scenes manually and trim the transitions.
8. Close personal tabs and enable Do Not Disturb. Plug in the laptop and prevent sleep for the recording. Keep OBS in the background after starting; the first and last screen-switching seconds can be cut.
9. Make a **60–90 second test recording** with both people speaking, the browser visible, a terminal command, and a real AI request. Play it back. Check voice balance, readable text, webcam framing, screen capture and smoothness. If encoding lags, reduce recording load and retest before the main take.

OBS's official guides support the scene/source, audio and test workflow: https://obsproject.com/kb/quick-start-guide/ and https://obsproject.com/kb/sources-guide . MKV and built-in MP4 remuxing are covered at https://obsproject.com/kb/standard-recording-output-guide . The small-overlay arrangement above is a suggested layout for this demo.

## Prepare the project before recording

Use the installed folder:

```powershell
Set-Location 'C:\Users\aryan\Documents\Codex\2026-11-17\i-h\outputs\collab-platform'
```

1. Double-click **Start browser demo.cmd** for reliable local recording. It starts the same Python gateway, three voters, browser edge and installed CPU model. Keep its launcher window open.
2. If you also want the public editor online during the recording, use **Start online demo.cmd instead**. Do not start both launchers. The online launcher also serves http://localhost:8080. It requires this host's authenticated GitHub CLI for endpoint publication. If internet/tunnel startup fails, use the local launcher and the public-link alternative line later in this guide.
3. Open **two separate browser windows** at http://localhost:8080. Put Alice on the left and Bob on the right. Separate windows are needed to show both views at once. Open both on the sign-in screen before the take. You may use two normal windows; the application isolates sessions per tab.
4. Prepare a third browser tab for the README diagram: https://github.com/aryan1078/commonplace#how-a-save-works . Prepare another for https://aryan1078.github.io/commonplace/ and the repository's Actions page.
5. Open a separate document named **Video rehearsal 01** for preflight. Sign in, save a sentence, and verify that Writing assistant says **Local CPU language model**. Warm it with a grammar request, a concise rewrite and a summary. A cold model may take a while. Do not record a claim of real local AI if the label says demo responses.
6. Sign out of the rehearsal sessions and return both demo windows to the login screen. Do not use Video Demo 01 for preflight; save that fresh document for the take. Keep the model/service processes running.
7. Have **DEMO-NOTES.txt** ready to copy. It deliberately contains “We has” for the grammar demonstration. It is fictional sample meeting content, not a statement of actual team contributions.
8. Open two PowerShell windows/tabs named conceptually **A: controls** and **B: recovery**, both in the project folder. A runs status, the crash command and the acceptance test. B is reserved for the restarted voter and must remain open after recovery.
9. In A, run a pre-recording test and keep its output:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -o addopts= -q | Tee-Object -FilePath .\logs\recording-tests.txt
```

Confirm the test summary passes. The plugin setting avoids unrelated globally installed pytest plugins on this host. This remains the same project test suite. Use the actual count displayed if the code has changed since this guide.

10. Increase terminal font size until the status table is readable in a 10-second test capture. Use a maximized browser for AI/history/status shots; use side-by-side windows only for propagation shots.
11. Rehearse the failure and recovery once, following the cleanup instructions below. Then start a fresh take with all three voters running and a new demo document. Read VIVA-GUIDE sections 1–8 and 20 before filming so you can explain the lines rather than only recite them.

## Exact commands during the recording

Create the document with the UI name **Video Demo 01**. Its internal ID is **video-demo-01**. All commands below use that ID. For another take, use Video Demo 02 and change the `--doc` argument consistently. Never delete a voter data directory to reset a take.

**Terminal A — show the actual current roles and document agreement:**

```powershell
.\.venv\Scripts\python.exe scripts/demo_control.py status --doc video-demo-01
```

**Terminal A — deliberately stop the currently elected leader:**

```powershell
.\.venv\Scripts\python.exe scripts/demo_control.py fail-leader --doc video-demo-01
```

The helper queries live Raft status, requires three reachable voters and one leader, checks that the listening process belongs to this project's docnode, records its original address/peers/data directory, and stops only that voter. It then shows the replacement in a higher term. It does not choose a fixed node number or erase data.

**Terminal B — recover that voter on the original disk:**

```powershell
.\.venv\Scripts\python.exe scripts/demo_control.py recover
```

Leave B running. In A, repeat the status command until all three document versions and digests match. The recovered voter can initially lag. A status table is a series of local observations, not an atomic snapshot of every index in the cluster.

**Terminal A — independent acceptance test with real process failures:**

```powershell
.\.venv\Scripts\python.exe scripts/verify_cluster.py
```

This harness uses temporary test disks and separate available ports, preserving the visible editor document. Its AI is stubbed so the workload isolates consensus/recovery. The editor's earlier AI shots use the real CPU model. The final JSON report is printed only after the assertions complete. Do not announce success if there is a traceback or failed check.

**Terminal A — show the pre-recording test summary:**

```powershell
Get-Content .\logs\recording-tests.txt -Tail 5
```

Do not kill every Python process. Do not stop the gateway, AI server or browser edge during the one-voter failure shot.

## Sample text and the three live edits

Paste the contents of the companion **DEMO-NOTES.txt** into Alice's new document, then wait for All changes saved.

Append as Alice:

```text
Alice: We will demonstrate a leader failure.
```

Append as Bob:

```text
Bob: We will check recovery on the original disks.
```

After the leader is stopped, append as Alice:

```text
Saved after leader failure.
```

For the rewrite, select this exact sentence from the sample:

```text
The consensus mechanism makes sure that all of the servers are able to maintain the same agreed order for changes that are made to the document.
```

For continuation, put the caret after **Next steps:** and click Continue writing. Leave the continuation unapplied to keep the notes concise. Grammar and a valid concise rewrite are the accepted AI edits demonstrated in the recording.

## Spoken script and screen cues

The blocks below contain the entire spoken script. Read only the quoted paragraphs. Screen cues and cut instructions are for the operators. Around 9 minutes is the edited target, with 4:30 allocated to each person. Leave the same real cluster running across the blocks.

### 1. 00:00–00:45 — Aryan — Introduce the demonstration

**Show and do:** Start with both people visible in the Camera scene. After the first two sentences, switch to the editor sign-in page with the small webcam overlay. Do not introduce the slides as the main demonstration.

**Say:**

> Hi, I’m Aryan, and this is Reshma. We are demonstrating Commonplace, our Advanced Operating Systems collaboration project. Users sign in, edit a shared document, see other users’ changes, and review its history. The main systems problem is keeping an agreed document history when a server crashes. We address that with three document replicas using Raft. We will show the complete save path, live editing, local writing assistance, leader failure, and recovery. This recording uses independent Python server processes with separate data directories on one laptop.

### 2. 00:45–01:30 — Reshma — Architecture and communication

**Show and do:** Show the README architecture diagram at a readable size. Point in order to Browser, Python edge, Gateway, leader/followers, and Assist. Keep the diagram visible while explaining the three voters and separate AI service.

**Say:**

> Here is the architecture. The browser uses gRPC-Web to reach a Python edge. The edge calls our authenticated gateway using native gRPC. The gateway routes document requests to the elected Raft leader and writing requests to the separate Assist service. Assist runs Qwen2.5-1.5B-Instruct locally on the CPU. Three document voters each own a SQLite log. These form five logical roles: the AI server, three voters, and the gateway with the client interface. All backend services and the consensus implementation are Python.

### 3. 01:30–02:15 — Aryan — Two accounts and live propagation

**Show and do:** Show two independent browser windows side by side. Sign in as Alice and Bob, create Video Demo 01 as Alice, paste the sample notes, wait for All changes saved, refresh Bob’s document list and open the same document. Add the Alice line below and show it arrive for Bob. Point at both presence avatars.

**Say:**

> I’ll sign in as Alice in this window and Bob in the other. These are two independent authenticated sessions, even though we are recording on one laptop. The gateway verifies password hashes and issues a session token. It also supplies the author identity for every edit. Alice now creates Video Demo 01 and enters our meeting notes. Bob opens the same document. When Alice adds this line, it appears for Bob, and both users are visible in the presence indicators. The saved label means the edit was acknowledged by the server.

### 4. 02:15–03:00 — Reshma — Revisions, conflict handling, and authors

**Show and do:** In Bob’s window append the Bob line. Wait for All changes saved and for Alice to receive it. Maximize Alice’s window and open History. Point to the newer version, Saved by Bob, and the earlier Saved by Alice. Explain stale revisions as a mechanism; the later concurrent workload provides overlap evidence.

**Say:**

> Each document has a revision number. A client sends changed text ranges together with the revision it started from and an operation ID. If another edit has already advanced that revision, the stale client fetches the missing history, adjusts its positions, and retries. The operation ID prevents a retry from applying the same operation twice. History records the accepted edits and their authenticated authors. I’ll add Bob’s line and open history to show both authors. This browser example shows propagation; the later workload tests overlapping requests from eight clients.

### 5. 03:00–03:50 — Aryan — Grammar, applying a suggestion, and continuation

**Show and do:** Open Writing assistant. Point to Local CPU language model. Click Check grammar, wait, show We has → We have, and apply that specific suggestion. Show the changed sentence and saved state; briefly open History to show the new version. Return to the assistant, put the caret after Next steps:, click Continue writing, and show the returned suggestion. Leave the continuation unapplied.

**Say:**

> The writing assistant is a separate service, rather than part of the consensus algorithm. First, we ask it to check this document. It proposes changing ‘We has’ to ‘We have’. We review that replacement before applying it. Grammar combines model output with explicit checks for common mistakes. Applying the suggestion creates another ordinary, replicated edit, which we can see in history. Next, we place the cursor after ‘Next steps’ and request a continuation. The generated text is a suggestion. It does not silently overwrite the document.

### 6. 03:50–04:40 — Reshma — Context-aware rewriting and summary

**Show and do:** Select the exact long sentence from the sample. Select Make it concise and click Rewrite selection. Show original and proposed replacement; apply only if the meaning is preserved. Click Summarize, wait for output, then point to Alice/Bob’s tasks and the Based on version label. Do not read the entire model answer aloud.

**Say:**

> For rewriting, we select this long sentence and choose ‘Make it concise’. The request includes the selection and relevant document context. We review the returned replacement and apply it only if it preserves the meaning. For summarization, the assistant receives the current document and returns its main points. The panel identifies the document version used. Suggestions carry an anchor containing the document, revision, and text range. Before acceptance, the client checks that the intended passage still matches. The model is pretrained and locally hosted. We use context-aware prompts; its answers still need review.

### 7. 04:40–05:25 — Aryan — The normal Raft save path

**Show and do:** Move the webcam out of the bottom-left system controls. Open System status. Point to the actual leader and its term, then commit/applied indices and document version. Switch briefly to the readable status command. Keep all three voters running. Use the real values you see; do not expect fixed node numbers or term values.

**Say:**

> Now follow a normal save. The browser keeps a local draft, and autosave sends changes through the authenticated gateway. The elected leader appends a command and sends AppendEntries RPCs to its followers. For a new entry in its current term, it commits after a majority has durably recorded it. In our three-voter cluster, that majority is two. Replicas then apply committed commands in order and update the clients. System status shows the leader, election term, commit index, applied index, and document revision. An entry stored on one disk is not yet a committed save.

### 8. 05:25–06:10 — Reshma — Kill the elected leader and keep editing

**Show and do:** Terminal A: run fail-leader. Keep the real stop/election sequence in the recording. Show the stopped address as unreachable and the replacement leader in a higher term. Return to Alice, append Saved after leader failure., wait for All changes saved, then show the line in Bob’s window. The narration’s result sentences are spoken only after those results appear.

**Say:**

> We will now stop the document server that is actually leader. The browser, gateway and other two voters keep running. After missing heartbeats, a follower becomes a candidate, increments its term and sends RequestVote RPCs. A candidate needs a majority, and voters check that its log is sufficiently up to date. Randomized timeouts reduce split votes. Here the failed voter is unreachable, and a new leader appears in a higher term. We can now save another line and see it in Bob’s window. Two survivors still form a majority of the original three voters.

### 9. 06:10–06:55 — Aryan — Restart on the original disk and verify catch-up

**Show and do:** Terminal B: run recover and leave that terminal open. Cut only the startup wait if needed. Terminal A: run status again, repeating until the helper says All three replicas agree. Point to matching VERSION and TEXT DIGEST values and show the Saved after leader failure. line remains in the document.

**Say:**

> We now restart the failed voter using its original address, membership configuration, and data directory. It replays its persisted committed log and catches up with the current leader. It may temporarily show an older revision while missing entries arrive. Here all three voters report the same document revision and text digest, including the edit made while one voter was down. A matching digest checks agreement of the document text. Commit indices can briefly differ between diagnostic reads, because these status requests observe each replica separately while the system is running.

### 10. 06:55–07:40 — Reshma — Concurrent workload, full disk restart, and majority loss

**Show and do:** Terminal A: run scripts/verify_cluster.py live and keep its actual final report. A silent test wait may be shortened with a caption. Point to final revision 200, history replay matches, client copies identical, and the checks for restart, duplicates, and majority loss. Do not substitute the older saved report for this run or claim its timing as today’s timing.

**Say:**

> This verification script launches a separate test cluster, so it does not overwrite our visible demo document. Eight clients attempt twenty-five edits each while the elected leader is killed. The report checks two hundred accepted edits, matching history replay, and identical client copies. It then restarts all voters on their existing test disks, checks duplicate suppression again, and verifies that losing a majority prevents fresh authoritative reads and writes. This harness uses a stub AI service to isolate recovery testing. The writing assistance we showed earlier used the real local model.

### 11. 07:40–08:20 — Aryan — Tests, source, and browser hosting

**Show and do:** Briefly show the current test summary and green Windows/Linux CI, then the README diagram. Open the public editor in a prepared tab, sign in and open Video Demo 01 if the public connection works. Show the saved-after-failure line. If public internet fails, use the explicit alternative line in the notes and keep the local demonstration.

**Say:**

> The repository contains the Python services, protobuf contracts, setup instructions, tests, and measured results. The release passed one hundred and forty-nine automated tests on Windows and Linux. We also tested a fresh source archive. Visitors can use the published browser editor without installing Python. GitHub Pages serves its static interface, while a free HTTPS tunnel connects to the host’s Python edge. The laptop supplies the model, compute, and durable storage. The public demo therefore needs the host awake and online. Local and LAN browser modes provide an alternative.

### 12. 08:20–09:00 — Reshma — Limits and conclusion

**Show and do:** Show the recovered three-voter status and the saved document. Then switch to Camera for the last two sentences. Both look at the lens. Leave two seconds of silence before stopping the recording.

**Say:**

> The key result is that accepted document edits survive a voter crash and remain consistent after recovery. The system also preserves version history, author identity, and duplicate protection across voter restarts. Our current limits are fixed membership, growing logs without compaction, and memory-only gateway and browser sessions. Three processes on one laptop share that laptop’s failure domain. Separate physical machines would be needed for host-failure tolerance. Future work includes snapshots, log compaction, and stronger gateway availability. That completes our demonstration of collaboration, gRPC communication, and Raft recovery. Thank you.

## Result-dependent lines and editing rules

- Say “Here the replacement leader…” only after the higher-term leader is visible. Say “Here all three voters…” only after they agree. The exact leader address, term and revisions vary between runs.
- If a rewrite changes the meaning, do not apply it. Say: **“This replacement changes the meaning, so we will leave the original unchanged. Suggestions remain under user control.”** Then continue to the summary.
- If the public connection is unavailable in block 11, replace the demonstration claim with: **“The public frontend is published, but the free tunnel is unavailable at the moment. This recording uses the local browser connection to the same Python services.”** Do not show an offline page as a working remote edit.
- If the AI answer invents a fact, say that it needs review or use another clean take. Do not describe an incorrect answer as correct. A model error does not mean the consensus layer failed.
- Keep input, request, and result in order. Leave about a second after clicking an AI tool, cut the middle of a long silent wait, then keep the actual output appearing. A small caption such as **“Inference wait shortened”** makes the edit clear.
- Keep the live leader-stop/election sequence intact where practical. It is short and is the strongest evidence in the video. Cut long recovery startup waits or test execution waits with a caption, preserving the command and final result.
- Do not speed up the failure shot and then quote it as a measured recovery time. The existing 1.438-second result belongs to an earlier measured run. If you mention time in this video, use the value reported by the run you actually recorded and describe it as one observation.
- The manual browser edits show live propagation and author history. The later eight-client workload supplies the evidence for overlapping edits. One person taking turns between two windows alone is not a simultaneous-concurrency stress test.
- The independent acceptance test's full disk restart verifies its own test documents. Do not claim that the on-screen Video Demo 01 document was fully restarted by that separate test.
- Keep both voices at a natural pace. Target 9:00, then allow a little flexibility while staying below 10:00. Trim idle waits, cursor wandering and repeated setup, not the evidence that supports the claims.

## Raft details aligned with the supplied course material

The script was checked against **Raft_mainPaper (1).pdf**, **RAFT_LeaderElection_21Oct.pdf**, and the scanned **Raft_example_print.pdf**. The printed handout reuses the lecture's three-voter Put examples. Useful study locations:

| Topic | Course source | What to say for this implementation |
|---|---|---|
| Follower, candidate, leader; terms and votes | Lecture PDF pages 12–14; paper section 5.2 | Missing heartbeats trigger a timeout; a candidate increments its term and seeks a majority. Timeouts are randomized. A voter grants at most one vote per term and persists it. Log freshness compares the last log term before the last index. |
| Normal log replication | Lecture pages 14–19; handout pages 3–6; paper sections 5.3 and 5.4.2 | A new current-term entry can be committed after durable replication to a majority. Older entries are not made safe merely by counting their copies; a current-term commitment establishes the relevant prefix. |
| Majority during failure | Lecture pages 20–22; paper sections 5.2–5.4 | Two of the configured three voters form a majority. After two voter failures, the remaining one does not redefine the cluster as a one-voter majority. |
| Returning voter and log repair | Lecture pages 23–24; handout pages 7–9 | Restart on the original data directory. Repair may replace conflicting uncommitted entries; do not say that acknowledged committed history is discarded. |
| Duplicate requests and fresh reads | Paper section 8 | Operation IDs are tracked by the replicated state machine. A lost reply must not cause duplicate application. This release uses committed no-op barriers for authoritative reads. |
| Persistent state | Paper Figure 2; lecture page 14 | Term, vote and log are the paper's required persistent state. Our implementation additionally persists commit metadata for recovery; do not claim the paper requires every implementation to persist commitIndex. |

The simplified initial crash example in the printed handout motivates the need for consensus. Do not treat acknowledgment from only the leader's private memory/disk as the completed safe Raft protocol. Show the implemented majority acknowledgment instead.

The other supplied files cover MapReduce, HDFS, Chord, general election algorithms, and a multi-agent exploration leader-election application. They are background, not extra mechanisms implemented by Commonplace. Do not claim that this project implements their algorithms. Avoid adding them to the nine-minute video merely to mention more topics.

## Clean up after recording

1. Stop OBS recording and wait for the file to finish saving.
2. In **Terminal B**, press **Ctrl+C** to stop the manually recovered voter. This voter was started in B, so keep track of it explicitly.
3. Run **Stop demo.cmd** to stop the launcher-owned services. Keep the three data directories.
4. If you want the public editor available afterward, run **Start online demo.cmd** again. This fresh start returns all three voters to normal launcher ownership. Verify all three with the status command.
5. Keep the original MKV. In OBS use **File → Remux Recordings** to create an MP4 for editing/upload. Remuxing changes the container; it does not perform your cuts.
6. Export the final edited MP4. Watch it from beginning to end, including after upload. Confirm: 5–10 minutes, both speakers audible, readable text, real AI label, live stop/new leader, successful edit with one voter down, original-disk recovery, current test results, and honest deployment limitations.
7. Upload to Drive and grant evaluator access as required by the submission instructions. Verify access using the intended viewer access or a signed-out/private window if the sharing setting is link-based. Avoid granting edit permission unnecessarily.
8. Complete the individual reflections, verify team details in the deck, attach the current source ZIP/PPT/reflection/video link in the course form, and retain its confirmation. The upload and course submission are still user actions to complete.
