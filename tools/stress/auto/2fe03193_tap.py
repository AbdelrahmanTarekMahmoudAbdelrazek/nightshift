# Night Shift tap repros for 2fe03193209d272d69500de7526df59f (from the engine repro + full field log)


# 2026-11-02 15:10 attempt 1
import re

FIX = '6e2486dd'   # ~38 s clip with AAC audio on layer 0, fresh transcode, not reversed


def _open_clean(ed):
    ed.dev.clear_app_cache()                         # no cache/<name> left from earlier runs: the 1st reverse must really run
    t0 = ed.log_mark()
    ed.open_fixture(FIX)
    ed.require_log(r'MsgAddVideo: media_layer 0 ', timeout=30, since=t0, why='fixture clip loaded on layer 0')
    ed.idle(3)
    ed.set_playing(False)
    return t0


def _reverse_tap(ed, why):
    ed.clip_tools()
    ed.menu_tap('reverse')                           # REVERSE handler: speed 1, curve 0, trim 0..originalDuration
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, why=why + ': speed reset')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=10, why=why + ': trim reset')


def _abort_by_home(ed, r, run_s):
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=15,
                   why='1st reverse really runs (dialog up)')
    ed.idle(r.uniform(*run_s))                       # let it write part of cache/<name>
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')                       # onPause -> JobLifecycleObserver: abortReverse, file NOT deleted
    ed.require_log(r'MsgAbortReverse', timeout=10, why='reverse aborted by onPause, partial file left')
    ed.idle(r.uniform(1.5, 3))
    ed.dev.launch()                                  # back to the same editor task
    ed.idle(3)
    ed.mon.allow_death = False


def _field_drags_then_trigger(ed, r):
    ed.step('field: Edit tool, drag the clip on the canvas')
    ed.clip_tools()
    for _ in range(r.randint(2, 4)):
        ed.dev.swipe(540, 700, 540 + r.randint(-250, 250), 700 + r.randint(-150, 150), r.randint(300, 700))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=8, why='canvas drag reaches engine')
        ed.idle(r.uniform(0.3, 0.8))
    ed.step('TRIGGER: Reverse again -> cached branch replaces with the partial file')
    _reverse_tap(ed, 'trigger reverse')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/transcoding-', timeout=10,
                   why='cached-file branch (no dialog) sends MsgReplaceVideo')
    ed.idle(6)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a(ed, r):
    """FULL: [libmedia.so] SIGSEGV in AudioMCDecoder::reset_state via replace_media: Reverse, leave mid-reverse, Reverse again."""
    _open_clean(ed)
    ed.step('Reverse #1 (real reverse starts)')
    _reverse_tap(ed, 'reverse #1')
    _abort_by_home(ed, r, (2.0, 5.0))
    _field_drags_then_trigger(ed, r)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b(ed, r):
    """HYBRID: [libmedia.so] reset_state SIGSEGV: partial cache/<name> made by engine reverse+abort, trigger = real Reverse tap."""
    t0 = _open_clean(ed)
    line = ed.wait_log(r'MsgAddVideo: media_layer 0 \S* ?path:? \S+', 10, since=t0)
    m = re.search(r'path:? (\S+)', line or '')
    if not m:
        raise UIError('clip path not found in MsgAddVideo line')
    cache_path = '/data/user/0/com.myzesty/cache/' + m.group(1).rsplit('/', 1)[-1]
    ed.step(f'HYBRID: partial reverse into {cache_path}')
    ed.jni(f'reverseVideo(0, "{cache_path}");sleep({r.randint(2000, 5000)});abortReverse()')   # HYBRID
    ed.require_log(r'MsgAbortReverse', timeout=20, why='HYBRID partial reverse aborted')       # HYBRID
    ed.idle(2)
    _field_drags_then_trigger(ed, r)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c(ed, r):
    """FULL: [libmedia.so] reset_state SIGSEGV on a slow low-end phone: early abort leaves a shorter partial reverse file."""
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dev.busy_storage(True)
        _open_clean(ed)
        ed.step('Reverse #1 on a slow phone')
        _reverse_tap(ed, 'reverse #1 (slow)')
        _abort_by_home(ed, r, (0.8, 3.0))
        _field_drags_then_trigger(ed, r)
    finally:
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)


