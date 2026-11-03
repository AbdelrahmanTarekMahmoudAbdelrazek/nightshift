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


# 2026-11-02 18:53 attempt 1
"""Night Shift tapflow 2fe03193: Reverse reuses an audio-less cached reverse -> SIGSEGV in AudioMCDecoder::reset_state."""

CACHE = '/data/user/0/com.myzesty/cache/'
REV_RX = r'MsgReverseVideo: media_layer 0 media_id 0 path (\S+)'
REPLACE_CACHE_RX = r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/\S+'


def _edit_and_drag(ed, r):
    """Field: ve_edit_tool_btn, then drags the clip on the canvas (MsgApplyFreeShift / MsgApplyFreeRotate)."""
    ed.set_playing(False)
    ed.step('Edit tool')
    t0 = ed.log_mark()
    ed.ui.tap(T.EDIT, timeout=10)
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=t0, why='Edit tool opened free transform')
    for _ in range(r.randint(2, 4)):
        t0 = ed.log_mark()
        ed.dev.swipe(540, 700, 540 + r.randint(-250, 250), 700 + r.randint(-120, 120), r.randint(300, 700))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x', timeout=6, since=t0, why='drag clip on canvas')
        ed.idle(r.uniform(0.3, 0.8))


def _tap_reverse(ed):
    if not ed.in_clip_tools():
        ed.clip_tools()
    t0 = ed.log_mark()
    ed.clip_tool('reverse')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=8, since=t0, why='REVERSE preamble (5396-5398)')
    return t0


