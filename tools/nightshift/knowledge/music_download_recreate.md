match: MusicTracksRepository, downloadMusicTrack, Flow exception transparency is violated
source: Night Shift lab repro, 2026-10-06, SM-A515F Android 13, dev build 1.11.0-productionInternal (repro_slideshow_20261006_130512/try_3)

Found while reproducing the get_media_starting_time crash: rotating the screen while a slideshow template loads
destroyed and recreated the engine twice in 4 s, then the app died in Java, not native:
- java.lang.IllegalStateException: Flow exception transparency is violated, at
  MusicTracksRepository.downloadMusicTrack (MusicTracksRepository.kt:183). The template's music download emits into a
  collector that belongs to the destroyed screen; that emit throws a NullPointerException, and the code then emits
  Error(...) from inside its catch block, which kotlinx.coroutines forbids. The fix direction is Flow.catch { } instead
  of emitting from a catch, and a collector scoped to the screen lifecycle.
- Then CrashCatcher.onCrash (CrashCatcher.kt:92) calls Toast.makeText on a coroutine worker thread ("Can't toast on a
  thread that has not called Looper.prepare()"), a second crash inside the crash handler.
Same trigger as the native crash: screen rebuilt while the template is loading.
