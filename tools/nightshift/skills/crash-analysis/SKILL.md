---
name: crash-analysis
description: Root cause + two diagrams for one production crash/ANR of MyZesty, from Google Play and Firebase evidence and the located source code. Output is strict JSON consumed by the Night Shift board. Never writes code.
---

# Crash analysis (Night Shift)

You get one problem as JSON: what both consoles saw (devices, dates, users/events), the crashed thread
(symbolized with the exact build's libMYJNILIB26.so), breadcrumbs (newest first), Google Play's symbolized
sample stack, and the bodies of the functions on the stack that exist in this repo (plus their callers).

Method:
0. If the input has `team_knowledge`, it is what our engineers verified (a manual repro, a Slack diagnosis, a board
   note). Treat it as ground truth: build the root cause, trigger, repro and diagrams on it, and use the stack and
   code to confirm and sharpen it (exact statement, file:line). Never contradict it with a guess; if the evidence
   really disagrees, keep the team's version and put the disagreement in open_questions. Cite it in evidence.
1. Read the crashed thread top-down. Find the first frame in OUR code (libMYJNILIB26.so, or com.myzesty /
   com.video / com.common Java). Framework frames above it (libc abort, mutex lock, futex, nativePollOnce)
   are where it surfaced, not the cause.
2. Read that function's body. `code` is the source AS SHIPPED in that build (`source`: release branch, commit,
   submodule commits), so its file:line are the real ones for the crash. Cite those lines. Name the exact statement that faults or blocks (null/out-of-range access, use
   after free, lock held across a slow call, main-thread I/O, missing timeout) and cite file:line.
3. Read EVERY line of EVERY event in `all_events.events[*].timeline_oldest_first` (each line: seconds before the
   crash, a tag USER / TEARDOWN / CREATE / ERROR / MEDIA / ENGINE, the message, and xN for repeats). Then read
   `shared_across_events_final_20s`: moments that repeat in several events are the trigger; moments seen in only
   one event are noise until proven otherwise. The trigger you name MUST explain every event, not just one.
   - Errors printed just before the crash are often CONSEQUENCES, not the cause. Example: "AMediaCodec_configure
     failed" right after "surface released" means the codec failed because the screen was torn down.
   - Look for lifecycle stories: screen/surface destroyed, engine or MsgLooper recreated, the user leaving or
     re-entering a screen, a template/draft reloading, while messages for the old state are still queued.
   - Use the last USER event, the screen class and the gap in seconds to say what the person was doing.
   - `other_crashes_in_same_crashlytics_issue` are different crashes grouped by Crashlytics: ignore them.
   Compare with sibling functions: a guard the siblings have and this one lacks is strong evidence.
3b. `instances` lists every crash instance from both consoles after duplicates are merged: `both` = the same
   physical crash reported by Firebase and Play (use both views of it together), `phone` numbers group the same phone
   model, `repeatPhones` = a phone that crashed more than once (its user hits the trigger reliably). Count crashes and
   phones from here, not from the console totals.
4. ANRs: start from `wait_chains`: code already followed who-waits-for-whom from the main thread (engine calls ->
   engine message thread, join() -> its worker, future.get() -> the pool task, Java locks -> holder, binder, MediaCodec)
   for every sample, and says where each chain ends and whether the samples agree. Name that end as the blocking
   cause, explain each link, and if samples disagree say the issue holds more than one ANR. Then read `all_threads` (every thread from Crashlytics and Google Play, engine frames symbolized). The main
   thread usually only WAITS; find what it waits for (MsgLooper::Get / GetResult = the engine message thread; a lock =
   the holder; binder = another process). Then read that thread: `our_code_or_lock_threads` lists the engine message
   thread (MsgLooper::ProcessMessages) first, then threads waiting on it. Name the exact call the blocking thread is
   stuck in (e.g. join(), a codec call, a lock) and the chain of waiters. If only the main thread exists, say so.
5. Before answering, write down at least two hypotheses and test each against every event (and team_knowledge).
   Keep the one that explains all of them. Confidence "high" only if it explains 2+ events or matches team
   knowledge; a cause seen in a single event is at most "medium".
6. If evidence is missing (unsymbolized frames, code not in this repo, third-party SDK) say exactly what is
   missing and lower the confidence. Never invent frames, lines, logs or numbers.
7. Owner = the side whose code made the WRONG decision, not the side where it crashed (team rule, 28 Oct). If the
   native engine crashes because the Kotlin/Java app called it wrongly (wrong order, a call after destroy or before
   create, a wrong id / clip / layer / time, a value the engine API does not accept), owner is "app-java" even when
   every crashing frame is C++. Owner is "engine" only when the engine does the wrong thing with a valid call (its
   own bug: a missing return, a race inside the engine, its own rounding). When both are wrong (the app sends a bad
   call AND the engine has no guard for it), owner is the side that made the wrong call; fix_direction names that
   fix first and the engine guard as defence in depth. owner_why says which call was wrong, with file:line.

Answer with ONE JSON object, no prose around it:
{
 "summary": "one sentence a manager understands (what crashes, where, how often)",
 "root_cause": "<= 120 words, cites file:line or the exact frame",
 "trigger": "the user/engine action sequence that leads to it, consistent with every event",
 "timeline": ["4-8 key moments in order, each 'T-0.2s: what happened (seen in N/M events)'"],
 "hypotheses": [{"h": "candidate cause", "verdict": "kept | rejected", "why": "which events support or refute it"}],
 "evidence": ["3-6 short bullet facts taken from the input"],
 "owner": "engine | app-java | third-party | system | unknown  (the side that made the wrong call, rule 7)",
 "owner_why": "one sentence: which call or decision was wrong and where (file:line), e.g. 'CoverActivity.kt:282 seeks after PlayerActivity destroyed the engine'",
 "confidence": "high | medium | low",
 "severity": "high | medium | low  (users hit, crash vs ANR, data loss)",
 "fix_direction": "<= 80 words, in words only, NO code",
 "repro": "how to reproduce on the lab phone (steps) and what a pass looks like",
 "diagram_cause": "Mermaid flowchart TD source: how it crashes, 5-10 nodes",
 "diagram_fix": "Mermaid flowchart TD source: the same flow with the fix stopping it, 5-10 nodes",
 "open_questions": ["what would raise confidence, if anything"]
}

Mermaid rules (the board renders them, keep them valid):
- Start with `flowchart TD`. Node ids are short letters/digits (A, B, C1). Every label in double quotes:
  `A["User opens draft"] --> B["add_video fails (-10000)"]`. No quotes or backticks inside labels; use ' if needed.
- Mark the crash node with `:::bad` and the fix node with `:::good`; end the source with
  `classDef bad fill:#fde8e8,stroke:#a32d2d` and `classDef good fill:#e8f5e9,stroke:#2e7d32` lines.
- Use `\n` only through the JSON string escaping; one statement per line.
