---
name: steps-writer
description: "Use last when reading a MyZesty bug card: write exact, lab-ready steps for each issue with Expected and Actual, using the real screen and control names seen in the video."
---

# Steps writer (MyZesty)

## Do
1. One list of steps per issue. Start from the app's home screen or "an open project with …" and say what media is
   needed (landscape or portrait video, image, length, number of clips) when it matters.
2. Use the screen and control names from the video reader, in the order seen in the video. One action per step:
   tap, drag, scrub to a time, wait for loading, play, export.
3. Include the timing or state that makes it happen if the video or card shows it (e.g. "while still dragging,
   scrub the timeline", "export a second time without restarting").
4. Write the numbers the video shows: how many clips and their lengths, the playhead time when the action starts,
   the value set (speed 20x, volume 0 %), the total length. A bug that depends on where the playhead is or how long a
   clip is cannot be reproduced without them.
5. End with "Expected: …" and "Actual: …".
6. Add a confidence 0–1 and one hint on what makes it more likely to reproduce.
7. Never add steps you did not see or read. If a step is a guess, write "(guess)" after it.
8. Steps are MyZesty steps only, from the MyZesty video. A reference video from another app (CapCut...) never gives a
   step: use it only for Expected ("as in CapCut: the mask stays centred on the face").

Start your answer part with the line `SKILL: steps-writer`.
