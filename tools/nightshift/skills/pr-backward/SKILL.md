---
name: pr-backward
description: Night Shift PR review - hunt backwards: start from each bad outcome the touched code can produce and walk back to the changed lines
---
# Backward hunter: from the bad outcome to the change

The other seats read the diff and go forward. You go the other way, which finds the deep bugs that are three calls
away from the change.

## 1. List the bad outcomes near the change
In the changed files AND the functions they call or are called by (one level each way), list every place that can
end badly:
- crash: an index into an array/vector/list, a dereference, `!!`, a cast, an unchecked optional, a division, a
  native abort/assert, a JNI call that throws, `get(0)`/`first()` on a maybe-empty list;
- wrong result: a value written to a texture/uniform/file/draft, the frame or time shown, the order of items;
- freeze: a wait/join/lock/`synchronized`/looper message that waits on other work;
- lost or broken state: a save, a cache commit, an undo record, a field reset.

## 2. For each one, walk back
Ask: which values would make this line go wrong (index >= size, null, 0, stale pointer, wrong thread)? Then walk back
through the callers (Grep them, across Kotlin <-> JNI <-> C++) to find where that value comes from. Stop when you
reach:
- a CHANGED line (in the diff) that can now produce the bad value, or no longer stops it -> a scenario;
- a guard that always stops it -> nothing to report (do not list it);
- a user action or another thread -> say which one, and whether it is reachable in the release build.

## 3. The states to try on every walk
Empty, one item, the last item, many items; paused, playing, a background job still running (model, decode, export,
save); right after undo/redo; a restored draft; after the app was killed and reopened; the same action twice quickly;
the feature off. A state that turns a safe walk into a bad one is a scenario.

## 4. Report
Each finding gets a scenario whose proof goes FROM the user action/thread TO the bad line, through the changed line,
every step with file:line and the code copied exactly. Name in "skips" what could stop it (a cache, an early return,
a flag) and why it does not.

SHIPS WITH (13 Nov, PR #3226): when the prompt has a "Ships with" section, the Kotlin copies you can Read ARE the Kotlin
PRs this PR goes together with, not the sprint. (1) Every claim about what the app does (who calls it, what it sends,
whether it sets a flag, whether a toggle exists, whether it waits or times out) must be checked in THOSE copies with a
file:line. If they already handle the case, the finding is refuted. If the trigger no longer exists there (a removed
toggle, a removed call), it is not reachable: refute, or at most a minor note. (2) Merge order is never a finding:
"merged alone it breaks", "the sprint / an older Player.kt lacks these natives", "RegisterNatives fails with the old
Player.kt", "the other repo must merge first". Refute these; Night Shift shows the shipping PRs itself.

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
