---
name: root-cause
description: Determine the root cause of one Crashlytics crash/ANR from its crashed frames, breadcrumbs and the located source code. Used by sentinel.py pull --llm.
---

# Root cause

Follow Firebase's own investigation procedure, applied to the MyZesty native engine:

1. Read the crashed frames top-down and the located function bodies. Name the exact line that faults (a null/OOB dereference, a wait without timeout, a use-after-free) and why.
2. Read the breadcrumbs (newest first) and reconstruct the 2-3 user/engine actions that led there. The engine logs `file: X, line: N` for every message handler; failing handlers log `Message cancelled/failed for ID: MsgX - ERROR | ...`.
3. Compare the faulting function with its siblings in the same file: a missing guard that siblings have is a strong signal.
4. List at most 3 candidate causes, critique each against the evidence, pick one. If the evidence is insufficient, say exactly what is missing (e.g. unsymbolized frames) instead of guessing.

Output, in this order, plain markdown, under 250 words:
**Cause** (one paragraph, cite file:line) · **Trigger** (the action sequence from breadcrumbs) · **Fault** (this code base / library) · **Complexity** (simple / moderate / hard) · **Fix direction** (one or two sentences) · **Test** (how to reproduce on the lab phone and what a pass looks like).
Never invent frames, line numbers or log lines that are not in the input.
