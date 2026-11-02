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
