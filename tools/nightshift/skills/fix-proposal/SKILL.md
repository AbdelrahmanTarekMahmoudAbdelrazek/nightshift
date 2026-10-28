---
name: fix-proposal
description: Produce the smallest safe patch (one unified diff) for a crash whose root cause is known. Used by sentinel.py fix; the patch is only a hypothesis until a replay of the same seed is clean.
---

# Fix proposal

Rules:
- Smallest change that removes the fault. Prefer the pattern the surrounding code already uses (e.g. the bounds check + `throw std::runtime_error("ERROR | Class::method ...")` that sibling VisualTimeLine methods use, which MsgLooper turns into a cancelled message instead of a crash).
- No refactors, no renames, no formatting changes, no new dependencies. Touch at most 2 files.
- Fix the side that made the WRONG call (team rule, 28 Oct). A wrong Kotlin/Java call that crashes in the C++ engine is
  fixed in Kotlin/Java (module folders under the repo root: android-video-editor-module/, java-common/, gallerypicker/),
  with paths like `b/android-video-editor-module/src/main/java/...`; an engine guard may be added as defence in depth.
  An engine bug with a valid call is fixed in C++. Kotlin guards log `Log.w("NightShift", "<function>: <reason>, call skipped")`.
- Output a short **Cause** paragraph, then exactly one ```diff block in `git diff` format with paths relative to the repo root and correct line context so `git apply --check` passes.
- Then a **Test** paragraph: which stress scenario/seed to replay and what log line proves the fix (e.g. the message now fails with `ERROR | VisualTimeLine` and the app keeps running).
- If the right fix is not local (needs a design change), say so and propose the minimal crash guard plus a follow-up note, clearly labelled.
