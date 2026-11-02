# Night Shift auto repros for 6e2486dde1f6797760258759f18a7333


# 2026-10-28 13:52 level 3 attempt 1
def _6e2486dd_reverse_at_end(ed, r, slow=0, slow_from_start=False, storage=False, pressure=('RUNNING_CRITICAL', 'RUNNING_LOW')):
    """Field chain: clip tools open, play the ~35 s clip to the end, tap Reverse within ~1 s of MsgAtEnd (no pause),
    real (uncached) reverse runs while the Oboe callback keeps pulling layer 0."""
    ed.dev.clear_app_cache()                         # reverse output = cache/<clip name>; cached -> no MsgReverseVideo
    ed.open_fixture('6e2486dd')
    ed.idle(2)
    ed.set_playing(False)
    ed.seek_start()
    ed.clip_tools()                                  # field user had the clip selected, Reverse one tap away
    s = ed.screen()
    pos = s.find(T.REVERSE).center if (s is not None and s.has(T.REVERSE)) else None
    if slow_from_start:
        ed.dev.slow_phone(slow)                      # low-end Oppo A17: renders ~1 s, decoder TRYAGAIN, as in the field
    if storage:
        ed.dev.busy_storage(True)
    try:
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(r'AUD layer 0 underfill|AudioMedia::get_frame_at', 20, since=mark,
                       why='checkpoint 1: playback audio live on layer 0')
        ed.require_log(r'MsgAtEnd', 90, since=mark, why='checkpoint 2: playback ran to the end, no pause')
        mark = ed.log_mark()
        if pos:
            ed.dev.tap(*pos)                         # Reverse < 1 s after at_end
        else:
            ed.tap_tool('reverse')
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 8, since=mark,
                       why='checkpoint 3: Reverse sent speed/curve/trim/reverse right after at_end')
        if slow and not slow_from_start:
            ed.dev.slow_phone(slow)
        ed.require_log(r'Audio track started successfully', 10, since=mark,
                       why='checkpoint 4: real reverse with audio encode (not the cached file)')
        ed.idle(r.uniform(0.8, 1.5))
        ed.dev.sh(f'am send-trim-memory {PKG} {pressure[0]}')   # field: trim_memory_15 x2 ~1.2 s into the reverse
        ed.require_log(r'AUD callback OVERRUN|AUD layer 0 underfill', 15, since=mark,
                       why='checkpoint 5: playback callback still live during the reverse')
        ed.require_log(r'Muxer started successfully', 60, since=mark, why='checkpoint 6: reverse muxer start')
        ed.dev.sh(f'am send-trim-memory {PKG} {pressure[1]}')   # field: trim_memory_10 right before the SIGSEGV
        ed.idle(10)
    finally:
        ed.dev.slow_phone(0)
        if storage:
            ed.dev.busy_storage(False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_1_a(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): play to end -> Reverse at once, CPU slowed only during the reverse + trim memory."""
    _6e2486dd_reverse_at_end(ed, r, slow=r.randint(28, 36))


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_1_b(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): play to end -> Reverse at once, slow storage (reverse lasts longer) + trim memory."""
    _6e2486dd_reverse_at_end(ed, r, storage=True)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_1_c(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): whole field window on a low-end-slow phone (TRYAGAIN/1 s renders before at_end) -> Reverse."""
    _6e2486dd_reverse_at_end(ed, r, slow=r.randint(40, 48), slow_from_start=True, storage=r.random() < 0.5)


# 2026-10-28 14:04 level 3 attempt 2
def _6e2486dd_reverse_at_end(ed, r, slow=0, slow_from_start=False, storage=False, trims=('RUNNING_MODERATE', 'RUNNING_LOW')):
    """Field chain: the clip is selected, play the ~38 s clip to its end, tap Reverse within ~1 s of MsgAtEnd
    (no pause, no seek), a real uncached reverse runs, and the Oboe callback keeps pulling layer 0."""
    ed.dev.clear_app_cache()                         # reverse output = cacheDir/<transcode name>; a cached file skips MsgReverseVideo
    ed.open_fixture('6e2486dd')
    ed.idle(2)
    ed.set_playing(False)
    ed.seek_start()
    ed.clip_tools()                                  # Reverse is one tap away, as for the field user
    s = ed.screen()
    pos = s.find(T.REVERSE).center if (s is not None and s.has(T.REVERSE)) else None
    if slow_from_start:
        ed.dev.slow_phone(slow)                      # Oppo A17: ~1 s renders and decoder TRYAGAIN before at_end
    if storage:
        ed.dev.busy_storage(True)                    # slow storage makes the reverse encode/mux last longer
    try:
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(r'MsgResumePlaying', 10, since=mark, why='checkpoint 1: playback (Oboe audio) live on the clip')
        ed.require_log(r'MsgAtEnd', 150, since=mark, why='checkpoint 2: playback ran to the end, no pause')
        mark = ed.log_mark()
        if pos:
            ed.dev.tap(*pos)                         # field: MsgReverseVideo ~0.9 s after at_end
        else:
            ed.tap_tool('reverse')
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 8, since=mark,
                       why='checkpoint 3: Reverse sent speed/curve/trim/reverse on media 0 right after at_end')
        if slow and not slow_from_start:
            ed.dev.slow_phone(slow)                  # slow the encoder and the audio callback during the reverse
        ed.require_log(r'Audio track started successfully', 15, since=mark,
                       why='checkpoint 4: real reverse with an audio encode (not a cached file)')
        ed.idle(r.uniform(0.8, 1.5))
        for _ in range(2):                           # field: trim_memory_15 x2 ~1.2 s into the reverse (no onPause:
            ed.dev.sh(f'am send-trim-memory {PKG} {trims[0]}')   # backgrounding would abort the reverse)
            ed.idle(0.2)
        ed.require_log(r'AUD callback OVERRUN|AUD layer 0 underfill|AudioMedia::get_frame_at', 30, since=mark,
                       why='checkpoint 5: playback callback still pulling layer 0 during the reverse')
        ed.require_log(r'Muxer started successfully', 90, since=mark, why='checkpoint 6: reverse muxer start')
        ed.dev.sh(f'am send-trim-memory {PKG} {trims[1]}')       # field: trim_memory_10 right before the SIGSEGV
        ed.idle(12)
    finally:
        ed.dev.slow_phone(0)
        if storage:
            ed.dev.busy_storage(False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_2_a(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): play to end -> Reverse at once; CPU slowed only during the reverse, trim memory 15/10."""
    _6e2486dd_reverse_at_end(ed, r, slow=r.randint(30, 38))


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_2_b(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): play to end -> Reverse at once; slow storage + mild CPU load (long reverse, OVERRUN callback)."""
    _6e2486dd_reverse_at_end(ed, r, slow=r.randint(18, 26), storage=True)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_2_c(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): whole field window on a low-end-slow phone (1 s renders before at_end) -> Reverse, critical trims."""
    _6e2486dd_reverse_at_end(ed, r, slow=r.randint(36, 44), slow_from_start=True,
                             trims=('RUNNING_CRITICAL', 'RUNNING_LOW'))


# 2026-10-28 14:18 level 3 attempt 3
def _6e2486dd_reverse_in_render_lag(ed, r, slow=44, storage=False, codec=False):
    """Field chain: playback of the ~38 s clip reaches its end while the render loop lags (decoder TRYAGAIN, ~1 s renders).
    Reverse is tapped right after at_the_end (Kotlin isPlaying=false, so no MsgPausePlaying) but before the native player
    is Finished. enter_edit_state therefore saves Playing, and quit_edit_state unmutes and resumes playback: the Oboe
    callback reads layer 0 during the real reverse."""
    ed.mon.allow_death = True
    ed.dev.force_stop()                              # do not let 'leave editor' save last run's reversed draft
    ed.mon.allow_death = False
    ed.dev.clear_app_cache()                         # reverse output = cacheDir/<transcode name>; cached -> no MsgReverseVideo
    ed.open_fixture('6e2486dd')
    ed.idle(2)
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.62, 0.72))                # ~11-14 s left: the field's slow-render window was the last 12 s
    ed.clip_tools()
    s = ed.screen()
    if s is None or not s.has(T.REVERSE):
        raise UIError('Reverse tile not on the clip tool bar')
    pos = s.find(T.REVERSE).center                   # found before the CPU slowdown makes dumps slow
    try:
        if codec:                                    # another codec user: a high-bitrate screen encode until the end of the run
            ed.dev.sh('nohup screenrecord --bit-rate 40000000 --time-limit 90 /data/local/tmp/ns_codec.mp4 >/dev/null 2>&1 &')
        if storage:
            ed.dev.busy_storage(True)
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(r'MsgResumePlaying', 10, since=mark, why='checkpoint 1: playback (Oboe audio) live on layer 0')
        ed.idle(1.5)
        ed.dev.slow_phone(slow)                      # Oppo A17: renders fall ~1 s behind the clock before the end
        ed.require_log(r'MsgAtEnd', 60, since=mark, why='checkpoint 2: playback ran to the end, no pause')
        ed.dev.tap(*pos)                             # at once: Kotlin is no longer playing, the render loop still is
        ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', 15, since=mark,
                       why='checkpoint 3: Reverse sent set-speed right after at_end')
        ed.require_log(r'glTask drain abandoned \(stopRendering set\)', 8, since=mark,
                       why='checkpoint 3: the edit message caught the player still Playing (field sign; else audio stays muted)')
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 20, since=mark,
                       why='checkpoint 3: speed/curve/trim/reverse on media 0')
        ed.require_log(r'Audio track started successfully', 30, since=mark,
                       why='checkpoint 4: real reverse with an audio encode (not a cached file)')
        ed.idle(r.uniform(0.8, 1.5))
        for _ in range(2):                           # field: trim_memory_15 x2 ~1.2 s into the reverse
            ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_MODERATE')
            ed.idle(0.2)
        ed.require_log(r'AUD callback OVERRUN|AUD layer 0 underfill', 40, since=mark,
                       why='checkpoint 5: playback callback unmuted and pulling layer 0 during the reverse')
        ed.require_log(r'Muxer started successfully', 120, since=mark, why='checkpoint 6: reverse muxer start')
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')          # field: trim_memory_10 right before the SIGSEGV
        ed.idle(15)
    finally:
        ed.dev.slow_phone(0)
        if storage:
            ed.dev.busy_storage(False)
        ed.mon.allow_death = True
        ed.dev.force_stop()                          # the reversed draft must not be saved over the fixture
        ed.mon.allow_death = False


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_3_a(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): low-end CPU (1 s renders) at the clip end -> Reverse right after at_end."""
    _6e2486dd_reverse_in_render_lag(ed, r, slow=r.randint(42, 48))


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_3_b(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): slow storage + slow CPU stall the decoder at the end -> Reverse right after at_end."""
    _6e2486dd_reverse_in_render_lag(ed, r, slow=r.randint(32, 40), storage=True)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l3_3_c(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): another codec user (screen encode) + slow CPU at the end -> Reverse right after at_end."""
    _6e2486dd_reverse_in_render_lag(ed, r, slow=r.randint(36, 44), codec=True)


# 2026-10-28 14:24 level 4 attempt 1
def _6e2486dd_reverse_on_at_end(ed, r, slow=40, delay=0.0, slow_during=30, storage=False, codec=False):
    """Field chain: the ~38 s clip plays to its end while renders lag. A tap waiting ON THE PHONE (logcat -> input tap,
    no host round trip) hits Reverse 0-0.5 s after VideoEngine::at_end. The render loop is still Playing, so
    enter/quit_edit_state unmute the Oboe callback, which then reads layer 0 while the real reverse reads it too."""
    ed.open_fixture('6e2486dd')
    ed.idle(2)
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.62, 0.72))
    ed.clip_tools()
    s = ed.screen()
    if s is None or not s.has(T.REVERSE):
        raise UIError('Reverse tile not on the clip tool bar')
    x, y = s.find(T.REVERSE).center
    ed.dev.clear_app_cache()                         # after the open: no cache/<name> reversed file -> real MsgReverseVideo
    try:
        if codec:
            ed.dev.sh('nohup screenrecord --bit-rate 40000000 --time-limit 120 /data/local/tmp/ns_codec.mp4 >/dev/null 2>&1 &')
        if storage:
            ed.dev.busy_storage(True)
        mark = ed.log_mark()
        ed.dev.sh("nohup sh -c 'logcat -T 1 -m 1 -e \"VideoEngine::at_end\" >/dev/null; "
                  f"sleep {delay:.2f}; input tap {x} {y}' >/dev/null 2>&1 &")
        ed.set_playing(True)
        ed.require_log(r'MsgResumePlaying', 10, since=mark, why='checkpoint 1: playback (Oboe audio) live on layer 0')
        ed.idle(1.0)
        ed.dev.slow_phone(slow)                      # Oppo A17: ~1 s renders before the end keep the loop Playing after at_end
        ed.require_log(r'VideoEngine::at_end', 60, since=mark, why='checkpoint 2: playback ran to the end, no pause')
        ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', 20, since=mark,
                       why='checkpoint 3: the on-phone Reverse tap sent set-speed right after at_end')
        ed.require_log(r'glTask drain abandoned \(stopRendering set\)', 10, since=mark,
                       why='checkpoint 3: the edit caught the player still Playing (field sign; else the callback stays muted)')
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 20, since=mark, why='checkpoint 3: reverse on media 0')
        ed.dev.slow_phone(slow_during)               # keep the callback slow (field OVERRUN 159 ms) while the reverse runs
        ed.require_log(r'Audio track started successfully', 30, since=mark,
                       why='checkpoint 4: real reverse with an audio encode (not a cached file)')
        ed.idle(r.uniform(0.8, 1.5))
        for _ in range(2):                           # field: trim_memory_15 x2 about 1.2 s into the reverse
            ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_MODERATE')
            ed.idle(0.2)
        ed.require_log(r'AUD callback OVERRUN|AUD layer 0 underfill', 25, since=mark,
                       why='checkpoint 5: playback callback unmuted and pulling layer 0 during the reverse')
        ed.wait_log(r'Muxer started successfully', 15, since=mark)
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')   # field: trim_memory_10 right before the SIGSEGV
        ed.idle(6)
    finally:
        ed.dev.slow_phone(0)
        if storage:
            ed.dev.busy_storage(False)
        ed.mon.allow_death = True
        ed.dev.force_stop()                          # stop before REVERSE_DONE saves the draft that points at cache/
        ed.mon.allow_death = False


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_1_a(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): slow CPU at the clip end, on-phone Reverse tap 0-0.15 s after at_end."""
    _6e2486dd_reverse_on_at_end(ed, r, slow=r.randint(40, 46), delay=r.uniform(0.0, 0.15))


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_1_b(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): codec contention (screen encode) + CPU load, Reverse 0.2-0.5 s after at_end (field 0.9 s)."""
    _6e2486dd_reverse_on_at_end(ed, r, slow=r.randint(34, 40), delay=r.uniform(0.2, 0.5), codec=True)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_1_c(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): slow storage + CPU stall the decoder at the end, Reverse 0.1-0.3 s after at_end, heavy load during the reverse."""
    _6e2486dd_reverse_on_at_end(ed, r, slow=r.randint(36, 42), delay=r.uniform(0.1, 0.3), slow_during=40, storage=True)


