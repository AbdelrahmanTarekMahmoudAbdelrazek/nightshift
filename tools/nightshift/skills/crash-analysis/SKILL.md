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
   own bug: a missing return, a race inside the engine, its own rounding). When the app's wrong call created the state
   that crashed, owner is "app-java" even if the engine is also fragile there: the wrong call is THE CAUSE, the engine
   weakness is only a missing guard (defence in depth), never a second cause.
8. How to write it when the cause is a wrong app call: root_cause STARTS with the trigger, i.e. the wrong Kotlin call
   (file:line, what it sends vs what it should send, what state that creates), then one short part "Engine (needs a
   guard): ..." saying where the engine should refuse or survive that state. summary and fix_direction follow the
   same order: the Kotlin fix first (the real fix), the engine guard second (hardening). owner_why says which call was wrong, with file:line.

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

## Check the Kotlin caller's arguments
When a lab or field log shows an engine message whose ids or values do not match the user's state (an index that
points at a different item than the one selected, a time past the timeline end, a layer or media id that does not
exist), do not leave it as an open question: find every Kotlin/Java caller of that call
(Grep `Player.<method>(` in android-video-editor-module/, java-common/, gallerypicker/) and compare each call's
argument ORDER and values with the `external fun` declaration in java-common Player.kt. A swapped or wrong argument
is a wrong call from the app: owner "app-java", cite caller file:line and the declaration line.

## Field facts (28 Oct)
The evidence has `field_facts`: the odd lines of the user's own log (rejected engine calls, duplicate ids, empty timeline,
instant at_end, timeouts). The root cause must explain EVERY one and contradict none; name in `evidence` which fact each
step of the trigger explains. When a fact shows an engine message with no tap before it (e.g. MsgSortMedia right after a
pause), find who sends it in `kotlin_side` (the Kotlin map: message -> JNI -> Kotlin callers). Several screens can keep
their OWN copy of the same data (a list, an index, a selection); when the engine rejects what the app sends, check every
copy and every caller, not only the first one you find.


## Which screen and which code the user was in (28 Oct)
- The screen class in an event (`firebase_screen_class`) names the ACTIVITY only. One activity can host several
  screens or modes, and each has its own UI code and its own event-name prefix. Before you name a caller, grep the code
  for the exact event names in the timeline (the `action_view` / event string). The file that logs them is the screen
  whose code ran. Follow THAT screen's handlers to the engine call. Don't assume the activity's main handler is the caller.
- Drags, swipes and long presses are usually NOT logged as events. An engine message with no tap before it (e.g. a
  reorder or seek) can come from a gesture on that screen's list. Look at the gesture callbacks (ItemTouchHelper,
  drag/drop listeners, scroll listeners) of the screen the event prefix points to.
- Say in `root_cause` which screen and which file/function sent the bad call, and why you know (the event names and
  the code that logs them).
