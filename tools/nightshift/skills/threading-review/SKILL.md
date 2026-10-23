---
name: threading-review
description: Review a native-engine PR for ANR and deadlock hazards using the diff, Infer output and the ANRSan finding delta against the base branch. Produces a PR comment in the team's PR_*.md style.
---

# Threading review

Inputs: the diff limited to `app/src/main/cpp`, `build/infer/report.txt` (RacerD data races, Starvation blocking calls), and the ANRSan finding delta (`new`, `gone`, `unchanged` fingerprints from `anrsan_findings.py` on base vs head).

Write a review comment with these sections, in this order, short:

1. **Verdict line** — `No new threading hazards` / `1 new HIGH finding` / `Fixes F008, introduces nothing`. Fingerprint ids when present.
2. **New hazards** — for each new ANRSan finding or Infer Starvation report: the chain in one line (who waits on whom, with or without timeout), the file:line in the diff that created it, and the smallest fix (a deadline on the wait, join off the critical thread, release the lock before the wait, reorder teardown). Cite the house rules in `ANR_FORENSICS_SYSTEM_DESIGN.md` and `tools/anrsan/README.md` when relevant.
3. **Hazards removed** — findings that disappeared, so the author gets credit and the case file can link the PR.
4. **Not blocking, worth knowing** — `LOW framework-sync` and `INFO likely-idle` items in one sentence each, or "none".
5. **Changelog line** — one line for RELEASE notes, user-visible wording (see skills/changelog).

Rules: never approve or request changes yourself; a human does. Quote code only from the diff. If Infer or ANRSan did not run, say which and why the review is partial.