# 2026-10-28 14:27 level 4 attempt 2
def _6e2486dd_fresh_project(ed):
    """Durable setup (the fx_6e2486dd snapshot points at a deleted cache/transcoding-*.mp4): a new project from the
    long clip WITH audio pushed to the top of the gallery, single clip on layer 0 (media 0)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    ed.dev.restore_env()
    ed.dev.clear_app_cache()                         # no stale reversed output; no project references cache/ yet
    push_newest_video(ed)                            # repro_assets/with_audio.mov: long clip, AAC audio, newest in gallery
    ed.dev.launch()
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    mark = ed.log_mark()
    ed.create_draft()
    ed.require_log(r'MsgAddVideo: media_layer 0 path', 60, since=mark, why='checkpoint 1: clip loaded on layer 0')
    if ed.wait_log(r'add_video Failed|media_id is out of range|test_ve_on_stop', 4, since=mark):
        raise UIError('setup: the clip did not load / PlayerActivity closed (not the field state)')
    ed.idle(3)


def _6e2486dd_reverse_race(ed, r, slow, delay, slow_during, storage=False, codec=False):
    """Play the clip to its end under a slowed CPU (Oppo A17: ~1 s renders), an on-phone tap hits Reverse `delay` s
    after VideoEngine::at_end while the render loop is still Playing, so the Oboe callback is unmuted and reads the
    layer 0 queue while the reverse export's get_frames_at(in_export) reads/reseeks it."""
    _6e2486dd_fresh_project(ed)
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.70, 0.80))
    ed.clip_tools()
    s = ed.screen()
    if s is None or not s.has(T.REVERSE):
        raise UIError('Reverse tile not on the clip tool bar')
    x, y = s.find(T.REVERSE).center
    try:
        if codec:
            ed.dev.sh('nohup screenrecord --bit-rate 40000000 --time-limit 120 /data/local/tmp/ns_codec.mp4 >/dev/null 2>&1 &')
        if storage:
            ed.dev.busy_storage(True)
        mark = ed.log_mark()
        ed.dev.sh("nohup sh -c 'logcat -T 1 -m 1 -e \"VideoEngine::at_end\" >/dev/null; "
                  f"sleep {delay:.2f}; input tap {x} {y}' >/dev/null 2>&1 &")
        ed.set_playing(True)
        ed.require_log(r'MsgResumePlaying', 10, since=mark, why='checkpoint 1: playback (Oboe audio) live on layer 0')
        ed.idle(1.0)
        ed.dev.slow_phone(slow)
        ed.require_log(r'VideoEngine::at_end', 90, since=mark, why='checkpoint 2: playback ran to the end, no pause')
        ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', 20, since=mark, why='checkpoint 3: Reverse right after at_end')
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 20, since=mark, why='checkpoint 3: reverse on media 0')
        ed.dev.slow_phone(slow_during)               # field OVERRUN 159 ms: slow callback during the reverse
        ed.require_log(r'Audio track started successfully', 30, since=mark, why='checkpoint 4: real reverse with audio encode')
        if not ed.wait_log(r'glTask drain abandoned \(stopRendering set\)', 1, since=mark):
            ed.log('    edit did not catch the player Playing: callback likely muted this run')
        ed.idle(r.uniform(0.8, 1.5))
        for _ in range(2):                           # field: trim_memory_15 x2 ~1.2 s into the reverse
            ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_MODERATE')
            ed.idle(0.2)
        ed.require_log(r'AUD callback OVERRUN|AUD layer 0 underfill', 25, since=mark,
                       why='checkpoint 5: playback callback unmuted and pulling layer 0 during the reverse')
        ed.wait_log(r'Muxer started successfully', 30, since=mark)
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')   # field: trim_memory_10 right before the SIGSEGV
        ed.idle(8)
    finally:
        ed.dev.slow_phone(0)
        if storage:
            ed.dev.busy_storage(False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_2_a(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): fresh durable project, slow CPU at the end, Reverse 0-0.15 s after at_end."""
    _6e2486dd_reverse_race(ed, r, slow=r.randint(40, 46), delay=r.uniform(0.0, 0.15), slow_during=30)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_2_b(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): field gap (Reverse 0.6-0.9 s after at_end) on a very slow CPU so the loop is still Playing."""
    _6e2486dd_reverse_race(ed, r, slow=r.randint(44, 48), delay=r.uniform(0.6, 0.9), slow_during=38)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_2_c(ed, r):
    """Firebase 2026-10-22 + Play Oppo A17 (6e2486dd): slow storage + codec contention stretch the reverse (field >7 s), Reverse 0.1-0.4 s after at_end."""
    _6e2486dd_reverse_race(ed, r, slow=r.randint(36, 42), delay=r.uniform(0.1, 0.4), slow_during=40, storage=True, codec=True)


# 2026-10-28 14:38 level 4 attempt 3
def _6e2486dd_reverse_at_end(ed, r, slow, delay, slow_during, storage=False):
    """Shared field chain: fixture clip plays to its end under CPU load; an on-phone tap (logcat -> input tap, no host
    round trip) hits Reverse `delay` s after VideoEngine::at_end, so enter/quit_edit_state still see Playing and unmute
    the Oboe callback, which reads layer 0 while reverse_audio_thread's get_frames_at(in_export) reads/reseeks it."""
    ed.dev.clear_app_cache()                         # cacheDir/<clip name> existing -> no real reverse (PlayerActivity:5288)
    ed.open_fixture('6e2486dd')
    ed.idle(2)
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.70, 0.80))
    ed.clip_tools()
    s = ed.screen()
    if s is None or not s.has(T.REVERSE):
        raise UIError('Reverse tile not on the clip tool bar')
    x, y = s.find(T.REVERSE).center
    if storage:
        ed.dev.busy_storage(True)
    mark = ed.log_mark()
    ed.dev.sh("nohup sh -c 'logcat -T 1 -m 1 -e \"VideoEngine::at_end\" >/dev/null; "
              f"sleep {delay:.2f}; input tap {x} {y}' >/dev/null 2>&1 &")
    ed.set_playing(True)
    ed.require_log(r'MsgResumePlaying', 10, since=mark, why='checkpoint 1: playback (Oboe audio) live on layer 0')
    ed.idle(1.0)
    ed.dev.slow_phone(slow)                          # Oppo A17: ~1 s renders keep the loop Playing past at_end
    ed.require_log(r'VideoEngine::at_end', 90, since=mark, why='checkpoint 2: playback ran to the end, no pause')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', 20, since=mark, why='checkpoint 3: Reverse right after at_end')
    ed.require_log(r'glTask drain abandoned \(stopRendering set\)', 10, since=mark,
                   why='checkpoint 3/5: edit caught the player Playing -> quit_edit_state unmutes the callback')
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 20, since=mark, why='checkpoint 3: reverse on media 0')
    ed.dev.slow_phone(slow_during)                   # field OVERRUN 159 ms: slow callback during the reverse
    ed.require_log(r'Audio track started successfully', 30, since=mark, why='checkpoint 4: real reverse with audio encode')
    return mark


