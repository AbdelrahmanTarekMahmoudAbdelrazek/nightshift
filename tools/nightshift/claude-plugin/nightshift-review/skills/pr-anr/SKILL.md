---
name: pr-anr
description: "Use when reviewing a pull request or diff of the MyZesty Android video editor for ANR risk: synchronous waits on the engine looper from the UI thread, shared locks, I/O, decoder/EGL calls or sleeps on the main thread."
---
# PR review: ANR risk

## Focus
Find what can block the main thread for seconds: synchronous waits on the engine (Get<>/future.get on the UI thread),
locks shared with background threads, file/network I/O, decoder or EGL calls, Thread.sleep/join, runBlocking, large
JSON/DB work, BroadcastReceiver/Service work over the limits. For each: the call chain from the UI thread to the wait, how
long it can take, and the non-blocking alternative.

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
