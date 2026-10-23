# Night Shift: daily use

Everything is on your board (`https://<your-project>.web.app`). Your worker does the work on your Mac; leave the Mac
on and awake (System Settings → Battery → prevent automatic sleeping while plugged in) and your phone plugged in.

## Every morning (5 min)
1. **Dashboard**: crash-free users per build, what is new or spiking since yesterday. The daily gathering runs at 08:00
   (Egypt time) by itself; **Sync now** on Crashes & ANRs runs it on demand.
2. **Crashes & ANRs**: filter by code layer (Native / Kotlin / Java), version, progress; sort by users, events, newest.
   The filter is in the page link, so you can send a filtered list to a colleague.
3. Open a problem → **Analyse** (root cause) → **Reproduce** (on your phone) → **Draft fix** (a patch checked on the
   phone). Nothing is committed; you take the patch into your own branch.

## When you open or review a PR
- **PR Review → Paste a PR link** (any repo of the project). About 15-25 minutes. Read the verdict, then answer each
  finding with **Agree / Not a problem / Ask author**: the reviewers learn from it.
- A native PR that changes JNI is checked against the Kotlin side; if the description links the Kotlin PR it ships
  with, that PR is used.

## When a Jira card comes in
- **Card Issue → paste the card** (key or link) → the root cause with the code lines, QA steps and a suggested fix.

## Audio work
- **Audio Check → your branch**: it is compared with today's code, 3 exports each; open the check, press ▶ on a cut to
  listen. Tick 2-4 checks → **Compare**.

## Your phone
- You can use your phone normally between jobs. The next phone job reinstalls its own build (and uninstalls a
  Play/release build once if needed). Don't unplug it while a Reproduce or Audio Check runs (Jobs tab shows it).

## If something looks wrong
- **Jobs** tab: every job, its log, and Cancel.
- Worker log on your Mac: `tail -f /tmp/nightshift-worker.log`.
- Restart the worker: `launchctl kickstart -k gui/$(id -u)/com.nightshift.worker`.
