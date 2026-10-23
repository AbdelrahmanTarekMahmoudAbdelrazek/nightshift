---
name: card-visual
description: Night Shift card review - turn a judged root-cause review of a Jira card into the visual page (summary, replay from the video to the code, one replay and fix per scenario)
---
# Build the visual root-cause review of a Jira card

You get a Jira card Night Shift read (issues, steps, every frame of the screen recording with what it shows) and the
root-cause scenarios after the line check and the judges (tier verified / suspected / safe). You run in a read-only
checkout of the branch; the Kotlin repos under "Kotlin side" are readable. Never guess a line number: open the file.

Write for a developer who opens the card and wants to understand the bug in 30 seconds, and for QA who watch the
same video. Plain words, short sentences. Labels: the real call as written in the code. Captions: 1-2 full sentences
(what happens and why it matters).

## What to produce
1. tldr: 1-2 sentences: what the user sees and, if a scenario is Verified, its root cause. Never present a Suspected
   cause as a fact ("most likely ...", "not proven").
2. before: {title, text, mini}: "What the card shows": the bug in 1-3 sentences; mini = 2-4 rows [who, what, result]
   from the video (e.g. ["User", "drags Speed to max", "preview black"]).
3. adds: {title, text, snippet}: "The cause in the code": 1-3 sentences on the Verified (or most likely) root cause;
   snippet = 1-2 real code lines of the line where it goes wrong.
4. heads: one short "heads up" line (something the developer must know: e.g. the video and the card disagree,
   several issues share one cause, a fix needs both Kotlin and C++), or "".
5. flow: ONE message-arrow replay: from the video to the code, for the card's main issue.
   modes {"bug": "What happens now", "fix": "With the suggested fix"} (no fix mode when no cause is Verified or
   Suspected). Columns (3-4): "Screen" (what the user sees and does) FIRST, then the real actors (Kotlin UI, engine
   looper, renderer or audio thread, a shared object). bug = the user's actions from the video through the code to
   the BUG frame; fix = the same steps with the suggested fix, ending with what the user should see.
   Every step that matches something in the video gets "frame": the frame number (i) where it is visible (the user's
   tap or drag, the screen result). The LAST bug step is what the user sees, as a mark on the Screen column
   (from == to == 0), c "bad", with the frame of the first BUG frame and a tag naming it ("preview turns black").
   A step that shows a scenario's cause gets "sc": that scenario id.
6. scenarios: you get them. Do NOT add, remove, merge or reword them, and do not change their claim, kind, why or
   proof. For EACH given id return only its replay: {"id", "modes", "cols", "bug": {bars, steps}, "fix"?,
   "fixCode"?}. A Verified or Suspected cause with a clear fix gets a fix mode ("Suggested fix") AND "fixCode": the
   smallest real change (3-15 lines) with the exact names and lines of the code ('- ' removed, '+ ' added, '  '
   context lines). Put the fix where the wrong state is FIRST created (see "Where the suggested fix goes"): in the Kotlin app
   when the bad step is a Kotlin exit or handler (use the Kotlin path and real Kotlin names you opened), in C++ when it
   is the engine. Check boundaries (<= vs <,
   the last item, an exact end). No fixCode when you are not sure. A "Not the cause" (safe) scenario: one short mode
   ("Why it is not the cause"), 3-4 steps, the guarding step c "ok" with a tag. Scenario steps may also carry "frame".

## Where the suggested fix goes (cards)
The fix goes where the WRONG STATE is first created, not where the symptom shows. A black screen in the renderer is
often caused upstream: a handler that never seeks, an exit that forgets to sync. Decide by these checks, in order:
1. The card's Expected must come true with the fix. A change that only hides the symptom (no black, but the wrong
   clip shows) is not the fix: mention it in the note as "hides the symptom only".
2. Siblings: if other handlers of the same kind already do the right thing (e.g. other panels seek to the selected
   clip when they open), the fix is to make this one do the same, in the same layer and style. Cite the sibling line.
3. Ownership: the layer that owns the decision (the Kotlin UI decides where the playhead is when a panel opens; the
   engine decides how to draw a time it is given). A comment on the card that names a side ("java side card",
   "native") is a strong hint.
4. When both layers could change, give the primary fix in fixCode and the other one in the note as "defence in depth".
5. A "Server content: ..." cause: fixCode is a diff of the downloaded server file (its path as the file), and the note
   says it is a content upload (no app release needed).

## Replay steps (flow and scenarios)
cols: [[name, sub], ...]. Each step: {"from": col, "to": col, "label": "...", "c": "ink|ok|risk|bad|mut",
"ret": true for a reply/return arrow, "crash": true only for a real crash step, "crashText": "...",
"m": "where: function :line", "chips": ["value = x"] (0-3), "tag": {"col": n, "text": "...", "c": "ok|risk|bad"},
"cap": "1-2 sentence caption", "sc": "scenario id (flow only)", "frame": i, "file": "path", "line": n}.
from == to draws a mark on that column. bars: [{"col": n, "from": step, "to": step,
"cls": "bar-hold|bar-wait|bar-ok|bar-risk", "text": "...", "end": "..."}] for locks, waits or a state that lasts.
Colours: "bad" = the step that breaks, "risk" = the step that sets it up, "ok" = fixed or safe.

## Answer
ONLY a ```json block with keys: tldr, before {title, text, mini}, adds {title, text, snippet}, heads,
flow {title, lead, modes, cols, bug {bars, steps}, fix {bars, steps}}, scenarios [{id, modes, cols, bug, fix?, fixCode?}].

Answer with exactly ONE ```json block. If you notice a mistake, fix it inside that block before answering; never add a second "corrected" block after it.
