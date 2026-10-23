---
name: card-reader
description: "Use first when reading a MyZesty Jira bug card: decide what kind of card it is (crash, ANR/freeze, wrong behaviour, visual, audio, feature card with several problems), list its issues, and what is expected."
---

# Card reader (MyZesty)

MyZesty is an Android/iOS video editor (Full Video Editor with canvas, timeline, effects, frames, text, stickers,
transitions, audio; templates; QuickCut; AI tools such as AI Video, AI Image, Ads Creator, AI Music, AI Speech).
QA cards usually carry: a platform tag in the title ([Android], [iOS], [WEB]), Environment/build, Device, Summary,
Steps to Reproduce, Actual, Expected, and one or more screen recordings.

## Do
1. Read title, description, environment, comments and the developer note (if any). The note wins over the card.
2. Decide the card kind: crash, anr (freeze / stuck / not responding / endless loading), behaviour (wrong result or
   state), visual (drawn wrong: size, crop, orientation, colour, missing item), audio, performance, other.
3. Split into issues. One problem = one issue. A card that lists several different problems (numbered, bullets,
   "also…", several videos showing different things) = several issues, numbered 1..n. Do not split one problem
   described in several ways.
4. For each issue write expected and actual in one sentence each, from the card text. If the card does not say what
   is expected, write "not stated" (do not invent).
5. Pick the route: "reproduce" (editor/engine/UI on the phone), "crash case" (crash or ANR), "audio check" (audio
   timing, gaps, repeats, stereo), "server" (AI generation or backend failure the phone cannot reproduce alone).
6. Note platform, build and device as written.

Start your answer part with the line `SKILL: card-reader`.