# 2026-11-02 15:12 attempt 2
import re

CACHE = '/data/user/0/com.myzesty/cache/'


def _make_project(ed, r, tag):
    ed.step('new clean project from a fresh phone video, saved, reopened as the first draft')
    ed.new_project(tag=tag, duration_s=r.randint(25, 40))
    ed.leave_editor()                                  # saved: it is now the FIRST item in My Projects
    return _reopen(ed)


def _reopen(ed):
    t0 = ed.log_mark()
    ed.open_draft()
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: [^,]+,', timeout=30, since=t0, why='clip loaded on layer 0')
    ed.idle(3)
    ed.set_playing(False)
    m = re.search(r'path: ([^,]+),', line or '')
    return CACHE + m.group(1).rsplit('/', 1)[-1] if m else None


def _cache_state(ed, cache):
    if cache:
        out = ed.dev.sh(f'run-as com.myzesty ls -l {cache} 2>&1', timeout=10)
        ed.log(f'    reversed cache file: {out.strip()[:160]}')
        return 'No such file' not in out
    return None


def _reverse_tap(ed, why):
    t0 = ed.log_mark()
    ed.clip_tools()
    ed.tap_tool('reverse')                             # Constants.REVERSE: speed 1, curve 0, trim 0..originalDuration
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, since=t0, why=why + ': speed reset')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=10, since=t0, why=why + ': trim reset')
    return t0


def _reverse_then_die(ed, r, run_s):
    t0 = _reverse_tap(ed, 'reverse #1')
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=15, since=t0,
                   why='1st reverse really runs (no cached file yet)')
    ed.idle(r.uniform(*run_s))                         # engine writes part of cache/<name>
    ed.step('app process dies mid-reverse: CANCEL_REVERSE never deletes the partial file')
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.idle(2)
    ed.dev.launch()
    ed.idle(4)
    ed.mon.allow_death = False


def _drags_then_trigger(ed, r, cache):
    ed.step('field: Edit tool, drag the clip on the canvas')
    t0 = ed.log_mark()
    ed.clip_tools()
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=t0, why='Edit tool opened (free crop)')
    s = ed.screen()
    cx, cy = s.find(('id:surface_view',)).center if s is not None and s.has(('id:surface_view',)) else (360, 450)
    for _ in range(r.randint(2, 4)):
        ed.dev.swipe(cx, cy, cx + r.randint(-180, 180), cy + r.randint(-120, 120), r.randint(300, 700))
        ed.wait_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x -?0\.\d*[1-9]', 5)
        ed.idle(r.uniform(0.3, 0.8))
    _cache_state(ed, cache)
    ed.step('TRIGGER: Reverse -> cached branch swaps in the partial (no-audio) file')
    t1 = _reverse_tap(ed, 'trigger reverse')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=10, since=t1,
                   why='cached-file branch (no dialog) sends MsgReplaceVideo')
    ed.idle(6)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_a(ed, r):
    """FULL: [libmedia.so] SIGSEGV AudioMCDecoder::reset_state via replace_media: Reverse, app dies mid-reverse, reopen, Reverse."""
    _make_project(ed, r, 'ns_rev_a')
    _reverse_then_die(ed, r, (1.5, 5.0))
    cache = _reopen(ed)
    _drags_then_trigger(ed, r, cache)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_b(ed, r):
    """HYBRID: [libmedia.so] reset_state SIGSEGV: partial cache/<name> made by engine reverse+abort, trigger = real Reverse tap."""
    cache = _make_project(ed, r, 'ns_rev_b')
    if not cache:
        raise UIError('clip path not found in MsgAddVideo line')
    ed.step(f'HYBRID: partial engine reverse into {cache}, aborted (no app-side delete)')
    ed.jni(f'reverseVideo(0, "{cache}");sleep({r.randint(1500, 5000)});abortReverse()')   # HYBRID
    ed.require_log(r'MsgAbortReverse', timeout=20, why='HYBRID partial reverse aborted')       # HYBRID
    ed.idle(2)
    _drags_then_trigger(ed, r, cache)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_c(ed, r):
    """FULL: [libmedia.so] reset_state SIGSEGV on a slow phone: cancel races the engine's write; else process death."""
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dev.busy_storage(True)
        cache = _make_project(ed, r, 'ns_rev_c')
        t0 = _reverse_tap(ed, 'reverse #1 (slow)')
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=20, since=t0,
                       why='1st reverse really runs')
        ed.step('cancel the reverse the moment its close button shows (abort vs delete race)')
        ed.ui.tap('id:img_close', timeout=20)
        ed.require_log(r'MsgAbortReverse', timeout=10, why='reverse cancelled by the close button')
        ed.idle(r.uniform(1.0, 3.0))
        if not _cache_state(ed, cache):
            ed.step('partial file was deleted: fall back to process death mid-reverse')
            _reverse_then_die(ed, r, (0.8, 3.0))
            cache = _reopen(ed)
        _drags_then_trigger(ed, r, cache)
    finally:
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)


