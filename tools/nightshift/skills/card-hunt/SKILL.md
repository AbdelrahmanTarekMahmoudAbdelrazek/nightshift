---
name: card-hunt
description: Night Shift card review - find the root cause of what a Jira card and its screen recording show, with a proof chain through the real code
---
# Find the root cause of a card's bug

You get a Jira card Night Shift already read: the issues, the steps, and EVERY frame of the screen recording with what
it shows (BUG = the bug is visible in that frame, #n = which issue). You run in a read-only checkout of the branch to
check; the app's Kotlin repos are under "Kotlin side" (Read/Grep them). The prompt also has a map of where each issue
lives and the code of the main functions. Your seat (what to focus on) is at the end of the prompt.

The goal is the cause of THIS bug, not "possible problems in this area": for each issue, the chain from what the user
did (the frames just before the first BUG frame) to what the screen shows (the BUG frames), through the real code,
with the line where it goes wrong.

How:
1. Start from the user's last actions before the first BUG frame, and from what the BUG frames show (a black
   preview, a cursor in the wrong place, the app gone = a crash, the same frame for seconds = a freeze, wrong sound).
2. Follow the code those actions run: Kotlin handler → JNI → looper → engine → renderer or audio, and back to what is
   drawn or played. Open every function you rely on. A Kotlin line counts as evidence: cite it.
3. Find the step where the state becomes wrong: a value not reset, a missing seek, a race, a check with the wrong
   boundary (< vs <=, the last item, an exact end), a cache not cleared, a failure stored as ready, an exit (Done,
   Cancel, system Back) that forgets to sync the engine and the UI. That line is the root cause. Say why it produces
   exactly what the BUG frames show.
4. Check your chain against the video: the screen, the timing and the order of events must match. If the video
   contradicts the chain, it is not the cause.
5. Alternatives: name 1-3 other places that could explain the same thing and check them. One you ruled out is a
   "safe" scenario titled "Not the cause: ..." whose proof cites the line that rules it out.
6. If the code cannot explain an issue (a server answer, an asset, a device or driver problem), write ONE "suspected"
   scenario titled "Not explained by the code: ..." whose why says what evidence is missing (a log, a device, a
   server response). Never force a code cause onto it.

Rules:
- Every proof step that cites a line quotes that line's code exactly: a script checks each one and DROPS the scenario
  when it does not match. Lines are lines of THIS checkout (Kotlin: the copies under "Kotlin side").
- claim: "verified" = the code forces it on the steps the user did; "suspected" = possible, but it depends on thread
  timing, a device, or a trigger you could not find; "safe" = you checked it and it is not the cause.
- kind: "always" = every time those steps run; "timing" = needs a thread interleaving (never "always" for a race);
  "condition" = only when something else happens first (say what in why).
- frames: the frame numbers (i) this scenario explains; the BUG frames of its issue first.
- What the screen shows is proven by the video frames, not by the code. You prove the code chain up to the WRONG STATE
  (the time left past the clip's end, a frame that is never decoded, a value not reset, the engine and the UI out of
  sync). If the code certainly puts the app in a state where the screen cannot be right, and the video shows the
  screen wrong at that moment, that is enough: whether the GPU then shows black, a stale frame or garbage depends on
  the driver and is never a reason for "unsure". Say "exact pixels depend on the device" in the note and claim "verified".
- Never name a file, class or caller you did not open. Speed, memory and image-quality effects are unmeasured: never
  claim them from code.
- A wait done while holding a lock: follow the waited-for task's calls two levels deep. If it needs that lock, the
  timeout is forced by the code, not by a slow device.
