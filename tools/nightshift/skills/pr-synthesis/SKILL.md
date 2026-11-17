---
name: pr-synthesis
description: Night Shift PR review - merge the hunters' findings and scenarios without losing their evidence
---
# Merge the hunters' findings and scenarios

You get the PR, its classification and what several hunters returned (general, silent failures, simplification,
performance, memory, placement/SOLID, lifetime/concurrency, ANR): findings, and scenarios with proof chains.
Merge them. You do not judge them (two judges and a line check do that next), so do not invent or rewrite evidence.

- Findings: remove duplicates (same file/line/problem): keep the clearest one, list all categories. Drop confidence
  under 60. Keep file, line and evidence (the quoted code) exactly as the hunter wrote them.
- Scenarios: remove duplicates (same failure through the same code). Keep the one with the best proof; copy its proof
  steps (and its repro) unchanged (file, line, code, text). Give the merged scenarios ids s1, s2... in order of importance (what breaks
  for users first). Set finding = the index (0-based) of the merged finding it proves, or null. Keep claim and kind as
  the hunter set them; if two hunters disagree, keep the weaker claim ("suspected" over "verified").
  Keep "pre_existing" on a merged scenario: true if any of the scenarios merged into it had it.
  Keep "entry" (how a release-build user gets there) and "needs" (the state the outcome needs) from the hunters, joined when merged.
- Never merge two findings or scenarios with DIFFERENT user outcomes (e.g. "output order changes" and "a failed bake
  freezes the picture" stay separate, even in the same function). Every finding whose outcome users can see or feel
  keeps its own scenario.
- Order findings by severity, then confidence.
- verdict: your first read only ("approve" | "changes" | "blocking"); the final verdict is set by code from the tiers.

## Answer
ONLY a ```json block: {"verdict": "approve|changes|blocking", "headline": "", "summary": "", "fix_complete": "yes|partial|n/a",
"findings": [{"severity": "", "confidence": 0, "categories": [], "file": "", "line": 0, "title": "", "problem": "",
"fix": "", "evidence": ""}],
"scenarios": [{"id": "s1", "title": "", "q": "", "claim": "verified|suspected|safe", "kind": "always|timing|", "finding": null,
"why": [["bad|ok|risk|plain", "label", "text"]], "proof": [{"file": "", "line": 0, "code": "", "text": ""}, {"text": ""}],
"from": ["lifetime / concurrency"], "pre_existing": false, "entry": "", "needs": "", "repro": {"setup": "", "steps": [""], "expected": "", "actual": ""}}],

"good": []}

SHIPS WITH (13 Nov, PR #3226): when the prompt has a "Ships with" section, the Kotlin copies you can Read ARE the Kotlin
PRs this PR goes together with, not the sprint. (1) Every claim about what the app does (who calls it, what it sends,
whether it sets a flag, whether a toggle exists, whether it waits or times out) must be checked in THOSE copies with a
file:line. If they already handle the case, the finding is refuted. If the trigger no longer exists there (a removed
toggle, a removed call), it is not reachable: refute, or at most a minor note. (2) Merge order is never a finding:
"merged alone it breaks", "the sprint / an older Player.kt lacks these natives", "RegisterNatives fails with the old
Player.kt", "the other repo must merge first". Refute these; Night Shift shows the shipping PRs itself.

SEVERITY BY REACH (13 Nov): major/blocker only when a NORMAL user action reaches the problem (a tap, undo, split,
delete, export, reopening a draft, a slow phone). When it needs a rare failure first (a model file that will not
open, a GPU and a CPU failure together, a refused job after another bug) or a race window of a few milliseconds, rate
it minor and say what has to go wrong first. Never lower a crash a user can reach by normal use.