# 2026-11-02 16:17 attempt 1
"""Night Shift tapflow for Crashlytics/Play [libmedia.so] SIGSEGV: AudioMCDecoder::reset_state <- in_export_state <- replace_media (Reverse, cached file has no audio)."""
import os

NOAUDIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'repro_assets', 'silent_noaudio.mp4')
PKG_ = 'com.myzesty'
SURF = ('id:surface_view',)


def _open_clip(ed):
    """Open the single-clip-with-audio fixture; return the basename of clip 0's photoUri (from MsgAddVideo)."""
    mark = ed.log_mark()
    ed.open_fixture('6e2486dd')
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', timeout=40, since=mark, why='fixture clip 0 loaded')
    ed.idle(4)
    return line.split('path: ', 1)[1].split(',')[0].strip().rsplit('/', 1)[-1]


def _edit_and_drag(ed, r, drags=3):
    """Field: ve_edit_tool_btn -> free shift/rotate, then drag the clip on the canvas and scrub the timeline."""
    mark = ed.log_mark()
    ed.clip_tools()                                          # taps Edit (ve_tab_edit)
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=mark, why='Edit tool -> free crop mode')
    s = ed.screen()
    l, t, rr, b = s.find(SURF).b
    cx, cy = (l + rr) // 2, (t + b) // 2
    for _ in range(drags):
        mark = ed.log_mark()
        ed.dev.swipe(cx, cy, cx + r.randint(-250, 250), cy + r.randint(-120, 120), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x -?0\.\d*[1-9]', timeout=8, since=mark, why='canvas drag')
        ed.idle(r.uniform(0.3, 1.0))
    for _ in range(2):
        mark = ed.log_mark()
        ed.seek_swipe(r.uniform(0.4, 1.0) * r.choice((-1, 1)), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=mark, why='timeline scrub')
        ed.idle(r.uniform(0.5, 1.2))


def _reverse_cached_tap(ed, why):
    """TRIGGER: the real Reverse tap; the cached-file branch must send speed/curve/trim then MsgReplaceVideo (no reverse)."""
    ed.clip_tools()
    mark = ed.log_mark()
    ed.menu_tap('reverse')                                   # desc:ve_btn_reverse_clip
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=8, since=mark, why='Reverse preamble speed 1')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=8, since=mark, why='Reverse preamble trim 0..orig')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/transcoding-', timeout=10, since=mark, why=why)
    ed.wait_log(r'-Error-Audio-Constructor- no audio', 5, since=mark)
    ed.idle(6)


