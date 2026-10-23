# Team knowledge

What engineers already know about a crash (from Slack, QA, a repro on a phone) goes here, one file per problem.
Night Shift feeds every matching file into the root-cause analysis as verified ground truth, and re-analyses the
problem automatically on the next sync when a file is added or changed.

Format: a `match:` line with comma-separated strings (function names, Crashlytics/Play issue ids). A problem
matches when any string appears in its title, stack or ids. Everything after the first blank line is the knowledge.
The note typed in the board's "PR & notes" tab is used the same way.
