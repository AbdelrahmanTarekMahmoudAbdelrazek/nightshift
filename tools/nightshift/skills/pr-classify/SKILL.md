---
name: pr-classify
description: Night Shift PR review - classify a pull request
---
# Classify a pull request

Decide what the PR is, from its title, description, branch names, Jira key, commit messages, the diff, and the list of
known crashes/ANRs on the Night Shift board (their top frames are given).

Types:
- crash_fix: fixes a crash (native SIGSEGV/SIGABRT or Java exception). Link it to a board crash when the changed code is on
  that crash's stack or the PR/Jira names it.
- anr_fix: fixes an ANR / freeze / main-thread block.
- behavior_fix: fixes wrong behaviour without a crash (wrong output, UI bug, wrong state).
- feature: adds a capability or screen.
- refactor: restructures without changing behaviour (also build/config/chore).

## Answer
ONLY a ```json block: {"type": "crash_fix|anr_fix|behavior_fix|feature|refactor", "confidence": 0-100,
"reason": "one sentence with the evidence", "jira": "KEY-123 or empty", "linked_issue": "board issue id or empty",
"risk": "low|medium|high", "areas": ["engine", "jni", "ui", "export", "..."]}