def _trigger(ed):
    """The field trigger: Reverse tap whose cached-file branch sends MsgReplaceVideo with cache/<name>."""
    ed.step('TRIGGER: Reverse again on the leftover cached file')
    t0 = _tap_reverse(ed)
    ed.require_log(REPLACE_CACHE_RX, timeout=8, since=t0, why='cached-file branch: handleReverse -> replaceMedia')
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a(ed, r):
    """FULL: Edit, drag, Reverse, cancel X as soon as it shows (before the muxer writes), Reverse again -> replace with audio-less cache."""
    ed.open_fixture('2fe03193')
    _edit_and_drag(ed, r)
    ed.step('first Reverse: real reverse starts')
    t0 = _tap_reverse(ed)
    ed.require_log(REV_RX, timeout=8, since=t0, why='real reverse started (cache file absent)')
    ed.step('cancel the reverse early')
    t1 = ed.log_mark()
    ed.ui.tap('id:img_close', timeout=10)            # visible once progress > 0 (audio-caching phase)
    ed.require_log(r'MsgAbortReverse', timeout=6, since=t1, why='X on Reversing dialog -> abortReverse')
    ed.wait_log(r'abort_reverse\(\) (WARNING|Threads finished)', 3, since=t1)
    ed.idle(r.uniform(3, 6))                          # straggling reverse threads finish the video-only file
    _trigger(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b(ed, r):
    """HYBRID: the leftover audio-less cache/<clip> is made by a lab reverse+abort; the Reverse tap that crashes is real."""
    t0 = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(r'MsgAddVideo: media_layer 0 \S* ?path:? (\S+)', timeout=20, since=t0, why='draft loads clip 0')
    src = line.split('path')[-1].strip(' :').split()[0]
    cache = CACHE + src.rsplit('/', 1)[-1]
    _edit_and_drag(ed, r)
    ed.step('HYBRID: reverse to cache/<clip> and abort with no Kotlin delete')
    t1 = ed.log_mark()
    ed.jni(f'reverseVideo(0,"{cache}");sleep({r.randint(250, 900)});abortReverse()', timeout=20)   # HYBRID
    ed.require_log(r'MsgAbortReverse', timeout=10, since=t1, why='lab abort of the reverse')        # HYBRID
    ed.idle(4)                                                                                      # HYBRID
    _trigger(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c(ed, r):
    """FULL: slow phone so reverse threads overrun abort's 500 ms wait; cancel by Home (onPause -> abortReverse), back, Reverse again."""
    ed.open_fixture('2fe03193')
    _edit_and_drag(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.step('first Reverse on a slow phone')
        t0 = _tap_reverse(ed)
        ed.require_log(REV_RX, timeout=10, since=t0, why='real reverse started')
        ed.idle(r.uniform(0.2, 1.0))
        ed.step('Home during the Reversing dialog')
        t1 = ed.log_mark()
        ed.dev.key('KEYCODE_HOME')
        ed.require_log(r'MsgAbortReverse', timeout=8, since=t1, why='onPause -> JobLifecycleObserver -> abortReverse')
        ed.wait_log(r"abort_reverse\(\) WARNING: Threads didn't finish", 4, since=t1)
        ed.idle(r.uniform(4, 8))
        ed.dev.launch()                               # back to the same editor
        ed.idle(3)
    finally:
        ed.dev.slow_phone(0)
    _trigger(ed)


# 2026-11-02 18:56 attempt 2
"""Night Shift tapflow 2fe03193: Reverse reuses an audio-less leftover cache/<clip> -> SIGSEGV in AudioMCDecoder::reset_state."""

CACHE = '/data/user/0/com.myzesty/cache/'
REV_RX = r'MsgReverseVideo: media_layer 0 media_id 0 path \S+'
REPLACE_CACHE_RX = r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/\S+'
CX, CY = 360, 520                                    # centre of surface_view (101,64)-(619,985)


def _edit_and_drag(ed, r):
    """Field: ve_edit_tool_btn, then canvas taps/drags (each finger-up -> MsgApplyFreeShift + MsgApplyFreeRotate)."""
    ed.set_playing(False)
    ed.step('Edit tool')
    t0 = ed.log_mark()
    ed.ui.tap(T.EDIT, timeout=10)
    ed.require_log(r'Event: (test_)?ve_edit_tool_btn', timeout=8, since=t0, why='Edit tab tapped')
    ed.idle(1)
    t0 = ed.log_mark()
    ed.dev.tap(CX, CY)                               # field: shift 0/0 + rotate 0 pairs before the drags
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=6, since=t0, why='canvas tap -> refreshMediaPosition')
    for _ in range(r.randint(2, 4)):
        t0 = ed.log_mark()
        ed.dev.swipe(CX, CY, CX + r.randint(-200, 200), CY + r.randint(-150, 150), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x', timeout=6, since=t0, why='drag clip on canvas')
        ed.idle(r.uniform(0.3, 0.8))


def _tap_reverse(ed, why):
    if not ed.in_clip_tools():
        ed.clip_tools()
    t0 = ed.log_mark()
    ed.clip_tool('reverse')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=8, since=t0, why=why)
    return t0


def _leave_mid_reverse(ed, r, camera=False):
    """Home (or another app) while 'Reversing' shows: onPause -> abortReverse only, no CANCEL_REVERSE delete."""
    t0 = _tap_reverse(ed, 'REVERSE preamble (5396-5398), first tap')
    ed.require_log(REV_RX, timeout=10, since=t0, why='real reverse started (cache file absent)')
    ed.idle(r.uniform(0.4, 1.5))                      # let the muxer start writing cache/<name>
    t1 = ed.log_mark()
    ed.dev.key('KEYCODE_HOME')
    if camera:
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
    ed.require_log(r'MsgAbortReverse', timeout=8, since=t1, why='onPause -> JobLifecycleObserver -> abortReverse')
    ed.idle(r.uniform(3, 6))
    ed.dev.launch()                                   # same task: editor resumes, clip still not reversed
    ed.idle(4)


def _trigger(ed):
    ed.step('TRIGGER: Reverse on the leftover cached file')
    t0 = _tap_reverse(ed, 'REVERSE preamble, trigger tap')
    ed.require_log(REPLACE_CACHE_RX, timeout=8, since=t0, why='cached-file branch: handleReverse -> replaceMedia')
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_a(ed, r):
    """FULL: Edit + canvas drags, Reverse, Home mid-reverse (abort keeps the partial file), back, Reverse again."""
    ed.open_fixture('2fe03193')
    _edit_and_drag(ed, r)
    ed.step('first Reverse, leave the app mid-reverse')
    _leave_mid_reverse(ed, r)
    _trigger(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_b(ed, r):
    """HYBRID: the audio-less cache/<clip> is left by a lab reverse+abort; the Reverse tap that crashes is real."""
    t0 = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', timeout=20, since=t0, why='draft loads clip 0')
    src = line.split('path:')[-1].split(',')[0].strip()
    cache = CACHE + src.rsplit('/', 1)[-1]
    _edit_and_drag(ed, r)
    ed.step('HYBRID: partial reverse into cache/<clip>, aborted without the Kotlin delete')
    t1 = ed.log_mark()
    ed.jni(f'reverseVideo(0,"{cache}");sleep({r.randint(600, 1500)});abortReverse()', timeout=20)   # HYBRID
    ed.require_log(r'MsgAbortReverse', timeout=10, since=t1, why='lab abort of the reverse')        # HYBRID
    ed.idle(4)                                                                                      # HYBRID
    _trigger(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_c(ed, r):
    """FULL: slow phone (field low-end Vivo) so the abort lands mid-write; leave via camera app, back, Reverse again."""
    ed.open_fixture('2fe03193')
    _edit_and_drag(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.step('first Reverse on a slow phone, switch to camera mid-reverse')
        _leave_mid_reverse(ed, r, camera=True)
    finally:
        ed.dev.slow_phone(0)
    ed.idle(2)
    _trigger(ed)


# 2026-11-02 19:00 attempt 3
"""Night Shift tapflow 2fe03193 (attempt 3): Reverse reuses cache/<clip> with no audio -> SIGSEGV in AudioMCDecoder::reset_state."""

_F3_CACHE = '/data/user/0/com.myzesty/cache/'
_F3_REV = r'MsgReverseVideo: media_layer 0 media_id 0 path \S+'
_F3_REPL_CACHE = r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/\S+'
_F3_REPL_ORIG = r'MsgReplaceVideo: media_layer 0 media_id 0 path (?!\S*/cache/)\S+'
_F3_CX, _F3_CY = 360, 520                            # centre of surface_view (101,64)-(619,985)


def _f3_edit_drag(ed, r):
    """Field: ve_edit_tool_btn, then canvas tap + drags (finger-up -> MsgApplyFreeShift/MsgApplyFreeRotate)."""
    ed.set_playing(False)
    ed.step('Edit tool')
    t0 = ed.log_mark()
    ed.ui.tap(T.EDIT, timeout=10)
    ed.require_log(r'Event: (test_)?ve_edit_tool_btn', timeout=8, since=t0, why='Edit tab tapped')
    ed.idle(1)
    t0 = ed.log_mark()
    ed.dev.tap(_F3_CX, _F3_CY)
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=6, since=t0, why='canvas tap')
    for _ in range(r.randint(2, 4)):
        t0 = ed.log_mark()
        ed.dev.swipe(_F3_CX, _F3_CY, _F3_CX + r.randint(-200, 200), _F3_CY + r.randint(-150, 150), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x', timeout=6, since=t0, why='drag clip on canvas')
        ed.idle(r.uniform(0.3, 0.8))


def _f3_reverse_tap(ed, why):
    if not ed.in_clip_tools():
        ed.clip_tools()
    t0 = ed.log_mark()
    ed.clip_tool('reverse')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=8, since=t0, why=why)
    return t0


def _f3_trigger(ed):
    ed.step('TRIGGER: Reverse on the existing cache/<clip>')
    t0 = _f3_reverse_tap(ed, 'REVERSE preamble (5396-5398), trigger tap')
    ed.require_log(_F3_REPL_CACHE, timeout=10, since=t0, why='cached-file branch: handleReverse -> replaceMedia')
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_a(ed, r):
    """FULL: Edit + drags, Reverse (real), Reverse (back to original), Reverse again -> replace with cached reversed file."""
    ed.open_fixture('2fe03193')
    _f3_edit_drag(ed, r)
    ed.step('Reverse #1: real reverse into cache/<clip>')
    t0 = _f3_reverse_tap(ed, 'REVERSE preamble, first tap')
    ed.require_log(_F3_REV, timeout=10, since=t0, why='real reverse started (no cache file)')
    ed.require_log(_F3_REPL_CACHE, timeout=120, since=t0, why='reverse done -> handleReverse')
    ed.idle(r.uniform(2, 4))
    ed.step('Reverse #2: back to the original')
    t0 = _f3_reverse_tap(ed, 'REVERSE preamble, second tap')
    ed.require_log(_F3_REPL_ORIG, timeout=10, since=t0, why='handleOriginal -> replaceMedia(photoUri)')
    ed.idle(r.uniform(2, 4))
    _f3_edit_drag(ed, r)
    _f3_trigger(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_b(ed, r):
    """HYBRID: a lab reverse aborted mid-way leaves an audio-less cache/<clip> (no Kotlin delete); the Reverse tap is real."""
    t0 = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', timeout=20, since=t0, why='draft loads clip 0')
    src = line.split('path:')[-1].split(',')[0].strip()
    cache = _F3_CACHE + src.rsplit('/', 1)[-1]
    ed.idle(2)
    ed.step('HYBRID: partial reverse into ' + cache)
    t1 = ed.log_mark()
    ed.jni(f'reverseVideo(0,"{cache}",0);sleep({r.randint(300, 3500)});abortReverse()', timeout=30)  # HYBRID
    ed.require_log(r'MsgAbortReverse', timeout=15, since=t1, why='lab abort of the reverse')          # HYBRID
    ed.idle(3)                                                                                        # HYBRID
    _f3_edit_drag(ed, r)
    _f3_trigger(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_c(ed, r):
    """FULL: slow phone; Home the instant the reverse muxer stops (onPause dismisses before handleReverse, file kept), back, Reverse."""
    ed.open_fixture('2fe03193')
    _f3_edit_drag(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.step('Reverse #1 on a slow phone, Home as the muxer stops')
        t0 = _f3_reverse_tap(ed, 'REVERSE preamble, first tap')
        ed.require_log(_F3_REV, timeout=10, since=t0, why='real reverse started')
        ed.require_log(r'Muxer stopped successfully', timeout=150, since=t0, why='reverse file written')
        ed.dev.key('KEYCODE_HOME')
        ed.require_log(r'Event: (test_)?ve_on_pause', timeout=8, since=t0, why='onPause -> JobLifecycleObserver')
        ed.idle(r.uniform(3, 6))
    finally:
        ed.dev.slow_phone(0)
    t1 = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Event: (test_)?ve_on_resume', timeout=10, since=t1, why='back to the same editor')
    ed.idle(3)
    _f3_trigger(ed)


# 2026-11-02 20:46 attempt 1
"""Night Shift tapflow 2fe03193 ([libmedia.so] SIGSEGV AudioMCDecoder::reset_state <- replace_media): Reverse reuses a video-only cache/<clip name>."""

PKG_ = 'com.myzesty'
DUP = 'NS_2fe03193_dup'                              # another folder on the phone, same file name as clip 0
ADD0 = r'MsgAddVideo: media_layer 0 path: (?!\S*/cache/)\S+'


def _open(ed):
    """Fixture 2fe03193: clip 0 with audio, never reversed. Returns clip 0's file name (the reverse cache key)."""
    m = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(ADD0, timeout=40, since=m, why='fixture clip 0 (with audio) loaded from durable media')
    ed.idle(4)
    ed.set_playing(False)
    return line.split('path: ', 1)[1].split(',')[0].strip().rsplit('/', 1)[-1]


def _silent_mp4(ed, dst, secs):
    """A valid H.264 mp4 with NO audio track (screenrecord), the same kind the proven lab hit used."""
    ed.dev.sh(f'mkdir -p {dst.rsplit("/", 1)[0]}; rm -f {dst}; '
              f'screenrecord --time-limit {secs} --bit-rate 2000000 --size 720x1600 {dst}', timeout=secs + 30)


def _reverse_tile(ed):
    try:
        ed.menu_tap('reverse')                       # desc ve_btn_reverse_clip -> Constants.REVERSE
    except UIError:
        ed.tap_tool('reverse')


def _same_name_clip_reversed(ed, r, name):
    """FULL prerequisite: a silent clip with clip 0's file name is added and really reversed -> video-only cache/<name>."""
    ed.step(f'phone has a silent clip also named {name}; add it and reverse it')
    dst = f'/sdcard/DCIM/{DUP}/{name}'
    _silent_mp4(ed, dst, r.randint(8, 14))
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(3)
    m = ed.log_mark()
    ed.add_media(pick=0)                             # newest in the gallery = the silent same-name clip
    ed.require_log(rf'MsgAddVideo: media_layer 0 path: \S*/{DUP}/{name}', timeout=30, since=m,
                   why='silent clip added with its own path (a transcode would rename it and close this route)')
    ed.seek_to(0.85)                                 # playhead on the added clip (media 1)
    ed.clip_tools()
    m = ed.log_mark()
    _reverse_tile(ed)
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 1', timeout=10, since=m, why='Reverse preamble on media 1')
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 1 path \S*/cache/', timeout=15, since=m,
                   why='real reverse of the silent clip (no audio thread)')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 1 path \S*/cache/', timeout=180, since=m,
                   why='reverse done: video-only cache/<name> written and kept')
    ed.idle(3)


def _field_edit_drag_scrub(ed, r):
    """Field: scrubs, ve_edit_tool_btn, canvas drags (MsgApplyFreeShift), more scrubs, all on clip 0."""
    ed.seek_to(0.2)                                  # back on clip 0
    ed.main_nav()
    m = ed.log_mark()
    ed.clip_tools()
    ed.require_log(r'Event: \S*ve_edit_tool_btn', timeout=10, since=m, why='Edit tool (field ve_edit_tool_btn)')
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=m, why='Edit on clip 0 -> free shift')
    x, y = ed.screen().find('id:surface_view').center
    for _ in range(r.randint(2, 4)):
        m = ed.log_mark()
        ed.dev.swipe(x, y, x + r.randint(-200, 200), y + r.randint(-120, 120), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x', timeout=8, since=m, why='drag clip 0 on canvas')
        ed.idle(r.uniform(0.3, 0.8))
    for _ in range(2):
        m = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.12, 0.12), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=m, why='timeline scrub inside clip 0')
        ed.idle(r.uniform(0.4, 1.0))


def _trigger(ed, name):
    """TRIGGER (real tap): Reverse on clip 0 -> preamble -> cached branch MsgReplaceVideo cache/<name> -> crash."""
    ed.step('TRIGGER: Reverse on clip 0 while cache/<name> is video-only')
    m = ed.log_mark()
    _reverse_tile(ed)
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, since=m, why='preamble speed 1 (5396)')
    ed.require_log(r'MsgSetMediaCurveSpeed layer 0 media_id 0 index 0', timeout=10, since=m, why='preamble curve 0 (5397)')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=10, since=m, why='preamble trim (5398)')
    hit = ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S+|MsgReverseVideo: media_layer 0 media_id 0',
                         timeout=15, since=m, why='cached-file branch -> handleReverse -> replaceMedia')
    if 'MsgReverseVideo' in hit or f'/cache/{name}' not in hit:
        raise UIError(f'Reverse did not reuse cache/{name}: {hit[-120:]}')
    ed.require_log(r'-Error-Audio-Constructor- no audio', timeout=10, since=m, why='no-audio early return (AudioMCDecoder.cpp:624)')
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a(ed, r):
    """FULL: a silent same-name clip is reversed first (video-only cache/<name>); Edit, drags, scrubs on clip 0, Reverse -> SIGSEGV."""
    name = _open(ed)
    _same_name_clip_reversed(ed, r, name)
    _field_edit_drag_scrub(ed, r)
    _trigger(ed, name)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b(ed, r):
    """HYBRID: video-only cache/<clip 0 name> planted (proven l3_2_b step); real Edit, drags, scrubs, real Reverse tap -> SIGSEGV."""
    name = _open(ed)
    ed.step(f'HYBRID: plant a video-only mp4 at cache/{name}')
    src = '/sdcard/Download/ns_2fe03193_noaudio.mp4'                                             # HYBRID
    _silent_mp4(ed, src, r.randint(12, 20))                                                     # HYBRID
    ed.dev.sh(f"cat {src} | run-as {PKG_} sh -c 'cat > cache/{name}'", timeout=60)              # HYBRID
    size = ed.dev.sh(f'run-as {PKG_} stat -c %s cache/{name}').strip()                          # HYBRID
    if not size.isdigit() or int(size) < 50000:
        raise UIError(f'video-only cache file was not planted (size {size!r})')
    _field_edit_drag_scrub(ed, r)
    _trigger(ed, name)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c(ed, r):
    """FULL: as (a), plus a slow low-end Vivo phone, critical memory pressure and the field seek storm before Reverse."""
    name = _open(ed)
    _same_name_clip_reversed(ed, r, name)
    _field_edit_drag_scrub(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.dev.sh(f'am send-trim-memory {PKG_} RUNNING_CRITICAL')
        m = ed.log_mark()
        ed.seek_storm(r.randint(4, 7), 60, 200, 0.2)  # field: seek gen 36..49, "get_frame interrupted by new seek"
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=10, since=m, why='field seek storm')
        ed.seek_to(0.2)                               # land back on clip 0 before the trigger
        ed.idle(1.5)
        _trigger(ed, name)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-02 20:54 attempt 2
