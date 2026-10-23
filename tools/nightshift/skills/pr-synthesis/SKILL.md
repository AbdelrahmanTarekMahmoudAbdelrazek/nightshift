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
"from": ["lifetime / concurrency"], "pre_existing": false, "repro": {"setup": "", "steps": [""], "expected": "", "actual": ""}}],

"good": []}
