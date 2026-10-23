---
name: pr-changemap
description: Night Shift PR review - map every changed function to its callers, threads and user entry points before the hunt
---
# Change map of a pull request

You run in a checkout of the PR head (Read, Grep, Glob). Before anyone looks for bugs, map what the change touches.
Facts only: no opinions, no findings. Open the code for every claim; never guess a caller or a thread.

For every changed function or block (from the diff):
- name, file, line (in the PR head), what changed in one short line;
- callers: EVERY place that calls it (file:line of the call), found with Grep over the whole repo, not only the one the
  PR is about: message-looper handlers (MsgLooper functions[...]), JNI entry points, draft load/restore, undo/redo,
  export, batch/apply-to-all paths. Up to 12, each with what triggers it ("draft restore: MsgSetMediaSpeedDraft");
- threads: which thread(s) run it, from the code (e.g. "engine looper (MsgLooper)", "Oboe audio callback", "GL render
  thread", "export thread", "UI/main", "coroutine Dispatchers.Default"), with the file:line that shows it, or "unknown";
- shared state: members/globals it reads or writes that another thread also touches (name + file:line of the other use);
- entry points: user actions or app events that reach it (e.g. "drag the timeline", "export", "open a draft"), via which path.
Then paths: 3-8 user actions that reach the changed code, as steps [user action, component, function].

Keep it compact: this map is given to six reviewers as their starting point.

## Answer
ONLY a ```json block: {"functions": [{"name": "", "file": "", "line": 0, "change": "", "callers": ["File.cpp:123 caller()"],
"threads": [{"thread": "", "evidence": "File.cpp:45"}], "shared": [{"name": "", "other_use": "File.cpp:67"}],
"entry_points": [""]}], "paths": [{"steps": ["user action", "component", "function"]}]}
