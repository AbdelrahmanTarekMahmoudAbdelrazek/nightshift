---
name: anr-triage
description: Write the narrative of an ANR/crash case file from counted facts produced by sentinel.py triage. Use when a Crashlytics issue needs a verdict (engine / not engine) and a report in the MyZesty house format.
---

# ANR triage narrative

You are drafting the prose of a stability case file for the MyZesty Android video editor. The numbers were counted by `tools/nightshift/sentinel.py triage` and are authoritative. You may not change, round differently, or invent a number. If a number you want is missing, write "not in the export".

## What you receive
A JSON object of facts: event counts, dump counts, cause-bucket shares, last-breadcrumb tables, device/version mix, native-engine log sites, and a rule-based verdict with its reasons.

## What you write (and nothing else)
Three short paragraphs in the voice of the team's existing reports (`ANR_2026-09_nativePollOnce_FCM_background_report.md` is the reference):

1. **TL;DR** — one paragraph. Start with the verdict in plain words ("This issue is not a main-thread hang and not the video engine" or "This issue is the engine: ..."). State the single strongest piece of evidence with its number and share.
2. **What the dumps say** — which pipeline the dumps show (FCM image download, FCM receiver, React Native context creation, native engine threads), with counts. Name the frames or log sites exactly as given.
3. **What to do next** — one paragraph. For not-engine: which team owns it and what Crashlytics custom key would make the next one self-classify. For engine: which editor path the breadcrumbs point at and which scenarios to run first.

## Rules
- Plain, specific sentences under 25 words. No bullet lists, no headings (the template has them).
- Never name a user, device id, session id or email. Identifiers are hashed before you see them; keep it that way.
- Confidence words follow the tool: high / medium / low. Do not upgrade them.
- If the verdict is "mixed" or "insufficient", say so first and recommend splitting or waiting; do not guess a cause.
- Finish with one sentence that a non-engineer can read aloud: what the user experienced and whether the editor is to blame.
