---
name: fix-proposal
description: Produce the smallest safe patch (one unified diff) for a crash whose root cause is known. Used by sentinel.py fix; the patch is only a hypothesis until a replay of the same seed is clean.
---

# Fix proposal

Rules:
- Smallest change that removes the fault. Prefer the pattern the surrounding code already uses (e.g. the bounds check + `throw std::runtime_error("ERROR | Class::method ...")` that sibling VisualTimeLine methods use, which MsgLooper turns into a cancelled message instead of a crash).
- No refactors, no renames, no formatting changes, no new dependencies. Touch at most 2 files per side (Kotlin / engine).
- Write like the code around it (team rule, 28 Oct): the file's naming, its log macro/tag, its error pattern, its coroutine
  and dispatcher habits, its formatting. Before writing any helper, flag or list, Grep the repo AND the Kotlin modules for
  one that exists (refresh/resync of a list, a bounds check, a cached count) and reuse it; say what you reused in **Cause**.
- Field facts (28 Oct): explain every odd line of the user's log (field_facts) with your theory, and contradict none.
  Check what each fact PROVES happened, not only what went wrong: a value in a later message can prove an earlier step
  ran, which rules out theories that assume it did not. When a fact points at another screen or caller, that is where
  the fix goes.
- Fix the side that made the WRONG call (team rule, 28 Oct). A wrong Kotlin/Java call that crashes in the C++ engine is
  fixed in Kotlin/Java (module folders under the repo root: android-video-editor-module/, java-common/, gallerypicker/),
  with paths like `b/android-video-editor-module/src/main/java/...`; an engine guard may be added as defence in depth.
  An engine bug with a valid call is fixed in C++.
- Logging in a guard (29 Oct: reviewers blocked fixes over a foreign "NightShift" tag): write it the way THAT file
  already logs. Kotlin/Java: the file's own TAG constant (or the tag its other Log calls use), e.g.
  `Log.w(TAG, "onItemClicked: position 1 >= 1 engine clip, ignored")`; never a tool name as the tag. C++: the macro
  and message shape the neighbouring guards use (copy one, e.g. include the size: `layer_size=%zu`). The words must say
  what the code does: "ignored"/"skipped" for an early return, "throwing" for a throw. Keep one line with the function
  name and the bad value: the lab finds the guard by that message text.
- A guard must check the SAME state the crashing call uses (the engine's count for an engine call), not a UI copy of it
  that can be out of step; if only the UI copy is reachable, say so and keep the engine-side guard.
- Output a short **Cause** paragraph, then exactly one ```diff block in `git diff` format with paths relative to the repo root and correct line context so `git apply --check` passes.
- Then a **Test** paragraph: which stress scenario/seed to replay and what log line proves the fix (e.g. the message now fails with `ERROR | VisualTimeLine` and the app keeps running).
- If the right fix is not local (needs a design change), say so and propose the minimal crash guard plus a follow-up note, clearly labelled.

## Which screen's code sent the call (28 Oct)
The activity in the field events can host several screens or modes. Grep the code for the exact event names in the
timeline: the file that logs them is the screen whose code ran. Fix THAT screen's handler (including its gesture
callbacks: drag/drop, swipe, scroll, which are usually not logged as taps), not just the activity's main handler. If
several screens share the same bad pattern, say so, and fix or guard each caller.