def _plant_noaudio(ed, base):
    """Lab shortcut: a reversed-cache file with NO audio track at cacheDir/<photoUri basename>."""
    ed.dev.adb('push', NOAUDIO, '/data/local/tmp/ns_noaudio.mp4', timeout=60)                          # HYBRID
    ed.dev.sh('chmod 644 /data/local/tmp/ns_noaudio.mp4')                                               # HYBRID
    ed.dev.sh(f'run-as {PKG_} sh -c "cp /data/local/tmp/ns_noaudio.mp4 cache/{base}; ls -l cache/{base}"')  # HYBRID


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a(ed, r):
    """FULL: real Reverse interrupted by Home (onPause abort) leaves cache/<name> behind; 2nd Reverse takes the cached branch -> SIGSEGV in reset_state."""
    base = _open_clip(ed)
    ed.dev.sh(f'run-as {PKG_} sh -c "rm -f cache/{base}"')   # start clean: the first Reverse must really encode
    _edit_and_drag(ed, r)
    mark = ed.log_mark()
    ed.menu_tap('reverse')
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path \S*/cache/transcoding-', timeout=10, since=mark, why='1st Reverse runs a real reverse')
    ed.idle(r.uniform(2.0, 7.0))                             # mid-reverse (audio caching or video encode)
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_HOME')                               # onPause -> JobLifecycleObserver -> abortReverse
    ed.require_log(r'abort_reverse\(\) (Called|Ended)', timeout=10, since=mark, why='leaving the app aborts the reverse')
    ed.idle(r.uniform(2, 5))
    ed.dev.launch()
    ed.idle(3)
    ed.step('2nd Reverse: field cached-file branch')
    _reverse_cached_tap(ed, why='aborted reverse left cache file (else the app re-reverses: natural route closed)')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b(ed, r):
    """HYBRID: video-only file planted as the cached reverse of a clip with audio; real Edit, drags, scrubs, then a real Reverse tap -> SIGSEGV."""
    base = _open_clip(ed)
    _plant_noaudio(ed, base)                                 # HYBRID
    _edit_and_drag(ed, r, drags=r.randint(2, 4))
    ed.step('Reverse tap (trigger)')
    _reverse_cached_tap(ed, why='Reverse tap with cached file -> MsgReplaceVideo')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c(ed, r):
    """HYBRID: as b on a slow phone (busy CPU, slow audio callback), Reverse tapped right after a scrub storm like the field."""
    base = _open_clip(ed)
    _plant_noaudio(ed, base)                                 # HYBRID
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '150')
        _edit_and_drag(ed, r, drags=r.randint(3, 5))
        ed.set_playing(True)
        ed.idle(r.uniform(1, 3))
        mark = ed.log_mark()
        ed.seek_storm(n=r.randint(6, 12), min_ms=40, max_ms=200, pause=(0.0, 0.15))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=mark, why='scrub storm before Reverse')
        ed.step('Reverse tap (trigger) right after the scrubs')
        _reverse_cached_tap(ed, why='Reverse tap with cached file -> MsgReplaceVideo (slow phone)')
    finally:
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '0')
        ed.dev.slow_phone(0)


# 2026-11-02 16:20 attempt 2
"""Night Shift tapflow for Crashlytics/Play [libmedia.so] SIGSEGV: AudioMCDecoder::reset_state <- in_export_state <- replace_media (Reverse, cached file has no audio)."""
import os

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'repro_assets')
NOAUDIO = os.path.join(ASSETS, 'silent_noaudio.mp4')          # 20 s, h264 only (no audio track)
WITHAUDIO = os.path.join(ASSETS, 'with_audio.mov')            # 20 s, h264 + aac
PKG_ = 'com.myzesty'
SURF = ('id:surface_view',)


