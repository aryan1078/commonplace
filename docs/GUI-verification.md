# Native GUI observations

The graphical client was run as a Windows desktop app, connected to actual Python gRPC services and three durable voters.

1. An incorrect password produced the generic incorrect-credentials message.
2. Alice signed in and created Project Meeting Notes.
3. Pasted note text autosaved as version 2.
4. The writing tools opened and the system panel displayed three replica roles and progress.
5. After restarting the local stack on the same disks, the document remained available.
6. The installed release displayed Local CPU language model in the assistant.
7. Grammar offered We has → We have with a subject-verb agreement explanation.
8. Applying it produced version 3, the corrected document text and Suggestion applied and saved.

The common grammar correction is supplied by an explicit check supplementing the model. The model also runs context-aware rewriting, summary and Q&A. Generated content still requires review.

The view layer is HTML/CSS/JavaScript inside a native Python webview. Authentication, editing, merging, networking, replication and inference services are Python. Remote calls use gRPC.