"""Night Shift tapflow 2fe03193 ([libmedia.so] SIGSEGV AudioMCDecoder::reset_state <- replace_media): Reverse reuses a video-only cache/<clip name>."""

N2FE2_PKG = 'com.myzesty'
N2FE2_DUP = 'NS_2fe03193_dup'                       # another folder on the phone, same file name as clip 0
N2FE2_ADD0 = r'MsgAddVideo: media_layer 0 path: (?!\S*/cache/)\S+'


def _n2fe2_open(ed):
    """Fixture 2fe03193: clip 0 with audio, never reversed. Returns clip 0's file name (the reverse cache key)."""
    m = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(N2FE2_ADD0, timeout=40, since=m, why='fixture clip 0 (with audio) loaded from durable media')
    name = line.split('path: ', 1)[1].split(',')[0].strip().rsplit('/', 1)[-1]
    if not re.fullmatch(r'[\w.\-]+\.(mp4|mov|3gp|mkv)', name, re.I):
        raise UIError(f'clip 0 file name not understood: {name!r}')
    ed.idle(4)
    ed.set_playing(False)
    ed.main_nav()
    return name


def _n2fe2_silent_mp4(ed, dst, secs):
    """A valid H.264 mp4 with NO audio track (screenrecord), the same kind the proven lab hit used."""
    ed.dev.sh(f'mkdir -p {dst.rsplit("/", 1)[0]}; rm -f {dst}; '
              f'screenrecord --time-limit {secs} --bit-rate 2000000 --size 720x1600 {dst}', timeout=secs + 30)