def _6e2486dd_cleanup(ed, storage=False):
    ed.dev.slow_phone(0)
    if storage:
        ed.dev.busy_storage(False)
    ed.mon.allow_death = True
    ed.dev.force_stop()                              # the reversed draft (cache/ path) must not be saved over the fixture
    ed.mon.allow_death = False


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_3_a(ed, r):
    """Firebase 2026-10-22 OPPO CPH2477 + Play Oppo A17 (6e2486dd): Reverse 0-0.3 s after at_end, reverse runs to its end (finish reset_layer_queue)."""
    try:
        mark = _6e2486dd_reverse_at_end(ed, r, slow=r.randint(40, 46), delay=r.uniform(0.0, 0.3), slow_during=30)
        for _ in range(2):                           # field: trim_memory_15 x2 ~1.2 s into the reverse
            ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_MODERATE')
            ed.idle(0.2)
        ed.require_log(r'Muxer started successfully', 60, since=mark, why='checkpoint 4: reverse muxer start')
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')   # field: trim_memory_10 right before the SIGSEGV
        ed.wait_log(r'Muxer stopped successfully', 40, since=mark)   # finish: reset/replace while the callback is live
        ed.idle(5)
    finally:
        _6e2486dd_cleanup(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_3_b(ed, r):
    """Firebase 2026-10-22 OPPO CPH2477 + Play Oppo A17 (6e2486dd): Reverse right after at_end, then the dialog's X aborts it mid-encode (abortReverse vs live callback)."""
    try:
        _6e2486dd_reverse_at_end(ed, r, slow=r.randint(40, 46), delay=r.uniform(0.1, 0.5), slow_during=34)
        ed.idle(r.uniform(3.0, 7.0))                 # field crash ~8 s in: abort inside that window
        ed.dev.slow_phone(0)                         # dumps must work to find the X
        ed.ui.tap('id:img_close', timeout=8)         # VideoReverse.kt:80 -> Player.abortReverse()
        ed.idle(1.0)
        ed.set_playing(True)                         # playback back on the half-torn layer 0 queue
        ed.idle(4)
        ed.set_playing(False)
    finally:
        _6e2486dd_cleanup(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l4_3_c(ed, r):
    """Firebase 2026-10-22 OPPO CPH2477 + Play Oppo A17 (6e2486dd): field gap (0.6-0.9 s after at_end) with slow storage + heavy CPU through the whole reverse."""
    try:
        mark = _6e2486dd_reverse_at_end(ed, r, slow=r.randint(44, 48), delay=r.uniform(0.6, 0.9),
                                        slow_during=r.randint(40, 46), storage=True)
        ed.idle(1.2)
        for _ in range(2):
            ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_MODERATE')
            ed.idle(0.2)
        if ed.wait_log(r'AUD callback OVERRUN|AUD layer 0 underfill', 20, since=mark):
            ed.log('    checkpoint 5 seen: callback starving during the reverse, as in the field')
        ed.require_log(r'Muxer started successfully', 90, since=mark, why='checkpoint 4: reverse muxer start')
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')
        ed.wait_log(r'Muxer stopped successfully', 60, since=mark)
        ed.idle(5)
    finally:
        _6e2486dd_cleanup(ed, storage=True)


# 2026-10-28 14:43 level 5 attempt 1
def _6e2486dd_durable_project(ed):
    """Fixture fx_6e2486dd points at a deleted cache/transcoding-*.mp4: build the same state from a durable clip."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    ed.dev.restore_env()
    ed.dev.clear_app_cache()                         # no cache/<name> reversed file -> real MsgReverseVideo
    push_newest_video(ed)                            # long clip WITH AAC audio, newest in the gallery
    ed.dev.launch()
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    mark = ed.log_mark()
    ed.create_draft()
    ed.require_log(r'MsgAddVideo: media_layer 0 path', 60, since=mark, why='checkpoint 1: clip on layer 0 media 0')
    if ed.wait_log(r'add_video Failed|media_id bigger than visual|container_size=0|test_ve_on_stop', 4, since=mark):
        raise UIError('setup: clip did not load / PlayerActivity closed')
    ed.idle(3)


def _6e2486dd_reverse_after_end(ed, r, delay, slow_during=0):
    """Play to the end, an on-phone tap hits Reverse `delay` s after at_end (field 0.9 s); the hook keeps the
    Oboe callback live during the reverse, as the field OVERRUN shows."""
    _6e2486dd_durable_project(ed)
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.80, 0.88))
    ed.clip_tools()
    s = ed.screen()
    if s is None or not s.has(T.REVERSE):
        raise UIError('Reverse tile not on the clip tool bar')
    x, y = s.find(T.REVERSE).center
    ed.dev.setprop('debug.zesty.hook.live_audio_reverse', '1')
    mark = ed.log_mark()
    ed.dev.sh("nohup sh -c 'logcat -T 1 -m 1 -e \"VideoEngine::at_end\" >/dev/null; "
              f"sleep {delay:.2f}; input tap {x} {y}' >/dev/null 2>&1 &")
    ed.set_playing(True)
    ed.require_log(r'MsgResumePlaying', 10, since=mark, why='checkpoint 1: playback live')
    ed.require_log(r'VideoEngine::at_end', 90, since=mark, why='checkpoint 2: played to the end, no pause')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', 20, since=mark, why='checkpoint 3: Reverse tapped')
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 20, since=mark, why='checkpoint 3: reverse media 0')
    ed.require_log(r'ZHOOK live_audio_reverse', 10, since=mark, why='checkpoint 5: callback unmuted during reverse')
    if slow_during:
        ed.dev.slow_phone(slow_during)               # field OVERRUN 159 ms: a slow callback widens the overlap
    ed.require_log(r'Audio track started successfully', 30, since=mark, why='checkpoint 4: real reverse audio encode')
    return mark


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l5_1_a(ed, r):
    """Firebase 2026-10-22 OPPO CPH2477 + Play Oppo A17: Reverse ~0.9 s after at_end, live callback vs reverse caching reads until the muxer starts."""
    try:
        mark = _6e2486dd_reverse_after_end(ed, r, delay=r.uniform(0.6, 1.0))
        for _ in range(2):                           # field trim_memory_15 x2
            ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_MODERATE')
            ed.idle(0.2)
        ed.wait_log(r'Muxer started successfully', 40, since=mark)
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')   # field trim_memory_10 just before the SIGSEGV
        ed.idle(8)
    finally:
        ed.dev.setprop('debug.zesty.hook.live_audio_reverse', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l5_1_b(ed, r):
    """Firebase 2026-10-22 OPPO CPH2477 + Play Oppo A17: same chain on a slow CPU during the reverse (field OVERRUN), Reverse 0.2-0.6 s after at_end."""
    try:
        mark = _6e2486dd_reverse_after_end(ed, r, delay=r.uniform(0.2, 0.6), slow_during=r.randint(30, 40))
        ed.wait_log(r'Muxer started successfully', 60, since=mark)
        ed.idle(10)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.setprop('debug.zesty.hook.live_audio_reverse', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l5_1_c(ed, r):
    """Firebase 2026-10-22 OPPO CPH2477 + Play Oppo A17: reverse runs to its end; finish reset_layer_queue + replace while the callback is live."""
    try:
        mark = _6e2486dd_reverse_after_end(ed, r, delay=r.uniform(0.5, 1.0))
        ed.require_log(r'Muxer started successfully', 60, since=mark, why='checkpoint 4: reverse muxer start')
        ed.wait_log(r'MsgReplaceVideo|Muxer stopped', 60, since=mark)
        ed.idle(6)
    finally:
        ed.dev.setprop('debug.zesty.hook.live_audio_reverse', '0')


# 2026-10-28 15:05 level 5 attempt 3
_6e2486dd_HOOK = 'debug.zesty.hook.reverse_audio_race'


def _6e2486dd_reverse_at_end(ed, r, hook, delay, slow_during=0):
    """Fixture clip plays to its end; an on-phone tap hits Reverse `delay` s after at_end (no pause, as in the field)."""
    ed.open_fixture('6e2486dd')
    ed.idle(2)
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.80, 0.88))
    ed.clip_tools()
    s = ed.screen()
    if s is None or not s.has(T.REVERSE):
        raise UIError('Reverse tile not on the clip tool bar')
    x, y = s.find(T.REVERSE).center
    ed.dev.setprop(_6e2486dd_HOOK, hook)
    mark = ed.log_mark()
    ed.dev.sh("nohup sh -c 'logcat -T 1 -m 1 -e \"VideoEngine::at_end\" >/dev/null; "
              f"sleep {delay:.2f}; input tap {x} {y}' >/dev/null 2>&1 &")
    ed.set_playing(True)
    ed.require_log(r'MsgResumePlaying', 10, since=mark, why='checkpoint 1: playback (Oboe) live on layer 0')
    ed.require_log(r'VideoEngine::at_end', 90, since=mark, why='checkpoint 2: played to the end, no pause')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', 20, since=mark, why='checkpoint 3: Reverse tapped')
    if hook == '1':
        ed.require_log(r'glTask drain abandoned \(stopRendering set\)', 10, since=mark,
                       why='checkpoint 5 (natural): edit caught the player Playing -> callback unmuted')
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0', 20, since=mark, why='checkpoint 3: reverse media 0')
    if slow_during:
        ed.dev.slow_phone(slow_during)
    ed.require_log(r'Audio track started successfully', 30, since=mark, why='checkpoint 4: real reverse audio encode')
    ed.require_log(r'ZHOOK reverse_audio_race: 2 readers', 30, since=mark,
                   why='checkpoint 5: playback callback and reverse thread inside getSamples together')
    return mark


def _6e2486dd_cleanup(ed):
    ed.dev.slow_phone(0)
    ed.dev.setprop(_6e2486dd_HOOK, '0')
    ed.mon.allow_death = True
    ed.dev.force_stop()                              # do not save the reversed (cache/) draft
    ed.mon.allow_death = False


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l5_3_a(ed, r):
    """Firebase OPPO CPH2477 + Play Oppo A17 (6e2486dd): natural unmute (Reverse <0.4 s after at_end), hook only widens the getSamples window."""
    try:
        mark = _6e2486dd_reverse_at_end(ed, r, '1', r.uniform(0.0, 0.4))
        ed.wait_log(r'Muxer started successfully', 60, since=mark)
        ed.idle(6)
    finally:
        _6e2486dd_cleanup(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l5_3_b(ed, r):
    """Firebase OPPO CPH2477 + Play Oppo A17 (6e2486dd): field gap (0.7-1.0 s), callback held live, trim_memory 15 x2 then 10 during the reverse."""
    try:
        mark = _6e2486dd_reverse_at_end(ed, r, '2', r.uniform(0.7, 1.0))
        for _ in range(2):
            ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_MODERATE')
            ed.idle(0.2)
        ed.wait_log(r'Muxer started successfully', 60, since=mark)
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')
        ed.idle(6)
    finally:
        _6e2486dd_cleanup(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_l5_3_c(ed, r):
    """Firebase OPPO CPH2477 + Play Oppo A17 (6e2486dd): slow CPU through the reverse (field OVERRUN), runs to the finish reset_layer_queue."""
    try:
        mark = _6e2486dd_reverse_at_end(ed, r, '2', r.uniform(0.3, 0.9), slow_during=r.randint(28, 36))
        ed.wait_log(r'Muxer started successfully', 60, since=mark)
        ed.wait_log(r'Muxer stopped|MsgReplaceVideo', 60, since=mark)
        ed.idle(4)
    finally:
        _6e2486dd_cleanup(ed)