def _new_clip(ed, tag):
    """New project from a 20 s clip WITH audio (the fixture 6e2486dd is gone); return clip 0's photoUri basename."""
    dst = '/sdcard/DCIM/NightShift/ns_2fe_audio.mov'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.adb('push', WITHAUDIO, dst, timeout=120)
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(2)
    mark = ed.log_mark()
    ed.new_project(tag=tag, duration_s=20)
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', timeout=60, since=mark, why='new project clip 0 loaded')
    if ed.wait_log(r'-Error-Audio-Constructor- no audio', 2, since=mark):
        ed.log('    WARNING: clip 0 has no audio track; the field clip had audio')
    ed.idle(3)
    return line.split('path: ', 1)[1].split(',')[0].strip().rsplit('/', 1)[-1]


def _edit_and_drag(ed, r, drags=3):
    """Field: ve_edit_tool_btn -> free shift/rotate, then drag the clip on the canvas and scrub the timeline."""
    ed.set_playing(False)
    mark = ed.log_mark()
    ed.clip_tools()                                          # Edit tab (ve_tab_edit)
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=mark, why='Edit tool -> free crop mode')
    s = ed.screen()
    l, t, rr, b = s.find(SURF).b
    cx, cy = (l + rr) // 2, (t + b) // 2
    for _ in range(drags):
        mark = ed.log_mark()
        ed.dev.swipe(cx, cy, cx + r.randint(-200, 200), cy + r.randint(-120, 120), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x -?0\.\d*[1-9]', timeout=8, since=mark, why='canvas drag')
        ed.idle(r.uniform(0.3, 1.0))
    for _ in range(2):
        mark = ed.log_mark()
        ed.seek_swipe(r.uniform(0.3, 0.8) * r.choice((-1, 1)), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=mark, why='timeline scrub')
        ed.idle(r.uniform(0.5, 1.2))


def _reverse_tap(ed):
    """Real Reverse tap (clip tool, desc ve_btn_reverse_clip); returns the log mark taken before it."""
    mark = ed.log_mark()
    ed.clip_tool('reverse', 'reverse clip')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=8, since=mark, why='Reverse preamble speed 1 (PlayerActivity:5396)')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=8, since=mark, why='Reverse preamble trim 0..orig (5398)')
    return mark


def _trigger_cached(ed, why):
    """TRIGGER: the cached-file branch sends MsgReplaceVideo within ~0.1 s (a real reverse takes ~14 s first)."""
    mark = _reverse_tap(ed)
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/transcoding-', timeout=4, since=mark, why=why)
    ed.wait_log(r'-Error-Audio-Constructor- no audio', 5, since=mark)
    ed.idle(6)


