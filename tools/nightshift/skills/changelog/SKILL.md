---
name: changelog
description: Turn a merged engine PR (title, description, diff summary, linked MZ ticket, ANRSan delta) into one release-note line and one internal changelog entry.
---

# Changelog

Produce exactly two lines:

- **Release note (user-facing):** what the user will notice, no internals. Example: `Fixed a freeze when leaving the editor right after cancelling an export.`
- **Internal changelog:** `MZ-14404 · <area> · <what changed technically> · ANRSan: fixes F008-52b8dc, no new findings · PR #3198`

Rules: present tense for the user line, past tense for the internal line; mention the Jira key only in the internal line; if the ANRSan delta is unknown write `ANRSan: not run`; never mention customers, devices or users by name.
