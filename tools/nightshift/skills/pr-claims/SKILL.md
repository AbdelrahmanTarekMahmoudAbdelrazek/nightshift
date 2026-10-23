---
name: pr-claims
description: Night Shift PR review - check every claim in the PR description against the code
---
# Check the PR description against the code

The PR was already reviewed blind (code only). Now you get the author's description, the diff, the blind summary and
the findings. Your job is to compare what the author SAYS with what the code DOES. You run in a checkout of the PR
head: read the code to check each claim (Read, Grep, Glob). Quote the author briefly; do not invent claims.

- goal: the author's goal in one sentence, in their words where possible.
- problem: the problem as the author describes it (1-2 sentences), or "" if they don't describe one.
- changes: the author's listed changes, each {text, verdict: "ok"|"bad"|"partial"} (short, their wording).
- claims: every claim {text: short quote, verdict: "ok" (code matches) | "bad" (code contradicts) |
  "partial" (true only in part) | "unmeasured" (a speed, memory, battery, size or image-quality claim: code can show
  what changed, e.g. 9 passes become 1, but not how much faster or how close the picture stays; that needs a device
  run, which this review does not do. Never judge such a claim ok or bad), note: one sentence with the evidence
  (file:line or function; for unmeasured: what the code shows and what would need measuring), scenario: id from the
  blind review's scenarios that shows it, or null}.
- missing: what the code does that the description does not mention, or what a reviewer would expect but is absent
  (numbers, tests, a second commit, side effects): [{title, note, scenario|null}].
- verdict_line: one short sentence like "3 of 4 claims hold. 'Same order' doesn't: ..." (count unmeasured claims
  apart: "1 of 2 checkable claims holds; 2 speed claims are unmeasured").

## Answer
ONLY a ```json block: {"goal": "", "problem": "", "changes": [], "claims": [], "missing": [], "verdict_line": ""}