def _n2fe2_tap_reverse(ed):
    ed.clip_tool('reverse', 'reverse clip')          # Constants.REVERSE (PlayerActivity.kt:5387)


def _n2fe2_same_name_reversed(ed, r, name):
    """FULL prerequisite: a silent clip with clip 0's file name is added and really reversed -> video-only cache/<name>."""
    ed.step(f'phone has a silent clip also named {name}; add it and reverse it')
    dst = f'/sdcard/DCIM/{N2FE2_DUP}/{name}'
    _n2fe2_silent_mp4(ed, dst, r.randint(8, 14))
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(3)
    m = ed.log_mark()
    ed.add_media(pick=0)                             # newest in the gallery = the silent same-name clip
    ed.require_log(rf'MsgAddVideo: media_layer 0 path: \S*/{N2FE2_DUP}/{re.escape(name)}', timeout=40, since=m,
                   why='silent clip added with its own path (a transcode would rename it and close this route)')
    ed.wait_loader(60)
    ed.seek_to(0.9)                                  # playhead on the added clip (media 1)
    m = ed.log_mark()
    _n2fe2_tap_reverse(ed)
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 1', timeout=10, since=m, why='Reverse preamble on media 1')
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 1 path \S*/cache/', timeout=20, since=m,
                   why='real reverse of the silent clip')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 1 path \S*/cache/', timeout=180, since=m,
                   why='reverse done: video-only cache/<name> written and kept')
    ed.wait_loader(30)
    ed.idle(3)
    ed.main_nav()


def _n2fe2_plant(ed, r, name):
    ed.step(f'HYBRID: plant a video-only mp4 at cache/{name}')
    src = '/data/local/tmp/ns_2fe03193_noaudio.mp4'                                              # HYBRID
    _n2fe2_silent_mp4(ed, src, r.randint(12, 20))                                                # HYBRID
    ed.dev.sh(f"chmod 644 {src}; run-as {N2FE2_PKG} sh -c 'cat > cache/{name}' < {src}", timeout=60)  # HYBRID
    size = ed.dev.sh(f'run-as {N2FE2_PKG} stat -c %s cache/{name} 2>&1').strip()                # HYBRID
    if not size.isdigit() or int(size) < 50000:
        raise UIError(f'video-only cache file was not planted (size {size!r})')
    ed.log(f'    planted cache/{name}: {size} bytes')


def _n2fe2_edit_drag_scrub(ed, r):
    """Field: ve_edit_tool_btn, canvas drags (MsgApplyFreeShift), timeline scrubs, all on clip 0."""
    ed.seek_to(0.15)                                 # playhead on clip 0
    m = ed.log_mark()
    ed.clip_tools()                                  # Edit tab (ve_tab_edit)
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=m, why='Edit tool -> free shift on clip 0')
    s = ed.screen()
    x, y = s.find('id:surface_view').center if s is not None and s.has(('id:surface_view',)) else (360, 520)
    for _ in range(r.randint(2, 4)):
        m = ed.log_mark()
        ed.dev.swipe(x, y, x + r.randint(-180, 180), y + r.randint(-120, 120), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x', timeout=8, since=m, why='drag clip 0 on canvas')
        ed.idle(r.uniform(0.3, 0.8))
    for _ in range(2):
        m = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.12, 0.12), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=m, why='timeline scrub inside clip 0')
        ed.idle(r.uniform(0.4, 1.0))
    ed.seek_to(0.15)                                 # make sure the selected clip is clip 0


def _n2fe2_trigger(ed, name):
    """TRIGGER (real tap): Reverse on clip 0 -> preamble -> cached branch MsgReplaceVideo cache/<name> -> crash."""
    ed.step('TRIGGER: Reverse on clip 0 while cache/<name> is video-only')
    m = ed.log_mark()
    _n2fe2_tap_reverse(ed)
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, since=m, why='preamble speed 1 (5396)')
    ed.require_log(r'MsgSetMediaCurveSpeed layer 0 media_id 0 index 0', timeout=10, since=m, why='preamble curve 0 (5397)')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+', timeout=10, since=m, why='preamble trim (5398)')
    hit = ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S+|MsgReverseVideo: media_layer 0 media_id 0',
                         timeout=15, since=m, why='cached-file branch -> handleReverse -> replaceMedia')
    if 'MsgReverseVideo' in hit or f'/cache/{name}' not in hit:
        raise UIError(f'Reverse did not reuse cache/{name}: {hit[-120:]}')
    ed.require_log(r'-Error-Audio-Constructor- no audio', timeout=10, since=m, why='no-audio early return (AudioMCDecoder.cpp:624)')
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_a(ed, r):
    """FULL: a silent same-name clip is reversed first (video-only cache/<name>); Edit, drags, scrubs on clip 0, Reverse -> SIGSEGV."""
    name = _n2fe2_open(ed)
    _n2fe2_same_name_reversed(ed, r, name)
    _n2fe2_edit_drag_scrub(ed, r)
    _n2fe2_trigger(ed, name)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_b(ed, r):
    """HYBRID: video-only cache/<clip 0 name> planted (proven l3_2_b step); real Edit, drags, scrubs, real Reverse tap -> SIGSEGV."""
    name = _n2fe2_open(ed)
    _n2fe2_plant(ed, r, name)                        # HYBRID
    _n2fe2_edit_drag_scrub(ed, r)
    _n2fe2_trigger(ed, name)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_c(ed, r):
    """HYBRID: as (b) on a slow low-end phone under critical memory pressure, field seek storm right before Reverse."""
    name = _n2fe2_open(ed)
    _n2fe2_plant(ed, r, name)                        # HYBRID
    _n2fe2_edit_drag_scrub(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.dev.sh(f'am send-trim-memory {N2FE2_PKG} RUNNING_CRITICAL')
        m = ed.log_mark()
        ed.seek_storm(r.randint(4, 7), 60, 200, 0.2)  # field: seek gen 36..49, "get_frame interrupted by new seek"
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=10, since=m, why='field seek storm')
        ed.seek_to(0.15)
        _n2fe2_trigger(ed, name)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-02 21:00 attempt 3
"""Night Shift tapflow 2fe03193 ([libmedia.so] SIGSEGV AudioMCDecoder::reset_state <- replace_media): Reverse reuses a video-only cache/<clip name>."""
import os
import re

N2FE3_PKG = 'com.myzesty'
N2FE3_ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'repro_assets', 'silent_noaudio.mp4')
N2FE3_DUP = '/sdcard/DCIM/NS_2fe03193_dup'          # another folder, same file name as clip 0
N2FE3_ADD0 = r'MsgAddVideo: media_layer 0 path: (?!\S*/cache/)\S+'


def _n2fe3_open(ed):
    """Fixture 2fe03193: clip 0 with audio, never reversed. Returns clip 0's file name (the reverse cache key)."""
    m = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(N2FE3_ADD0, timeout=40, since=m, why='fixture clip 0 (with audio) loaded')
    name = line.split('path: ', 1)[1].split(',')[0].strip().rsplit('/', 1)[-1]
    if not re.fullmatch(r'[\w.\-]+\.(mp4|mov|3gp|mkv)', name, re.I):
        raise UIError(f'clip 0 file name not understood: {name!r}')
    ed.idle(4)
    ed.set_playing(False)
    ed.main_nav()
    ed.log('    cache before: ' + ed.dev.sh(f'run-as {N2FE3_PKG} ls -l cache/{name} 2>&1').strip())
    return name


