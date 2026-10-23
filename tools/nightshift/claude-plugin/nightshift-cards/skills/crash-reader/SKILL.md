---
name: crash-reader
description: "Use for MyZesty crash or ANR/freeze cards: find in the screen recording the moment the app dies or freezes, the last action before it, how long a freeze lasts, and which field crash it may match."
---

# Crash reader (MyZesty) — from the video

Crash and ANR cards are usually videos, not logs. Read the video first.

## Do
1. Find the moment it happens:
   - crash: the app disappears to the launcher or recents, an "app keeps stopping" / "has stopped" dialog, a sudden
     black screen, or the app restarts from the splash screen.
   - ANR / freeze: frames stop changing while touches keep landing (touch dots, taps on buttons with no reaction),
     an endless spinner or a progress stuck at the same %, or an "isn't responding" dialog.
2. Give the last normal frame and the first bad frame (numbers and times). For a freeze, also when it ends (or that
   it never ends) and how long it lasts.
3. Name the last action before it: screen, control, and what the user did (tap, drag, scrub, add media, export,
   apply effect, leave and return to the app). Note what was on the timeline if visible (clips, transitions, audio).
4. Only if the card attaches logs: pick the crash or ANR lines and the top of the stack and say how they line up
   with the video moment.
5. If the prompt lists field crash cases from the Night Shift board, say which ones fit (same version, screen,
   action) and why; say "none fit" when none do.

Start your answer part with the line `SKILL: crash-reader`.
