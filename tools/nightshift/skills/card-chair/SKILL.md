---
name: card-chair
description: Night Shift card review - write the short headline, issue lines and next steps of a judged root-cause review of a Jira card
---
# Write up a card's root-cause review (short)

You get a Jira card (its issues) and the checked results: each scenario with its tier after the line check and two
judges (verified = both judges confirmed it with code; suspected = possible, not proven; safe = checked, not the
cause), and its suggested fix (`fix_at` = file:line, `fix_note`). The status of each issue is set by code. You cannot
change tiers.

The page shows the causes, the code and the fixes itself. Your text is only the short frame around them, so leave out
anything a developer does not need: no review process, no judges, no token or tool talk, no repeating the card.

- headline: ONE sentence, at most 25 words: what the user sees and the verified cause in plain words, or that no
  cause was proven.
- summary: at most 2 short sentences.
- issues: for each issue number, one line of at most 15 words (what is wrong, or what is missing to prove it).
- next: at most 3 steps, each at most 18 words, most useful first. When a scenario has a suggested fix, name the fix
  exactly where `fix_at` says (same file and function, same idea as `fix_note`). Never move the fix to another place
  and never offer a second location of your own.
- qa: 3-6 numbered steps in app words for QA to retest after the fix (tap, drag, press the phone's Back button (system
  Back)), ending with what should happen.

Never present a Suspected cause as a fact.

## Answer
ONLY a ```json block: {"headline": "", "summary": "", "issues": [{"n": 1, "line": ""}], "next": [""], "qa": [""]}
