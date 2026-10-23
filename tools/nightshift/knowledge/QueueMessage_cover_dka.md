match: MsgLooper::QueueMessage, b0624779923c1f52e97b73f75b8c5950
source: engineer (a.tarek), 14 Oct 2026; Night Shift found and reproduced this trigger earlier (recipe ns_b0624779_l3_2_a, level 3)

How the 1.25.1 null-looper crash (SIGSEGV fault 0x30 in pthread_mutex_lock <- MsgLooper::QueueMessage <- MsgLooper::Set<unsigned long> <- JNI_seekTo) happens:
the user changes the video's thumbnail COVER while the editor's engine is already gone.

0. ORDER (from the 14 Oct lab runs):
   a. Get into the main editor with the test project: open_draft (live agent) / ed.open_draft() (recipe). Do NOT create
      a project through the gallery picker with "Don't keep activities" on: the picker never returns (live run 18:46,
      32 actions stuck in the gallery), and the QuickCut flow crashes on recreate (InflateException).
   b. Then switch "Don't keep activities" ON (reclaim_activities on / ed._dka_ui(True)); it goes through the Settings
      app, so the editor is destroyed meanwhile: `resume` (ed.dev.launch()) brings PlayerActivity back, recreated.
   c. Pause, tap the Cover thumbnail, drag the Cover filmstrip (steps 2-3 below).
1. Turn on Developer options > "Don't keep activities" (low-RAM phones do the same under memory pressure). On the
   realme only the Settings switch takes effect (`settings put` alone does not): ed._dka_ui(True) in a recipe,
   reclaim_activities {"on": true} in the live agent. Switch it OFF at the end.
2. In the editor (PlayerActivity) pause playback, then tap the Cover thumbnail on the track (id:cover_thumbnail).
   CoverActivity opens (id:timeline). PlayerActivity stops and, with Don't keep activities, is destroyed behind it:
   destroyPlayerAsync -> MsgDestroyPlayer -> JNIHelper's Looper becomes nullptr ('~MsgLooper ended' in the log).
3. Keep dragging the Cover filmstrip seek box (id:timeline) for 2.5-4 s: every move -> seekPreview -> JNI_seekTo on the
   seek thread -> getLooper() returns nullptr -> QueueMessage on a null looper -> fault 0x30.
   (A send-trim-memory RUNNING_CRITICAL before opening Cover helps.)
Related field entry points with the same window: Cover then Home (JNI_onSurfaceDestroyed); export dialog + Home + quick
return (JNI_isInBackgroundState from ExportDialog.onResume).
