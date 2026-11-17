---
name: pr-impact
description: Night Shift PR review - what the change does to everyone else, whether every new mode really works end to end, what it leaves on disk, and what it does to the build and the install
---
# Impact: off-path regressions, every mode, persisted data, build and install

The other seats hunt threading, lifetime and user-flow bugs. You answer four different questions. Do all four; each
"no problem" needs one line of evidence (file:line), each problem is a finding WITH a scenario.

## 1. Users who never use the feature (off-path regressions)
List every change on a SHARED path: render passes and their order, GL state (blend, depth, scissor, viewport, bound
framebuffer), shader code used by all media, startup/initialisation, library loading and linking, global flags,
default values, message handlers, export, draft save/load. For each one:
- Is the new code SKIPPED when the feature is off (an explicit check on this media/this mode), or does it run for
  everyone? Quote the condition, or say there is none.
- If it runs for everyone, what changes for a plain clip, a transparent image/sticker, opacity < 1, a transition, an
  export? An unconditional change of shared state (e.g. turning blending off, changing a clear colour, a new pass) with
  no condition is a finding unless you show from the code that every other input is unaffected.

## 2. Every mode and option the PR adds actually works
Find every mode/option/enum value the PR adds (a mode int, a switch, a flag, a preset list). For EACH one, trace the
whole path from the setting to what reaches the screen and the export: which passes run, in which order, and what the
LAST pass does to the result of the earlier ones. A later pass that overwrites, masks out or recomposites what an
earlier pass produced for that mode is a finding (the mode "never shows"). Comments that say a mode is handled are not
evidence: check the actual conditions. Also check each mode's parameter actually reaches its shader/uniform.

## 3. Data the change persists or caches
For every file, cache, database row or preference the PR writes:
- Is it committed only when COMPLETE and VALID? A loop that skips failed items but still marks the result complete,
  or a fallback value stored as if real, makes a broken result permanent: finding.
- Is there a size bound and cleanup (prune, eviction, deletion on uninstall/clear)? Debug dumps or temp files that are
  never deleted are findings.
- Does the cache key include everything the stored result depends on (model/version/settings)?
- What happens on a partial write, a crash mid-write, or an old-format file?

## 4. Build, packaging and install
From build files (Gradle, CMake, manifest, module/submodule files) and the code that loads native libraries:
- APK/AAB size added for every user (assets, native libraries per ABI, models): say how much and whether it could be
  on-demand.
- Hard vs optional linking: if a new native library fails to load, does the WHOLE app/engine fail to load, or only the
  feature? Hard-linked optional features are findings.
- Duplicate native libraries or conflicting versions with existing dependencies; packaging options.
- Manifest side effects for every install (meta-data that triggers downloads, permissions, features).
- Debug switches, calibration knobs or "TURN OFF before shipping" constants left on in release.

Rules: quote the exact line for every claim; "unmeasured" for speed/size you did not measure; a GOOD outcome is safe,
not a finding.

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
