# Security and data

- **Inputs:** Crashlytics event exports (CSV) and lab logs. Event and session ids are hashed (SHA-256, 12 chars) before anything is written or sent; raw ids never appear in case files, prompts or tickets.
- **Model calls:** only through the company Claude account (`claude` CLI on the worker). The prompt is the skill text plus counted facts; no stack dumps with identifiers, no customer media, no source beyond the frames already in the report.
- **Secrets:** none in this folder or in `nightshift.yaml`. Jira, Slack, Bitbucket and Firebase credentials live in the runner's keychain / environment (Phase 2) and are read at run time.
- **Writes:** the tool writes only under `tools/nightshift/out/` and `runlog.csv`. Phase 2 posts to Jira/Slack and opens *draft* PRs; it never merges, closes or deletes anything.
- **Symbols:** `.so` symbol files are build artifacts, not customer data; they are stored in the team's bucket and never attached to tickets.
- **Case board:** a separate free Firebase project (never the production app's). Sign-in by email link; Firestore rules require a verified `@msd-my.com` address (optional allowlist). The browser can only read and queue one of three job types on an existing case; all other writes are refused. The worker writes with an Admin SDK key stored at `~/.config/nightshift/` (outside the repo, git-ignored by location).
- **Worker:** runs only the three actions in `ns/worker.py`, each a fixed command; job logs are truncated lines of tool output, never raw dumps.
