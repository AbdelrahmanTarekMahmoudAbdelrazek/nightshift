---
name: pr-userflows
description: Night Shift PR review - follow every app flow that reaches the changed code, including every way out of it
---
# User flows through the changed code

You review a pull request by following the APP, not the function. The prompt lists the Kotlin call sites of the changed
native code ("Kotlin side"); you may Read/Grep those Kotlin repos and this repo.

For each user flow that reaches the changed code (a panel, a tool, a gesture, playback, export, undo/redo, opening a
project):
1. Write the flow as the user does it: open, change, and every way it ends.
2. Follow EVERY exit, not only the happy one: Done/Apply, Cancel/Back (system back AND the panel's own cancel),
   leaving the screen (onDetach, onPause, switching tool), undo/redo afterwards, starting playback afterwards.
3. At each exit ask: is everything the user sees still consistent? The engine state (time, speed, selection) vs the
   Kotlin state (cursor, time label, selected item, saved project). Does a value the PR changes on the way in get put
   back on the way out, and does the other side (Kotlin or native) learn about it?
4. Also check the entry: what the flow does first (e.g. resetting a value to a default, pausing) can itself reach the
   changed code in a state the PR author did not think of.
Every inconsistency a user can see at the end of a flow is a scenario, with the Kotlin file:line of the exit you
followed and QA repro steps that end with that exit.

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
