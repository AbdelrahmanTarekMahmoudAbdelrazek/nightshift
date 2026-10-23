---
name: root-cause
description: "Use after a MyZesty bug card has been read: search the given branch's code (read-only) to explain why each issue happens, with files, lines, mechanism, confidence and a fix direction."
---

# Root cause (MyZesty)

You are in a read-only checkout of the branch the developer picked. MyZesty's layers:
- Kotlin/Java UI and presenters: `app/src/main/java/com/myzesty/...` (videoEditor, managers, activities, fragments).
- JNI bridge: `app/src/main/cpp/JNI/JNI.cpp`, message looper `player/MsgLooper.cpp` (Get<> calls block the caller).
- C++ engine: `app/src/main/cpp/player/` (VideoEngine, VideoPlayer, VisualTimeLine, FramesHelper),
  `video/Renderer/` (GraphicEngine, renderers per feature: Text, Mask, overlayMask, FloatingWindow, Webp…),
  `video/decoders/` (MCDecoder), `audio/` (AudioTimeline, AudioMedia, AudioLayer, mixer, normalizer).
- AI tools and server calls are mostly Kotlin + network; a server-side failure may have no app-side root cause.

## Do, for each issue
1. Turn the issue into code words: screen and control names, feature names from the card (e.g. "Frames", "Myric",
   "Celebration Jam", "Seedance"), and what goes wrong (orientation, crop, stuck at %, crash on export…).
2. Find the entry point: Grep resource ids / strings / class names for the screen and control, then follow the call
   path down (Kotlin → JNI → engine) to where the wrong thing is decided.
3. Read the deciding code. Name the exact file and line range and explain the mechanism in plain words
   (e.g. "the frame texture is fitted to the canvas aspect ratio in X.cpp:212, so on landscape media it is laid out
   landscape; iOS keeps the asset's own portrait ratio and lets the canvas crop it").
4. For a crash / freeze, follow the last action seen in the video to code that can crash or block on that path
   (null media, race, unchecked return, a blocking Get<> on the UI thread, a wait without timeout).
5. Give a fix direction (where and what to change), not a patch. Give a confidence 0–1 and what would confirm it
   (a log line to add, a value to print, a quick lab check).
6. If the code does not explain it (server, assets, device), say so and say what evidence is missing.

Rules: read-only — never edit files. Quote only short code fragments. Do not invent files or functions; every
file:line you give must exist in this checkout. Start your answer part with `SKILL: root-cause`.