def _plant_noaudio(ed, base):
    """Lab shortcut: a video-only file as the cached reverse cacheDir/<photoUri basename>."""
    ed.dev.adb('push', NOAUDIO, '/data/local/tmp/ns_noaudio.mp4', timeout=60)                                   # HYBRID
    ed.dev.sh('chmod 644 /data/local/tmp/ns_noaudio.mp4')                                                        # HYBRID
    ed.dev.sh(f"run-as {PKG_} sh -c 'cat > cache/{base}' < /data/local/tmp/ns_noaudio.mp4")                      # HYBRID
    ed.log('    planted: ' + ed.dev.sh(f"run-as {PKG_} ls -l cache/{base}").strip())


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_a(ed, r):
    """FULL: real Reverse aborted by Home mid-encode may leave cache/<name> without audio; 2nd Reverse takes the cached branch -> SIGSEGV in reset_state."""
    base = _new_clip(ed, 'ns2fe_a')
    ed.dev.sh(f"run-as {PKG_} rm -f cache/{base}")           # first Reverse must really encode
    _edit_and_drag(ed, r)
    mark = _reverse_tap(ed)
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path \S*/cache/transcoding-', timeout=10, since=mark, why='1st Reverse runs a real reverse')
    ed.idle(r.uniform(0.5, 6.0))                             # anywhere from audio caching to video encode
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_HOME')                               # onPause -> JobLifecycleObserver -> abortReverse -> CANCEL_REVERSE
    ed.require_log(r'abort_reverse|abortReverse|MsgAbortReverse', timeout=10, since=mark, why='leaving the app aborts the reverse')
    ed.idle(r.uniform(2, 5))
    ed.dev.launch()
    ed.idle(3)
    ed.log('    cache after abort: ' + ed.dev.sh(f"run-as {PKG_} ls -l cache/{base} 2>&1").strip())
    _edit_and_drag(ed, r, drags=2)
    ed.step('2nd Reverse: field cached-file branch')
    _trigger_cached(ed, why='aborted reverse left cache file (else CANCEL_REVERSE deleted it: natural route closed)')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_b(ed, r):
    """HYBRID: video-only file planted as the cached reverse of a clip with audio; real Edit, drags, scrubs, then a real Reverse tap -> SIGSEGV."""
    base = _new_clip(ed, 'ns2fe_b')
    _plant_noaudio(ed, base)                                 # HYBRID
    _edit_and_drag(ed, r, drags=r.randint(2, 4))
    ed.step('Reverse tap (trigger)')
    _trigger_cached(ed, why='Reverse tap with cached file -> MsgReplaceVideo')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_c(ed, r):
    """HYBRID: as b on a slow phone (busy CPU, slow audio callback), Reverse tapped right after play + a scrub storm like the field."""
    base = _new_clip(ed, 'ns2fe_c')
    _plant_noaudio(ed, base)                                 # HYBRID
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '150')
        _edit_and_drag(ed, r, drags=r.randint(3, 5))
        ed.set_playing(True)
        ed.idle(r.uniform(1, 3))
        mark = ed.log_mark()
        ed.seek_storm(n=r.randint(6, 12), min_ms=40, max_ms=200, pause=(0.0, 0.15))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=mark, why='scrub storm before Reverse')
        ed.step('Reverse tap (trigger) right after the scrubs')
        _trigger_cached(ed, why='Reverse tap with cached file -> MsgReplaceVideo (slow phone)')
    finally:
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '0')
        ed.dev.slow_phone(0)


# 2026-11-02 16:30 attempt 3
"""Night Shift tapflow for Crashlytics/Play [libmedia.so] SIGSEGV: AudioMCDecoder::reset_state <- in_export_state <- replace_media (Reverse, cached file has no audio)."""
import os

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'repro_assets')
NOAUDIO = os.path.join(ASSETS, 'silent_noaudio.mp4')          # h264 only, no audio track
PKG_ = 'com.myzesty'
SURF = ('id:surface_view',)


def _open(ed):
    """Reopen the lab test draft ourselves (fixtures/new_project failed before); return clip 0's photoUri basename."""
    ed.leave_editor()
    mark = ed.log_mark()
    ed.open_draft()
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', timeout=40, since=mark, why='test draft clip 0 loaded')
    if ed.wait_log(r'-Error-Audio-Constructor- no audio', 3, since=mark):
        ed.log('    WARNING: a draft clip has no audio; the field clip had audio')
    ed.idle(6)                                                # overlays restore ~6-8 s after resume
    return line.split('path: ', 1)[1].split(',')[0].strip().rsplit('/', 1)[-1]


def _edit_and_drag(ed, r, drags=3):
    """Field: ve_edit_tool_btn -> free shift/rotate, drag the clip on the canvas, scrub the timeline."""
    ed.set_playing(False)
    mark = ed.log_mark()
    ed.clip_tools()                                           # Edit tab (ve_tab_edit)
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=mark, why='Edit tool -> free crop mode')
    l, t, rr, b = ed.screen().find(SURF).b
    cx, cy = (l + rr) // 2, (t + b) // 2
    for _ in range(drags):
        mark = ed.log_mark()
        ed.dev.swipe(cx, cy, cx + r.randint(-200, 200), cy + r.randint(-120, 120), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x -?0\.\d*[1-9]', timeout=8, since=mark, why='canvas drag')
        ed.idle(r.uniform(0.3, 1.0))
    for _ in range(2):
        mark = ed.log_mark()
        ed.seek_swipe(r.uniform(0.3, 0.8) * r.choice((-1, 1)), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=mark, why='timeline scrub')
        ed.idle(r.uniform(0.5, 1.2))


def _reverse_tap(ed, wait=6):
    """One real Reverse tap; returns the MsgReplaceVideo/MsgReverseVideo line it produced."""
    mark = ed.log_mark()
    ed.clip_tool('reverse', 'reverse clip')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=8, since=mark, why='Reverse preamble speed 1 (5396)')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=8, since=mark, why='Reverse preamble trim 0..orig (5398)')
    line = ed.require_log(r'Msg(ReplaceVideo|ReverseVideo): media_layer 0 media_id 0 path \S+', timeout=10, since=mark, why='Reverse branch taken')
    if 'MsgReverseVideo' in line:                             # real reverse: wait for its own replace
        line = ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=60, since=mark, why='real reverse finished')
    ed.idle(wait)
    return line