def _n2fe3_reverse(ed, mid):
    """One real Reverse tap on media `mid`; returns the branch line (MsgReplaceVideo or MsgReverseVideo)."""
    m = ed.log_mark()
    ed.clip_tool('reverse', 'reverse clip')          # Constants.REVERSE (PlayerActivity.kt:5387)
    ed.require_log(rf'MsgSetVideoSpeed: speed 1\.0+, layer 0, id {mid}', timeout=10, since=m, why='preamble speed 1 (5396)')
    ed.require_log(rf'MsgSetMediaCurveSpeed layer 0 media_id {mid} index 0', timeout=10, since=m, why='preamble curve 0 (5397)')
    ed.require_log(rf'MsgTrimVideo: media_layer 0 media_id {mid} start_time 0\.0+', timeout=10, since=m, why='preamble trim (5398)')
    return ed.require_log(rf'Msg(ReplaceVideo|ReverseVideo): media_layer 0 media_id {mid} path \S+', timeout=15, since=m,
                          why='Reverse branch taken'), m


def _n2fe3_same_name_reversed(ed, name):
    """FULL prerequisite: a silent clip with clip 0's file name is added and reversed -> video-only cache/<name>."""
    ed.step(f'phone has a silent clip also named {name}; add it and reverse it')
    dst = f'{N2FE3_DUP}/{name}'
    ed.dev.sh(f'mkdir -p {N2FE3_DUP}')
    ed.dev.adb('push', N2FE3_ASSET, dst, timeout=120)
    ed.dev.sh(f'touch {dst}; content call --uri content://media --method scan_file --arg {dst.replace("/sdcard", "/storage/emulated/0")}', timeout=60)
    ed.idle(3)
    rows = ed.dev.sh('content query --uri content://media/external/video/media --projection _data 2>/dev/null')
    if 'NS_2fe03193_dup/' + name not in rows:
        raise UIError('silent same-name clip is not in MediaStore; the picker would add another clip')
    m = ed.log_mark()
    ed.add_media(pick=0)                             # newest in the gallery = the silent same-name clip
    ed.require_log(rf'MsgAddVideo: media_layer 0 path: \S*/NS_2fe03193_dup/{re.escape(name)}', timeout=40, since=m,
                   why='silent clip added under its own path (no transcode rename)')
    ed.wait_loader(60)
    ed.seek_to(0.9)                                  # playhead on the added clip (media 1)
    line, m = _n2fe3_reverse(ed, 1)
    if 'MsgReverseVideo' in line:
        ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 1 path \S*/cache/', timeout=180, since=m,
                       why='reverse of the silent clip done: video-only cache/<name> written')
    ed.wait_loader(30)
    ed.idle(3)
    ed.main_nav()


def _n2fe3_plant(ed, name):
    """Lab shortcut (proven l3_2_b step): the 20 s h264-only asset as cacheDir/<clip 0 name>."""
    ed.step(f'HYBRID: plant a video-only mp4 at cache/{name}')
    want = os.path.getsize(N2FE3_ASSET)                                                             # HYBRID
    ed.dev.adb('push', N2FE3_ASSET, '/data/local/tmp/ns_noaudio.mp4', timeout=60)                   # HYBRID
    ed.dev.sh('chmod 644 /data/local/tmp/ns_noaudio.mp4')                                            # HYBRID
    ed.dev.sh(f"run-as {N2FE3_PKG} sh -c 'cat > cache/{name}' < /data/local/tmp/ns_noaudio.mp4")     # HYBRID
    size = ed.dev.sh(f'run-as {N2FE3_PKG} stat -c %s cache/{name} 2>&1').strip()
    if size != str(want):
        raise UIError(f'video-only cache file not planted: {size!r} bytes, asset has {want}')
    ed.log(f'    planted cache/{name}: {size} bytes')


def _n2fe3_edit_drag_scrub(ed, r):
    """Field: ve_edit_tool_btn, canvas drags (MsgApplyFreeShift), timeline scrubs, all on clip 0."""
    ed.seek_to(0.15)                                 # playhead on clip 0
    m = ed.log_mark()
    ed.clip_tools()                                  # Edit tab (ve_tab_edit)
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=m, why='Edit tool -> free shift on clip 0')
    s = ed.screen()
    x, y = s.find('id:surface_view').center if s is not None and s.has(('id:surface_view',)) else (360, 520)
    for _ in range(r.randint(2, 4)):
        m = ed.log_mark()
        ed.dev.swipe(x, y, x + r.randint(-180, 180), y + r.randint(-120, 120), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x', timeout=8, since=m, why='drag clip 0 on canvas')
        ed.idle(r.uniform(0.3, 0.8))
    for _ in range(2):
        m = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.12, 0.12), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=8, since=m, why='timeline scrub inside clip 0')
        ed.idle(r.uniform(0.4, 1.0))
    ed.seek_to(0.15)                                 # the selected clip must be clip 0


def _n2fe3_trigger(ed, name):
    """TRIGGER (real tap): Reverse on clip 0 -> cached branch MsgReplaceVideo cache/<name> -> SIGSEGV in reset_state."""
    ed.step('TRIGGER: Reverse on clip 0 while cache/<name> is video-only')
    line, m = _n2fe3_reverse(ed, 0)
    if 'MsgReverseVideo' in line or f'/cache/{name}' not in line:
        raise UIError(f'Reverse did not reuse cache/{name}: {line[-120:]}')
    ed.require_log(r'-Error-Audio-Constructor- no audio', timeout=10, since=m, why='no-audio early return (AudioMCDecoder.cpp:624)')
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_a(ed, r):
    """FULL: a silent same-name clip is added and reversed (video-only cache/<name>); Edit, drags, scrubs on clip 0, Reverse -> SIGSEGV."""
    name = _n2fe3_open(ed)
    _n2fe3_same_name_reversed(ed, name)
    _n2fe3_edit_drag_scrub(ed, r)
    _n2fe3_trigger(ed, name)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_b(ed, r):
    """HYBRID: video-only cache/<clip 0 name> planted (proven l3_2_b step); real Edit, drags, scrubs, real Reverse tap -> SIGSEGV."""
    name = _n2fe3_open(ed)
    _n2fe3_plant(ed, name)                           # HYBRID
    _n2fe3_edit_drag_scrub(ed, r)
    _n2fe3_trigger(ed, name)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_c(ed, r):
    """HYBRID: as (b) on a slow low-end phone under critical memory pressure, field seek storm right before Reverse."""
    name = _n2fe3_open(ed)
    _n2fe3_plant(ed, name)                           # HYBRID
    _n2fe3_edit_drag_scrub(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.dev.sh(f'am send-trim-memory {N2FE3_PKG} RUNNING_CRITICAL')
        m = ed.log_mark()
        ed.seek_storm(r.randint(4, 7), 60, 200, 0.2)  # field: seek gen 36..49, "get_frame interrupted by new seek"
        ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=10, since=m, why='field seek storm')
        ed.seek_to(0.15)                             # back on clip 0 before the trigger
        _n2fe3_trigger(ed, name)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-03 12:56 attempt 1
# Night Shift tapflow for crash 2fe03193 ([libmedia.so] SIGSEGV in AudioMCDecoder::reset_state <- replace_media).

NS_FX = '2fe03193'


def _clip(ed):
    """(phone path, file name) of the fixture's layer-0 clip (durable DCIM copy, outside cache/)."""
    for path, _secs in ed.dev.video_lengths():
        if f'ns_fx_{NS_FX}' in path:
            return path, path.rsplit('/', 1)[-1]
    raise UIError('fixture clip ns_fx_2fe03193_* not found on the phone')


