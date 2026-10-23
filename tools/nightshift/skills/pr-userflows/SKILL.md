---
name: pr-userflows
description: Night Shift PR review - follow every app flow that reaches the changed code, including every way out of it
---
# User flows through the changed code

You review a pull request by following the APP, not the function. The prompt lists the Kotlin call sites of the changed
native code ("Kotlin side"); you may Read/Grep those Kotlin repos and this repo.

For each user flow that reaches the changed code (a panel, a tool, a gesture, playback, export, undo/redo, opening a
project):
1. Write the flow as the user does it: open, change, and every way it ends.
2. Follow EVERY exit, not only the happy one: Done/Apply, Cancel/Back (system back AND the panel's own cancel),
   leaving the screen (onDetach, onPause, switching tool), undo/redo afterwards, starting playback afterwards.
3. At each exit ask: is everything the user sees still consistent? The engine state (time, speed, selection) vs the
   Kotlin state (cursor, time label, selected item, saved project). Does a value the PR changes on the way in get put
   back on the way out, and does the other side (Kotlin or native) learn about it?
4. Also check the entry: what the flow does first (e.g. resetting a value to a default, pausing) can itself reach the
   changed code in a state the PR author did not think of.
Every inconsistency a user can see at the end of a flow is a scenario, with the Kotlin file:line of the exit you
followed and QA repro steps that end with that exit.