def _trigger_cached(ed):
    """TRIGGER: Reverse tap that takes the cached-file branch (cache/<name>); untoggle first if the draft is reversed."""
    line = _reverse_tap(ed)
    if '/cache/' not in line:                                 # was reversed -> handleOriginal; now tap again
        ed.step('clip was reversed; Reverse again for the cached branch')
        line = _reverse_tap(ed)
    if '/cache/' not in line:
        raise UIError('Reverse never took the cached-file branch: ' + line[:160])
    ed.idle(6)


def _plant_noaudio(ed, base):
    """Lab shortcut: a video-only file as the cached reverse cacheDir/<photoUri basename>."""
    ed.dev.adb('push', NOAUDIO, '/data/local/tmp/ns_noaudio.mp4', timeout=60)                          # HYBRID
    ed.dev.sh('chmod 644 /data/local/tmp/ns_noaudio.mp4')                                               # HYBRID
    ed.dev.sh(f"run-as {PKG_} sh -c 'cat > cache/{base}' < /data/local/tmp/ns_noaudio.mp4")             # HYBRID
    ed.log('    planted: ' + ed.dev.sh(f"run-as {PKG_} ls -l cache/{base} 2>&1").strip())


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_a(ed, r):
    """FULL: Edit + canvas drags + scrubs, then Reverse toggled on/off/on so the 3rd tap swaps in the cached reversed file -> SIGSEGV in reset_state."""
    base = _open(ed)
    ed.log('    cache before: ' + ed.dev.sh(f"run-as {PKG_} ls -l cache/{base} 2>&1").strip())
    _edit_and_drag(ed, r)
    _reverse_tap(ed)                                          # reverse (real or cached) or back to original
    _edit_and_drag(ed, r, drags=2)
    _reverse_tap(ed)                                          # toggle back
    ed.step('Reverse again: cached-file branch like the field')
    _trigger_cached(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_b(ed, r):
    """HYBRID: video-only file planted as the cached reverse of the audio clip; real Edit, drags, scrubs, then a real Reverse tap -> SIGSEGV."""
    base = _open(ed)
    _plant_noaudio(ed, base)                                  # HYBRID
    _edit_and_drag(ed, r, drags=r.randint(2, 4))
    ed.step('Reverse tap (trigger)')
    _trigger_cached(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_c(ed, r):
    """HYBRID: as b on a slow phone (busy CPU, slow audio callback), Reverse tapped right after play + a scrub storm."""
    base = _open(ed)
    _plant_noaudio(ed, base)                                  # HYBRID
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '150')
        _edit_and_drag(ed, r, drags=r.randint(3, 5))
        ed.set_playing(True)
        ed.idle(r.uniform(1, 3))
        mark = ed.log_mark()
        ed.seek_storm(n=r.randint(6, 12), min_ms=40, max_ms=200, pause=(0.0, 0.15))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=mark, why='scrub storm before Reverse')
        ed.step('Reverse tap (trigger) right after the scrubs')
        _trigger_cached(ed)
    finally:
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '0')
        ed.dev.slow_phone(0)
