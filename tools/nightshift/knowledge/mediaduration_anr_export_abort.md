match: eb0d37d2c7d146881b89d7a0b3859b0f, JNI_getMediaDuration, ExportManager::abort_export
source: Night Shift lab repro, 2026-10-06, SM-A515F Android 13, debug build (stress_results/20261006-163527, 2/2 runs ANR)

Reproduced automatically: tools/stress/scenarios.py run export_stuck_abort_clip_tool (debug hook
debug.zesty.hook.stall_audio_export makes the audio decoder task hang during export, like the field export frozen at 50%).
Lab ANR trace matches the field frame for frame:
- main: JNI_getMediaDuration <- MsgLooper::Get<MediaDuration> <- PlayerActivity.getMediaDurationByID
  <- PlayerActivity.onMessageEvent (OPEN_SPEED, line 5415) <- EventBus <- MainMenuFragment.setClipTools onItemClick
  (a tool in the Edit bar; Trim is commented out in this build, Speed takes the same path).
- engine message thread: MsgLooper::ProcessMessages -> VideoEngine::abort_export -> ExportManager::abort_export
  -> pthread_join on the audio export thread, which waits on AudioMCDecoder::generateFrames forever.
User path: export -> app to background (trim memory) -> back -> Cancel (MsgAbortExport) -> export screen never closes
(ExportDialog waits for ResultState.Cancel, sent only after abortExporting() returns) -> Cancel tapped again closes it
(cancelExport already set isExporting=false) -> Edit -> a clip tool -> main thread waits on the dead engine -> ANR.
Fix directions: abort_export must not join without a timeout (signal the audio thread to stop, detach/time out);
getMediaDuration needs a timeout fallback like getCurrentTime/getTotalDuration; the audio decoder wait in export
needs a stop check.

In Night Shift: the board's Reproduce button on this case runs the scenario (nightshift.yaml lab.repros, keyed by the
Crashlytics issue id) and marks it reproduced only if the lab ANR dump contains every field frame: JNI_getMediaDuration,
PlayerActivity.getMediaDurationByID, MainMenuFragment$setClipTools, ExportManager::abort_export, pthread_join,
ExportManager::export_audio_thread. Field vs lab difference: the field decoder froze inside Android MediaCodec
(AMediaCodec_dequeueOutputBuffer/dequeueInputBuffer, awaitResponse) while the app was backgrounded with memory pressure;
the lab forces that freeze with the debug hook in AudioMCDecoder::generateFrames.