def _edit_and_shift(ed, r, drags):
    """Field: ve_edit_tool_btn, then finger drags on the preview (free crop -> MsgApplyFreeShift layer 0 media 0)."""
    ed.step('field: Edit tool on clip 0')
    t0 = ed.log_mark()
    ed.clip_tools()
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=t0, why='Edit tool enables free crop')
    s = ed.screen()
    cx, cy = s.find(('id:surface_view',)).center
    for _ in range(drags):
        t1 = ed.log_mark()
        ed.dev.swipe(cx, cy, cx + r.randint(-250, 250), cy + r.randint(-120, 120), r.randint(300, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x', timeout=8, since=t1, why='drag the clip on the preview')
        ed.idle(r.uniform(0.3, 1.0))


def _reverse_tap(ed, why, expect_cache):
    """The tap whose MsgReplaceVideo ends in replace_media -> in_export_state -> reset_state."""
    ed.step(f'trigger: Reverse ({why})')
    t0 = ed.log_mark()
    ed.ui.tap(T.REVERSE)
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, since=t0, why='REVERSE handler speed 1')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0', timeout=10, since=t0, why='REVERSE handler trim 0..orig')
    pat = r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' if expect_cache else r'MsgReverseVideo|MsgReplaceVideo'
    ed.require_log(pat, timeout=180, since=t0, why=why)
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a(ed, r):
    """FULL: Crashlytics 2fe03193 - real Reverse (transcodes cache/<clip>), Reverse back, Reverse again -> cached branch -> SIGSEGV."""
    ed.dev.clear_app_cache()                         # no leftover cache/<clip>: the first Reverse must transcode for real
    ed.open_fixture(NS_FX)
    ed.set_playing(False)
    _edit_and_shift(ed, r, drags=2)
    _reverse_tap(ed, 'first reverse: real transcode into cache/<clip>', expect_cache=False)
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/', timeout=240, why='reverse output swapped in')
    _reverse_tap(ed, 'back to original (handleOriginal)', expect_cache=False)
    for _ in range(r.randint(2, 4)):                 # field: scrub seeks between edits
        ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(80, 200))
    _reverse_tap(ed, 'reverse again: cachedFile.exists() -> handleReverse(cache path)', expect_cache=True)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b(ed, r):
    """HYBRID: Crashlytics 2fe03193 - a valid video-only mp4 already at cache/<clip name>, then a REAL Reverse tap."""
    ed.dev.clear_app_cache()
    src, name = _clip(ed)
    ed.dev.plant_app_file(src, f'cache/{name}', video_only=True, min_bytes=100000)   # HYBRID
    ed.open_fixture(NS_FX)
    ed.set_playing(False)
    _edit_and_shift(ed, r, drags=r.randint(1, 3))
    for _ in range(r.randint(2, 3)):
        ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(80, 200))
    _reverse_tap(ed, 'cached branch: MsgReplaceVideo with the video-only cache file', expect_cache=True)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c(ed, r):
    """HYBRID: Crashlytics 2fe03193 - as (b) on a slow, memory-pressed phone (Vivo field devices), field-length free-shift drags."""
    ed.dev.clear_app_cache()
    src, name = _clip(ed)
    ed.dev.plant_app_file(src, f'cache/{name}', video_only=True, min_bytes=100000)   # HYBRID
    ed.open_fixture(NS_FX)
    ed.set_playing(False)
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.trim_memory('RUNNING_CRITICAL')
        _edit_and_shift(ed, r, drags=r.randint(4, 7))
        ed.seek_storm(r.randint(6, 12), 40, 160, 0.05)
        ed.idle(r.uniform(1.0, 3.0))
        _reverse_tap(ed, 'cached branch under load', expect_cache=True)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-03 13:09 attempt 1
# Night Shift tapflow for CRASH 2fe03193: SIGSEGV in AudioMCDecoder::reset_state <- in_export_state <- VideoEngine::replace_media
# (Reverse swaps a clip that has audio for a cached reversed mp4 that has NO audio track).

def _clip_name(ed, mark):
    """File name of layer 0 media 0 as the engine opened it (MsgAddVideo path), fallback: newest fixture copy."""
    line = ed.wait_log(r'MsgAddVideo.*\.mp4', 20, since=mark)
    for tok in line.replace('=', ' ').split():
        if tok.endswith('.mp4'):
            return tok.split('/')[-1], tok
    name = ed.dev.sh('ls -t /sdcard/DCIM/NightShift | grep ns_fx_2fe03193 | head -1').strip()
    return name, f'/sdcard/DCIM/NightShift/{name}'


def _field_edit_moves(ed, r):
    """Field 21:50:44-21:51:05: Edit tool, drag the clip around the canvas, scrub the timeline."""
    ed.step('field: Edit tool (ve_edit_tool_btn)')
    t0 = ed.log_mark()
    ed.clip_tools()
    ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=10, since=t0, why='Edit tool opened free crop on clip 0')
    s = ed.screen()
    cx, cy = s.find(('id:surface_view',)).center
    for _ in range(r.randint(2, 3)):
        t0 = ed.log_mark()
        ed.dev.swipe(cx, cy, cx - r.randint(80, 220), cy + r.randint(-60, 60), r.randint(500, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0 shift_x -?0\.\d*[1-9]', timeout=8, since=t0, why='canvas drag moved clip 0')
    for _ in range(2):
        t0 = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.4, 0.4), r.randint(300, 700))
        ed.require_log(r'VideoPlayer::seek requested', timeout=8, since=t0, why='timeline scrub')


def _reverse(ed, pattern, timeout, why):
    t0 = ed.log_mark()
    ed.reverse_clip()
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0', timeout=10, since=t0, why=why + ' (REVERSE handler ran)')
    ed.require_log(pattern, timeout=timeout, since=t0, why=why)
    ed.idle(2)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a(ed, r):
    """FULL: Crashlytics/Play 2fe03193 - Reverse, Reverse back, Reverse again: the 3rd takes the cached branch -> replace_media SIGSEGV."""
    ed.dev.clear_app_cache()                         # no stale cache/<clip>: the first Reverse is a real reverse
    mark = ed.log_mark()
    ed.open_fixture('2fe03193')
    _clip_name(ed, mark)
    ed.set_playing(False)
    _field_edit_moves(ed, r)
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/', 180, 'Reverse #1: real reverse writes cache/<clip>')
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path', 30, 'Reverse #2: back to the original (handleOriginal)')
    _field_edit_moves(ed, r)
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/', 30, 'Reverse #3: cached branch -> replaceMedia')
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b(ed, r):
    """HYBRID: Crashlytics/Play 2fe03193 - video-only mp4 already at cache/<clip name>, then the field's Edit + Reverse taps."""
    mark = ed.log_mark()
    ed.open_fixture('2fe03193')
    name, src = _clip_name(ed, mark)
    ed.dev.plant_app_file(src, f'cache/{name}', video_only=True, min_bytes=100000)   # HYBRID
    ed.set_playing(False)
    _field_edit_moves(ed, r)
    ed.step('TRIGGER: Reverse on clip 0 (cached branch)')
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/', 30, 'Reverse took the cached branch -> replaceMedia')
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c(ed, r):
    """FULL: Crashlytics/Play 2fe03193 on a slow phone - the reverse muxer outruns the audio thread, the cached reverse has no audio."""
    ed.dev.clear_app_cache()
    mark = ed.log_mark()
    ed.open_fixture('2fe03193')
    _clip_name(ed, mark)
    ed.set_playing(False)
    _field_edit_moves(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.dev.busy_storage(True)
        _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/', 300, 'Reverse #1 on a slow phone writes cache/<clip>')
    finally:
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path', 30, 'Reverse #2: back to the original')
    ed.trim_memory('RUNNING_CRITICAL')
    _field_edit_moves(ed, r)
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/', 30, 'Reverse #3: cached branch -> replaceMedia')
    ed.settle(5)


# 2026-11-03 13:34 attempt 1
# Night Shift tapflow: Crashlytics/Play [libmedia.so] SIGSEGV in AMediaCodec_configure <- AudioMCDecoder::reset_state
# <- VideoEngine::replace_media (Reverse swaps a clip with audio for a cached video-only mp4).

FX = '2fe03193'
CLIP_DIR = '/storage/emulated/0/DCIM/NightShift'


def _clip_name(ed):
    """File name of the fixture's clip (the REVERSE handler's cache key is cacheDir/<photoUri file name>)."""
    name = ed.dev.sh(f'ls -t {CLIP_DIR} | grep ns_fx_{FX} | head -1').strip()
    if not name:
        raise UIError('fixture clip not found in DCIM/NightShift')
    return name


def _reverse(ed, pattern, timeout, why):
    """Edit tab -> Reverse tap; checks the engine message that tap must send."""
    t0 = ed.log_mark()
    ed.reverse_clip()
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, since=t0, why=why + ' (speed reset)')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0', timeout=10, since=t0, why=why + ' (trim reset)')
    return ed.require_log(pattern, timeout=timeout, since=t0, why=why)


