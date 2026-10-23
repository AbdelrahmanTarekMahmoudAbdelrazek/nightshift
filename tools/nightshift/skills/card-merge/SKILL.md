---
name: card-merge
description: Night Shift card review - merge the hunters' root causes and scenarios for a Jira card without losing their evidence
---
# Merge the hunters' root causes

You get a Jira card (its issues and what the video shows) and what three hunters returned: findings (root causes,
each at the line where it goes wrong) and scenarios with proof chains. Merge them. You do not judge them (a line check
and two judges do that next), so never invent or rewrite evidence.

- Findings: remove duplicates (same file and line, same cause): keep the clearest one, keep its issue number. Drop
  confidence under 50. Keep file, line and evidence (the quoted code) exactly as the hunter wrote them.
- Scenarios: remove duplicates (same cause through the same code for the same issue). Keep the one with the best
  proof; copy its proof steps, frames and repro unchanged. Keep "issue" and "frames" on every scenario.
- Never merge two different issues, or two different causes of the same issue: if hunters disagree on the cause, keep
  both scenarios (the judges decide). If two hunters disagree on the claim of the SAME scenario, keep the weaker one
  ("suspected" over "verified").
- Order: issue 1 first; within an issue, the main root-cause scenario first (a "Not built in MyZesty: ...", "Server content: ..."
  or "Not in the app code: ..." scenario keeps that title start word for word), then other candidate causes, then
  "Not the cause" (safe) checks, then "Not explained by the code". Ids s1, s2... in that order.
- finding = the 0-based index of the merged finding the scenario proves, or null.

## Answer
ONLY a ```json block:
{"findings": [{"issue": 1, "severity": "", "confidence": 0, "file": "", "line": 0, "title": "", "problem": "", "fix": "",
  "evidence": ""}],
 "scenarios": [{"id": "s1", "issue": 1, "frames": [], "title": "", "q": "", "claim": "verified|suspected|safe",
  "kind": "always|timing|condition", "finding": null, "why": [["bad|ok|risk|plain", "label", "text"]],
  "proof": [{"file": "", "line": 0, "code": "", "text": ""}, {"text": ""}], "from": ["root cause"],
  "repro": {"setup": "", "steps": [""], "expected": "", "actual": "", "when": "", "math": "", "control": "", "edges": []}}]}
Copy repro.when, repro.math, repro.control and repro.edges unchanged from the best scenario. When two hunters give different
"when" conditions for the same cause, keep both scenarios (the judges decide).
