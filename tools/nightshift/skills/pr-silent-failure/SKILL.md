---
name: pr-silent-failure
description: Night Shift PR review - silent failures
---
# PR review: Silent failures

## Focus
Hunt errors that are swallowed or hidden: empty catch blocks, catch-all that logs nothing, runCatching/try without
handling, native code that throws inside the MsgLooper (caught there and turned into an error value the Java side may not
check), returning a default/null that callers use as real data, ignored return codes (AMediaCodec, EGL, JNI), and coroutine
exceptions lost in a scope. Say what the user sees when it fails and how the failure should surface (log + safe state +
report).

## How to work
- You are reviewing ONE pull request of the MyZesty Android video editor: Kotlin/Java app + a C++ engine (MsgLooper message
  thread, VideoEngine, VisualTimeLine, decoders, OpenGL ES) reached through JNI (JNI.cpp / JNIHelper).
- The working folder is the PR's code (PR head). The diff is in the prompt. Read the changed files and the code around them
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

SHIPS WITH (13 Nov, PR #3226): when the prompt has a "Ships with" section, the Kotlin copies you can Read ARE the Kotlin
PRs this PR goes together with, not the sprint. Check every claim about what the app does in THOSE copies (file:line);
if they already handle it, or the trigger no longer exists there, do not report it. Merge order ("merged alone it
breaks", "the sprint / an older Player.kt lacks these natives") is never a finding.

MUST-CHECK LISTS (13 Nov, #3226: both bugs below were missed by one run and found by another)
A. Work on another thread (a worker, a decoder, a walk, a callback): list everything end(), begin(), cancel, close,
   delete and reset set while that work runs (sizes to 0, buffers cleared, ids changed, objects freed). For each,
   check whether the work USES it after its slow step (decode, inference, I/O, wait). A "still current?" check made
   only BEFORE the slow step does not protect what comes after it. Also check an exception in that work: an uncaught
   one on a std::thread aborts the app.
B. Any new per-clip state (tracks, masks, caches, effects, ids): follow it through delete -> Undo (detach / restore),
   split, duplicate and replace, on the native side AND in the Kotlin code (who calls restore, what is re-sent after
   it). State shared by two clips (copied ids) must not be wiped by one of them.

SEVERITY BY REACH (13 Nov): major/blocker only when a NORMAL user action reaches the problem (a tap, undo, split,
delete, export, reopening a draft, a slow phone). When it needs a rare failure first (a model file that will not
open, a GPU and a CPU failure together, a refused job after another bug) or a race window of a few milliseconds, rate
it minor and say what has to go wrong first. Never lower a crash a user can reach by normal use.
