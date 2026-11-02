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
