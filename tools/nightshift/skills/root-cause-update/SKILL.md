# Root cause update after the lab (Night Shift)

A root cause was written from field data BEFORE the lab work. Since then the lab ran repro recipes, a diagnosis read
every run, Night Shift learned facts by reading the app code, and a fix patch may exist. Rewrite the root cause so it
says what is known NOW. Verify every code claim yourself (Read/Grep the repo; the shipped commit is given). Never
invent lab results: only use the lab facts, diagnoses and run notes you are given, and quote them.

Rules:
- Name the defect in our code precisely (file:line, the condition) when the evidence supports it; say what it causes.
- Say plainly what the lab proved and what it did not (e.g. "field condition reached with a hook; this phone's GPU
  driver returns an error instead of crashing").
- confidence: high only if the defect is in the code AND the lab showed the bad state; medium if one of the two.
- The diagrams are mermaid `flowchart TD`, 6 to 9 boxes, short labels, every box a real step from the evidence.
  diagram_cause ends at the crash (class bad); diagram_fix shows where the PATCH changes the flow (class good).
  Keep `classDef bad fill:#fde8e8,stroke:#a32d2d` and `classDef good fill:#e8f5e9,stroke:#2e7d32`.
- lab_confirmed: true only if a lab run reached the field state and logged the same failure (crash or the same
  error at the same call), false otherwise.
- Rewrite EVERY section so none contradicts the new root cause: trigger, timeline, hypotheses (each with verdict
  kept / rejected / open and why, citing what settled it), evidence, open_questions (only what is truly still open,
  at most 3; drop questions the code or the lab answered).
- Cite line numbers AT THE SHIPPED COMMITS (use `git show <commit>:<path>` / `git grep -n <pattern> <commit>`; the
  submodule commits are listed under source). If the working copy differs, say "(working copy: line N)".
Answer ONLY:
```json
{"summary": "...", "root_cause": "...", "confidence": "high|medium|low", "fix_direction": "...",
 "trigger": "...", "timeline": ["T-...: ..."], "hypotheses": [{"h": "...", "verdict": "kept|rejected|open", "why": "..."}],
 "evidence": ["..."], "open_questions": ["..."],
 "diagram_cause": "flowchart TD ...", "diagram_fix": "flowchart TD ...",
 "lab_update": "2-4 sentences: what the lab changed in the understanding", "lab_confirmed": true}
```
