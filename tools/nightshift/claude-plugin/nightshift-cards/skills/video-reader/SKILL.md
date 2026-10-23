---
name: video-reader
description: "Use when a MyZesty bug card has screen recordings: watch every video frame by frame, label each video (bug, reference, other), find where each issue shows, and compare with a reference when one exists."
---

# Video reader (MyZesty)

You get contact sheets: 12 frames per image, left to right, top to bottom, numbered across ALL videos, with each
frame's video and time given in the prompt. Open every sheet with the Read tool before answering.

## Screens and controls (use these names)
Home ("New Project", "My Projects", drafts) · Full editor (canvas on top, timeline below, bottom toolbar: Edit,
Effects, Text, Stickers, Audio, Overlay, Filters, Canvas…) · Effects panel (tab row: Blur, Party, Glitch, Frames,
Romance…; thumbnail grid; the applied item is highlighted) · gallery picker · export dialog and done screen ·
templates and QuickCut screens · AI tool screens (model picker, prompt, generate, My AI Library). If the prompt
gives a screen map, prefer its names.

## Do
1. Label each video: "bug" (shows the problem), "reference" (how it should look: another app such as CapCut,
   InShot or VN, iOS, an older build, a design, another device), or "other". Use the card text (e.g. "not as CapCut",
   "iOS reference"), the attachment names and what you see (another app's UI, logo or watermark). Give each video's
   app ("MyZesty", "CapCut"...). Frames of a reference video are never bug=true.
2. For every frame, one short sentence: what changed since the previous frame (screen, finger, dialog, playhead,
   what is drawn or missing). "No change" is fine. Name the screen and the control touched.
3. For each issue from card-reader: the video, the time range (from/to) and the frames where it shows. Mark bug=true
   only where it first appears or changes, never on every following "no change" frame.
4. If there is a reference video, line up the same moment in both (same screen, same item applied, same playhead)
   and compare concretely: orientation (portrait/landscape), scale, crop, position, colour, timing, missing items.
   The difference is the bug. With another app as the reference, line up the same ACTION (the same mask, effect or
   gesture), not the same time: the two apps' screens differ, only the result matters. Put the reference frames that
   show the expected result in the issue's ref_frames, and write expected from the reference and actual from MyZesty.
   With no reference video, compare with the card's expected text only.
5. Describe only what is visible; say "unclear" when you cannot tell. Never guess at code.

Start your answer part with the line `SKILL: video-reader`.
