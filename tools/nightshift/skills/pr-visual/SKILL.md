---
name: pr-visual
description: Night Shift PR review - turn a reviewed PR into the six-page visual review (summary, flow replay, risky scenarios, change map, code cards)
---
# Build the visual review of a pull request

You get a pull request (diff, commits, classification) and the merged review findings. You do NOT get the PR
description: describe what the code does, from the code. You run inside a checkout of the PR head, so read any file of
the codebase (Read, Grep, Glob) to understand callers, threads, defaults and lifetimes. Never guess a line number: open
the file and check it. Every line number is a line in the file AFTER the PR (the worktree you are in).

Write for a developer who opens the PR and wants it in 30 seconds. Plain words, short sentences, no jargon a reviewer
outside this module would not know. Labels: the real call as written in the code. Captions: 1-2 full sentences (what happens and why it matters).

## What to produce
1. tldr: 1-2 sentences: what the PR does and the main risk.
2. before / adds: two boxes. For a fix: before = the problem (what goes wrong), adds = the fix. For a feature or
   refactor: before = how it worked before, adds = what this PR adds. Each: a title, 1-3 sentences, and for "before"
   2-3 mini rows [who, what, result] (result is a 1-3 word tag); for "adds" 1-2 short real code lines from the diff.
3. files: every changed file, with the functions/areas changed. dot: "r" = a finding points here, "y" = minor concern,
   "g" = fine. tag: "core", "skip" (only trivial: includes, members, comments) or "new" (added in the newest commit).
   Each function row has a one-line note and, if it is shown in the code cards, the hunk id.
4. ready: 2-5 cards answering "is it done?": {"kind", "title", "text", "scenario"}. kind "ok" (✓) ONLY for what the
   code proves; a result only a device can show (a glitch is gone, smoother, faster, looks the same) is "maybe"
   with the text "fixed in code, not measured on a device". "bad" (✕) only for a Verified scenario; a Suspected one is
   "maybe". Link the scenario id when there is one: the page colours the card by that scenario's tier.
5. heads: one short "heads up" line (things the reviewer must know that are not findings), or "".
6. flow: ONE message-arrow replay of the main flow. For a fix: modes {"bug": "Before", "fix": "With this PR"}, bug =
   how the crash/ANR happens, fix = the same flow with the fix. For a feature/refactor: bug = old flow, fix = new flow.
   3-4 columns (threads, components or shared objects), 5-9 steps per mode, following the replay rules you get.
7. scenarios: you get them (the hunters wrote them; a line check already checked their proof). Do NOT add, remove,
   merge or reword scenarios, and do not change their claim, kind, why or proof. For EACH given scenario id return only
   its replay: {"id": same id, "modes", "cols", "bug": {bars, steps}, "fix"?}: bug = how it goes wrong (or why it is
   safe), fix = the suggested fix if the scenario has one. Replay steps cite file:line of the PR head like the flow.
8. hunks: 3-6 code cards in review order (most important first, a trivial one last with skip: true). Each card shows
   only the lines that matter: show = line ranges [file, from, to] (keep each range under ~25 lines; several ranges
   are fine, they are joined with "…"); full = wider ranges [file, from, to] that contain the whole function(s) for
   "show full code"; hot = [file, line] lines a finding points at. note: one sentence on why to read it.
   links: [scenario id or "flow", step index (0-based), mode "bug"|"fix"] for the replay steps that run this code.
9. paths: start from the change map's paths (you get it): steps = [user action, component, function], cov = the given
   scenario id that covers it or null, note = short text when cov is null (e.g. "not affected").
10. order: the review order shown on the summary: [{hunk, title, where, why}] (same order as hunks).
11. finding_links: for each merged finding (by index): {finding, scenario (given id or null), hunk (id)}. The chair
    writes the comments later.

## Replay steps (flow and scenarios)
cols: [[name, sub], ...]. Each step: {"from": col, "to": col, "label": "...", "c": "ink|ok|risk|bad|mut",
"ret": true for a reply/return arrow (dashed), "crash": true only for a real crash step, "crashText": "...",
"m": "where: function :line", "chips": ["value = x", ...] (0-3), "tag": {"col": n, "text": "...", "c": "ok|risk|bad"},
"cap": "1-2 sentence caption", "sc": "scenario id this step shows (main flow only)", "hunk": "h-id", "file": "path/in/repo", "line": n}.
from == to draws a dot on that column (use with a tag for a state change). bars: [{"col": n, "from": step, "to": step,
"cls": "bar-hold|bar-wait|bar-ok|bar-risk", "text": "who holds what :take → :release", "end": "released|gets the lock|…"}] for locks held, waits, or a state that lasts.
Colours: c "bad" = the step that breaks, "risk" = the step that sets it up, "ok" = the fixed/safe step.

## Answer
ONLY a ```json block with keys: tldr, before {title, text, mini}, adds {title, text, snippet}, files, ready, heads,
flow {title, lead, modes, cols, bug {bars, steps}, fix {bars, steps}}, scenarios [{id (as given), modes, cols,
bug {bars, steps}, fix?, fixCode?}] (replays + the fix as code), hunks [{id: "h-..", n: "1".. or "–", title, file, range, note,
show, full, hot, links, skip?}], paths, order, finding_links.
