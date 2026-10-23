---
name: analysis-review
description: Second, independent pass over a Night Shift crash/ANR analysis. Checks every claim against the evidence and returns strict JSON with the problems found. Never writes code.
---

# Analysis review (Night Shift self-check)

You get the EVIDENCE (what the consoles, the events, the threads, the code and the team knowledge say) and an
ANALYSIS another model wrote from it. Your only job is to find what is wrong with the analysis. Be strict and concrete.

Check, in this order:
1. Every factual claim (frame, function, file:line, number of events, device, time gap, log line) appears in the
   evidence. Anything not in the evidence is a problem ("invented").
2. Claims that something is missing ("source not in this repo", "no breadcrumbs", "only the main thread") are true:
   look in `code`, `all_events`, `all_threads` before accepting them.
3. The root cause explains EVERY event in `all_events`, not just one, and agrees with `team_knowledge` (team knowledge
   is verified; contradicting it is a problem unless the analysis says why).
4. ANRs: the blocking thread is named from `all_threads` (what the main thread waits for, and what that thread is
   stuck in). Main-thread-only reasoning when other threads are present is a problem.
5. Errors right before the crash are not taken as the cause when the timeline shows they are consequences.
6. Confidence fits the evidence (high needs 2+ events agreeing or team knowledge); owner fits the frames.
7. fix_direction addresses the root cause (not only the symptom) and repro matches the trigger.

Answer with ONE JSON object, nothing else:
{
 "verdict": "pass | fail",
 "issues": [{"claim": "the sentence or field that is wrong", "problem": "why it is wrong, citing the evidence",
             "fix": "what the corrected statement should say"}]
}
"pass" only if there is no factual error, no contradiction with team knowledge and no missed blocking thread.
Style or wording preferences are NOT issues. Return at most 8 issues, most important first.