- repro is for QA, who test by hand and never read code or logs: setup = the project to start from; steps = 3-8
  numbered actions in the app's words (tap, drag, select, press the phone's Back button (system Back), undo); expected
  = what should happen; actual = what the video shows. If it needs luck (a race), say so in setup ("rare: may need
  several tries").
- The exact trigger (repro.when, repro.math, repro.control). A bug that needs a condition is only useful to QA when
  the condition is exact. Find in the code the comparison that decides bug vs no bug (a boundary, an order, a count)
  and write it in app words with the app's quantities: playhead time, clip lengths, the speed, the total timeline
  length, which clip is selected, how many clips. Example of the level wanted: "black only when the playhead time is
  later than the new end of the whole timeline (total length after the speed change)", not "black at max speed".
  Then:
  * math: the arithmetic with the REAL numbers read from the video frames (time labels, clip lengths, speed shown),
    e.g. "clips 16 s + 19 s + 19 s = 54 s; at 20x clip 2 = 0.95 s, so the timeline is 35.95 s; playhead 22 s < 35.95 s".
  * setup and steps use specific numbers that satisfy the condition with a safe margin ("3 clips: 16 s, 19 s, 5 s; put
    the playhead at 30 s, inside clip 2"). Never "somewhere in the middle".
  * control: the closest setup that does NOT meet the condition, with numbers, and what QA should see then ("same,
    but make clip 3 40 s long: the preview keeps a frame"). If the control would also break, your condition is wrong:
    find the right one.
  * edges: a condition has edges (every "<", ">", "and", "only when"). For EACH edge give one case with numbers just
    inside and one just outside, and follow EACH case through the code to what the screen shows (do not assume: the
    code may clamp, wrap, skip or fall back). Typical edges for a time bug: inside the selected clip's new length;
    just past it (in the next clip); past the end of the whole timeline (clamped?); the first and the last clip.
    If two edges give the same screen, merge them into one wider condition ("whenever the playhead is no longer
    inside the selected clip", not "between X and Y"). Write each as {"case": "", "numbers": "", "result": "black |
    frame | crash ...", "line": "file:line that decides it"} in repro.edges. The control is the edge case that does
    NOT break.
  * If the code shows two different conditions could each give the same screen, say which one the video's numbers
    meet, and make the control tell them apart.
  The condition must come from the code you cited (name the comparison's line in proof); the numbers from the frames.
- One finding per root cause (the line where it goes wrong), linked from its scenario. A ruled-out place has no finding.

## Where the fix goes (the finding's "fix" field)
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

## Server content (effects, frames, transitions, templates...)
When the prompt has a "Server content" section, those files are what the app downloads and runs unchanged (a shader, a
webp image, the item's JSON). Read them. If the wrong behaviour comes from that content (the shader ignores the image
ratio, the item points to the wrong file, a size or id is wrong), the main scenario is titled "Server content: ..." and
cites the downloaded file's lines like code (path:line, code copied exactly); compare with the app's own shader or code
that does it right. Claim "verified" when those lines force what the video shows. The fix is a change to that server
file (show it as a diff of the downloaded file) and the note says it is a content upload, not an app release. If the
file is missing from the section, say so and title the scenario "Not in the app code: ..." (suspected).

## A reference video from another app (e.g. CapCut)
Some cards have two videos: one from another app (CapCut, InShot, VN...) showing the RIGHT behaviour, and one from
MyZesty showing the wrong one ("mask applied wrong, not as CapCut"). The other app is only the expected result: never
look for its code, never cite it as a cause, and never take a step from it. Compare the REF frames with MyZesty's BUG
frames at the same action (same item applied, same gesture) and name the concrete difference (scale, position, crop,
rotation, timing, a missing option). The cause is the MyZesty code that produces that difference. If MyZesty never
does what the other app does (no code path for that behaviour at all), write the main scenario titled
"Not built in MyZesty: ..." with claim "verified" when the code proves it (cite the lines that do it differently or
the place where the option would have to go), and a fix that adds it. That is a feature gap, not "Not explained".

## Answer (overrides any other answer format)
End with ONE ```json block:
{"summary": "",
 "findings": [{"issue": 1, "severity": "blocker|major|minor|suggestion", "confidence": 0, "file": "path", "line": 0,
   "title": "the root cause in one line", "problem": "how it produces what the video shows",
   "fix": "where and what to change", "evidence": "the code on that line, copied exactly"}],
 "scenarios": [{"issue": 1, "frames": [64, 70], "title": "why ... / what if ...", "q": "the question it answers",
   "claim": "verified|suspected|safe", "kind": "always|timing|condition", "finding": 0,
   "why": [["bad|ok|risk|plain", "label", "text"]],
   "proof": [{"file": "", "line": 0, "code": "copied exactly", "text": "what this step shows"},
             {"text": "a step that is not code: a user action, or what the screen shows at frame N"}],
   "repro": {"setup": "", "steps": [""], "expected": "", "actual": "", "when": "", "math": "", "control": "", "edges": [{"case": "", "numbers": "", "result": "", "line": ""}]}}]}
finding = the index of the finding in YOUR findings list, or null.
