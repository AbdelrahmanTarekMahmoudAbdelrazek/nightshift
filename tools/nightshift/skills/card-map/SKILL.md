---
name: card-map
description: Night Shift card review - map each issue of a Jira card to the code it runs (screen, handler, JNI, engine functions)
---
# Map the card to the code

You get a Jira card that Night Shift already read: its issues, the steps, and EVERY frame of the screen recording with
what it shows (BUG marks the frames where the bug is visible). You run in a read-only checkout of the branch to check
(the native app: JNI, looper, engine, renderer, audio). The app's Kotlin repos are listed under "Kotlin side": Read and
Grep them too. Do NOT look for the cause yet. Find WHERE each issue lives, so the hunters start in the right place.

For each issue:
1. Turn the user's words into code words: the screen, panel, button, slider, gesture or toast text. Grep string
   resources, layout ids and class names in the Kotlin repos (fragments, activities, presenters).
2. Take the LAST user actions before the first BUG frame (drag the slider, tap Done, press the phone's Back button,
   tap Play, select a clip) and find their handlers. Follow each one down: Kotlin handler → `external fun` in
   Player.kt (java-common) → `JNI_*` in app/src/main/cpp/JNI/JNI.cpp → MsgLooper message → engine function.
3. List the native functions on that path: name, the file and line where it is defined, which thread runs it, and
   its main callers (file:line).
4. If an issue clearly does not live in app code (a server answer, an asset, the device), say so in not_in_code.

Facts only: every file:line you give must be one you opened. Never invent a caller. Keep it short: this is a map, not
an analysis.

## Answer
ONLY a ```json block:
{"issues": [{"n": 1, "screens": ["Speed panel"], "actions": [{"action": "drag the speed slider", "file": "path", "line": 0,
  "code": "the line, copied", "calls": "Player.setVideoSpeed(...)"}], "native": ["set_video_speed"]}],
 "functions": [{"name": "VideoEngine::set_video_speed", "file": "app/src/main/cpp/player/VideoEngine.cpp", "line": 0,
  "callers": ["MsgLooper.cpp:1228"], "thread": "engine looper"}],
 "threads": ["one line per thread that matters: who runs what"],
 "not_in_code": [{"n": 2, "why": ""}]}
