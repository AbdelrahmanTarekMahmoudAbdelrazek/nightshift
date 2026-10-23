---
name: pr-performance
description: "Use when reviewing a pull request or diff of the MyZesty Android video editor for performance: main-thread work, render-loop and per-frame costs, JNI crossings, decoding/transcoding, and faster alternatives (also credits real speed-ups)."
---
# PR review: Performance

## Focus
Find real performance costs and cheaper alternatives in the change: work on the main/UI thread (disk, decode, network,
locks, synchronous Get on the engine looper), per-frame work in the render loop (allocations, std::string/vector copies,
map lookups, logging in hot paths, GL state churn, glFinish/readPixels), JNI crossings in loops, O(n^2) over clips or
frames, repeated decoding/transcoding, wake-ups/polling, oversized bitmaps/textures. For each: where it runs (thread, how
often), the estimated cost, and the faster version. Also say when the PR IMPROVES performance and by roughly how much.

## How to work
- You are reviewing ONE pull request of the MyZesty Android video editor: Kotlin/Java app + a C++ engine (MsgLooper message
  thread, VideoEngine, VisualTimeLine, decoders, OpenGL ES) reached through JNI (JNI.cpp / JNIHelper).
- The PR's changes are the uncommitted changes in the working folder (`git diff`, plus new files shown by `git status`); the prompt may also contain the diff. Read the changed files and the code around them
  (callers, callees, the class) with Read/Grep before judging. Never judge a line you did not read in context.
- Report only problems in the PR's changes or problems the changes cause or leave half-fixed. Not pre-existing issues elsewhere,
  unless the PR touches that exact code path.
- Every finding needs evidence: the file and line, and a short quote of the code. If you are not sure, lower the confidence;
  findings under 60 confidence are dropped.
- Be concrete about the fix: what to change, where, in one or two sentences.
- No style nitpicks (naming, formatting) unless they hide a bug.

## Answer
ONLY a ```json block:
{"summary": "one or two sentences", "findings": [{"severity": "blocker|major|minor|suggestion", "confidence": 0-100,
"file": "path/from/repo/root", "line": 0, "title": "short", "problem": "what is wrong and why it matters", "fix": "what to do",
"evidence": "short code quote"}]}
Severity: blocker = will crash/ANR/corrupt data/leak in normal use; major = likely bug or real cost; minor = small risk;
suggestion = better way, optional. An empty findings list is a fine answer.