def _field_edit_moves(ed, r):
    """Field: ve_edit_tool_btn, canvas drags (MsgApplyFreeShift), scrubs (VideoPlayer::seek)."""
    t0 = ed.log_mark()
    ed.ui.tap(T.EDIT)
    ed.require_log(r've_edit_tool_btn|MsgApplyFreeShift: media_layer 0', timeout=10, since=t0, why='edit tool')
    c = ed.screen().find(('id:surface_view',)).center
    for _ in range(r.randint(2, 4)):
        t1 = ed.log_mark()
        dx, dy = r.randint(-250, 250), r.randint(-120, 120)
        ed.dev.swipe(c[0], c[1], c[0] + dx, c[1] + dy, r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=8, since=t1, why='canvas drag')
    for _ in range(r.randint(2, 3)):
        t1 = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.5, 0.5), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested', timeout=8, since=t1, why='scrub')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a(ed, r):
    """FULL: Crashlytics [libmedia.so] replace_media SIGSEGV - real reverse writes cache/<clip>, revert, Reverse again (cached)."""
    ed.dev.clear_app_cache()                               # no leftover cache/<clip>: the first Reverse is a real one
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    _field_edit_moves(ed, r)
    ed.step('reverse 1: real reverse transcode into cache/<clip>')
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), 300, 'first reverse done')
    ed.idle(3)
    ed.step('reverse 2: back to the original (handleOriginal)')
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*' + re.escape(name), 30, 'revert to original')
    ed.idle(3)
    _field_edit_moves(ed, r)
    ed.step('reverse 3 (TRIGGER): cached branch -> replace_media with the cached file')
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), 30, 'cached reverse')
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b(ed, r):
    """HYBRID: Crashlytics [libmedia.so] replace_media SIGSEGV - video-only mp4 at cache/<clip>, field edit moves, Reverse tap."""
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    ed.dev.plant_app_file(f'{CLIP_DIR}/{name}', f'cache/{name}', video_only=True, min_bytes=100000)  # HYBRID
    _field_edit_moves(ed, r)
    ed.step('TRIGGER: Reverse -> cached branch -> MsgReplaceVideo with the video-only file')
    _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), 30, 'cached reverse')
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c(ed, r):
    """HYBRID: Crashlytics [libmedia.so] replace_media SIGSEGV - as b on a slow, memory-pressed phone with a seek storm first."""
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    ed.dev.plant_app_file(f'{CLIP_DIR}/{name}', f'cache/{name}', video_only=True, min_bytes=100000)  # HYBRID
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.trim_memory('RUNNING_CRITICAL')
        _field_edit_moves(ed, r)
        t0 = ed.log_mark()
        ed.seek_storm(r.randint(6, 12), 40, 160, 0.05)       # field: seek gens 25-49 right before the edit tool
        ed.require_log(r'VideoPlayer::seek requested', timeout=10, since=t0, why='seek storm')
        ed.step('TRIGGER: Reverse while seeks are still settling')
        _reverse(ed, r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), 45, 'cached reverse')
        ed.settle(10)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-03 13:45 attempt 2
# Night Shift tapflow: Crashlytics/Play [libmedia.so] SIGSEGV in AMediaCodec_configure <- AudioMCDecoder::reset_state
# <- VideoEngine::replace_media (Reverse swaps a clip with audio for a cached mp4 that has no audio track).

FX = '2fe03193'
CLIP_DIR = '/storage/emulated/0/DCIM/NightShift'
CACHE = '/data/user/0/com.myzesty/cache'


def _clip_name(ed):
    """File name of the fixture clip: the REVERSE handler's cache key is cacheDir/<photoUri file name>."""
    name = ed.dev.sh(f'ls -t {CLIP_DIR} | grep ns_fx_{FX} | head -1').strip()
    if not name:
        raise UIError('fixture clip not found in DCIM/NightShift')
    return name


def _cache_size(ed, name):
    out = ed.dev.sh(f'run-as com.myzesty stat -c %s {CACHE}/{name} 2>/dev/null').strip()
    ed.log(f'    cache/{name} size: {out or "absent"}')
    return int(out) if out.isdigit() else 0


def _reverse_tap(ed, why):
    """Edit -> Reverse; the handler always sends speed 1 + trim 0..duration first (PlayerActivity.kt:5396-5398)."""
    t0 = ed.log_mark()
    ed.reverse_clip()
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, since=t0, why=why + ' (speed reset)')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0', timeout=10, since=t0, why=why + ' (trim reset)')
    return t0


def _field_edit_moves(ed, r):
    """Field: ve_edit_tool_btn, canvas drags (MsgApplyFreeShift), scrubs (VideoPlayer::seek)."""
    ed.main_nav()                                          # after a Reverse the clip-tools panel stays open
    t0 = ed.log_mark()
    ed.ui.tap(T.EDIT)
    ed.require_log(r've_edit_tool_btn|MsgApplyFreeShift: media_layer 0', timeout=10, since=t0, why='edit tool')
    c = ed.screen().find(('id:surface_view',)).center
    for _ in range(r.randint(2, 4)):
        t1 = ed.log_mark()
        ed.dev.swipe(c[0], c[1], c[0] + r.randint(-250, 250), c[1] + r.randint(-120, 120), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=8, since=t1, why='canvas drag')
    for _ in range(r.randint(2, 3)):
        t1 = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.5, 0.5), r.randint(150, 400))
        ed.require_log(r'VideoPlayer::seek requested', timeout=8, since=t1, why='scrub')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_a(ed, r):
    """FULL: Crashlytics [libmedia.so] replace_media SIGSEGV - Reverse, Home mid-reverse (file kept), back, Reverse (cached)."""
    ed.dev.clear_app_cache()                               # no leftover cache/<clip>: the first Reverse is real
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    _field_edit_moves(ed, r)
    ed.step('reverse 1: real reverse transcode, then Home mid-way (onPause aborts it, the file is NOT deleted)')
    t0 = _reverse_tap(ed, 'first reverse')
    ed.require_log(r'File opened successfully, Path: .*/cache/' + re.escape(name), timeout=15, since=t0, why='reverse muxer open')
    ed.idle(r.uniform(3, 12))
    t1 = ed.log_mark()
    ed.background(r.uniform(3, 8))                         # Home + back: JobLifecycleObserver.onPause -> abortReverse
    ed.require_log(r've_on_pause', timeout=10, since=t1, why='app paused during reverse')
    _cache_size(ed, name)
    _field_edit_moves(ed, r)
    ed.step('reverse 2 (TRIGGER): cachedFile.exists() -> handleReverse -> MsgReplaceVideo with the left-over file')
    t2 = _reverse_tap(ed, 'cached reverse')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), timeout=30, since=t2, why='cached reverse')
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_b(ed, r):
    """HYBRID: Crashlytics [libmedia.so] replace_media SIGSEGV - video-only mp4 at cache/<clip>, field edit moves, Reverse tap."""
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    ed.dev.plant_app_file(f'{CLIP_DIR}/{name}', f'cache/{name}', video_only=True, min_bytes=100000)  # HYBRID
    if _cache_size(ed, name) < 100000:                     # HYBRID
        raise UIError('video-only plant missing or too small')
    _field_edit_moves(ed, r)
    ed.step('TRIGGER: Reverse -> cached branch -> MsgReplaceVideo with the video-only file')
    t0 = _reverse_tap(ed, 'cached reverse')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), timeout=30, since=t0, why='cached reverse')
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_2_c(ed, r):
    """HYBRID: Crashlytics [libmedia.so] replace_media SIGSEGV - as b on a slow, memory-pressed phone after a seek storm."""
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    ed.dev.plant_app_file(f'{CLIP_DIR}/{name}', f'cache/{name}', video_only=True, min_bytes=100000)  # HYBRID
    if _cache_size(ed, name) < 100000:                     # HYBRID
        raise UIError('video-only plant missing or too small')
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.trim_memory('RUNNING_CRITICAL')
        t0 = ed.log_mark()
        ed.seek_storm(r.randint(6, 12), 40, 160, 0.05)     # field: seek gens 25-49 right before the edit tool
        ed.require_log(r'VideoPlayer::seek requested', timeout=10, since=t0, why='seek storm')
        _field_edit_moves(ed, r)
        ed.step('TRIGGER: Reverse while seeks are still settling')
        t1 = _reverse_tap(ed, 'cached reverse')
        ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), timeout=45, since=t1, why='cached reverse')
        ed.settle(10)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-03 13:54 attempt 3
# Night Shift tapflow: Crashlytics/Play [libmedia.so] SIGSEGV in AMediaCodec_configure <- AudioMCDecoder::reset_state
# <- VideoEngine::replace_media (Reverse swaps a clip with audio for a cached reversed mp4 that has no audio track).

FX = '2fe03193'
FX_TRANSCODED = '6e2486dd'                                  # fresh transcode: audio comes from MsgTriggerAudioTranscode
CLIP_DIR = '/storage/emulated/0/DCIM/NightShift'
CACHE = '/data/user/0/com.myzesty/cache'


def _clip_name(ed):
    """The REVERSE handler's cache key is cacheDir/<photoUri file name> (VideoReverse.kt:202)."""
    name = ed.dev.sh(f'ls -t {CLIP_DIR} | grep ns_fx_{FX} | head -1').strip()
    if not name:
        raise UIError('fixture clip not found in DCIM/NightShift')
    return name


def _size(ed, path):
    out = ed.dev.sh(f'run-as com.myzesty stat -c %s {path} 2>/dev/null || stat -c %s {path} 2>/dev/null').strip()
    ed.log(f'    {path} size: {out or "absent"}')
    return int(out) if out.isdigit() else 0


def _reverse(ed, why, replace_re, timeout):
    """Edit -> Reverse: speed 1 + trim reset (PlayerActivity.kt:5396-5398), then the MsgReplaceVideo we expect."""
    t0 = ed.log_mark()
    ed.reverse_clip()
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=10, since=t0, why=why + ' (speed reset)')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0', timeout=10, since=t0, why=why + ' (trim reset)')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path ' + replace_re, timeout=timeout, since=t0, why=why)
    ed.idle(2)


def _flip_cycles(ed, r, n):
    """Reverse (handleOriginal, back to the source) then Reverse (cached branch = TRIGGER); repeated because the
    crash needs the uninitialised `active` to read non-zero in the half-built decoder."""
    for i in range(n):
        ed.step(f'cycle {i + 1}/{n}: Reverse -> original clip')
        _reverse(ed, 'reverse back to original', r'(?!.*/cache/).*', 30)
        ed.step(f'cycle {i + 1}/{n}: TRIGGER Reverse -> cached reversed file')
        _reverse(ed, 'cached reverse (handleReverse)', r'.*/cache/', 15)
        ed.settle(r.uniform(3, 5))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_a(ed, r):
    """FULL: Crashlytics [libmedia.so] replace_media SIGSEGV - real Reverse, Reverse back, Reverse again (cached file)."""
    ed.dev.clear_app_cache()                               # first Reverse must be a real reverse transcode
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    ed.step('reverse 1: real reverse transcode into cache/<clip>, let it finish')
    t0 = ed.log_mark()
    ed.reverse_clip()
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), timeout=15, since=t0, why='real reverse started')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/' + re.escape(name), timeout=180, since=t0, why='reverse finished -> handleReverse')
    ed.settle(4)
    _size(ed, f'{CACHE}/{name}')
    _flip_cycles(ed, r, r.randint(3, 4))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_b(ed, r):
    """HYBRID: Crashlytics [libmedia.so] replace_media SIGSEGV - video-only mp4 at cache/<clip>, then real Reverse taps."""
    ed.open_fixture(FX)
    ed.set_playing(False)
    name = _clip_name(ed)
    src = _size(ed, f'{CLIP_DIR}/{name}')
    ed.dev.plant_app_file(f'{CLIP_DIR}/{name}', f'cache/{name}', video_only=True, min_bytes=100000)  # HYBRID
    planted = _size(ed, f'{CACHE}/{name}')                 # HYBRID
    if planted < 100000 or (src and planted >= src):       # HYBRID: same size as the source = audio was not stripped
        raise UIError(f'video-only plant wrong: {planted} bytes (source {src})')
    ed.step('TRIGGER: Reverse -> cachedFile.exists() -> handleReverse -> MsgReplaceVideo with the video-only file')
    _reverse(ed, 'cached reverse (handleReverse)', r'.*/cache/' + re.escape(name), 15)
    ed.settle(r.uniform(3, 5))
    _flip_cycles(ed, r, r.randint(3, 4))                   # the plant stays: every second Reverse is a fresh trigger


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_3_c(ed, r):
    """FULL: Crashlytics [libmedia.so] replace_media SIGSEGV - transcoded clip (field cache/transcoding-*), slow phone, seeks, Reverse x3."""
    ed.dev.clear_app_cache()
    ed.open_fixture(FX_TRANSCODED)
    ed.set_playing(False)
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.trim_memory('RUNNING_CRITICAL')
        t0 = ed.log_mark()
        ed.seek_storm(r.randint(6, 12), 40, 160, 0.05)     # field: seek gens 25-49 before the edit tool
        ed.require_log(r'VideoPlayer::seek requested', timeout=10, since=t0, why='seek storm')
        ed.step('reverse 1: real reverse of the transcoded clip (video-only source, audio from the audio transcode)')
        t1 = ed.log_mark()
        ed.reverse_clip()
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path .*/cache/', timeout=20, since=t1, why='real reverse started')
        ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path .*/cache/', timeout=300, since=t1, why='reverse finished -> handleReverse')
        ed.settle(5)
        _flip_cycles(ed, r, r.randint(3, 4))
    finally:
        ed.dev.slow_phone(0)
