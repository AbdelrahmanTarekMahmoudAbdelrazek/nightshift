# Night Shift: frozen copy of the registered repro ns_2fe03193_l5_1_a (1103140620); later runs cannot change it
# Night Shift auto repros for 2fe03193209d272d69500de7526df59f


# 2026-11-03 14:03 level 5 attempt 1
_2FE_EDIT_EVT = r'Event: (test_)?ve_edit_tool_btn'
_2FE_PRE = r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0\.0+'
_2FE_REPL_CACHE = r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/\S+'
_2FE_HOOK = 'debug.zesty.hook.no_audio_replace'


def _2fe03193_open(ed):
    """Fixture clip with audio on layer 0; returns (source path, cache-file basename)."""
    t0 = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: [^,\s]+', timeout=30, since=t0, why='fixture clip 0 loaded')
    src = line.split('path:', 1)[1].split(',')[0].strip()
    ed.idle(3)
    ed.set_playing(False)
    return src, src.rsplit('/', 1)[-1]


def _2fe03193_edit_drag(ed, r):
    """Field: ve_edit_tool_btn, then drags of the clip on the canvas (MsgApplyFreeShift/Rotate on layer 0 id 0)."""
    t0 = ed.log_mark()
    ed.ui.tap(T.EDIT, timeout=10)
    ed.require_log(_2FE_EDIT_EVT, timeout=8, since=t0, why='Edit tool opened (field last user action)')
    for _ in range(r.randint(2, 4)):
        t0 = ed.log_mark()
        ed.dev.swipe(360, 520, 360 + r.randint(-200, 200), 520 + r.randint(-150, 150), r.randint(400, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=6, since=t0, why='canvas drag')
        ed.idle(r.uniform(0.3, 0.8))


def _2fe03193_reverse(ed, why):
    if not ed.in_clip_tools():
        ed.clip_tools()
    t0 = ed.log_mark()
    ed.clip_tool('reverse')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=8, since=t0, why=why + ': speed 1')
    ed.require_log(_2FE_PRE, timeout=8, since=t0, why=why + ': trim 0..orig')
    return t0


def _2fe03193_crash_wait(ed, t0):
    ed.require_log(r'-Error-Audio-Constructor- no audio', timeout=10, since=t0, why='hook: new decoder half-built')
    ed.idle(6)                                       # the SIGSEGV in reset_state lands here


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l5_1_a_r1103140620(ed, r):
    """Firebase vivo V2150: cached-branch Reverse after Edit+drags swaps in cache/<clip> seen as audio-less (hook)."""
    src, base = _2fe03193_open(ed)
    if src.startswith('/storage') or src.startswith('/sdcard'):
        ed.dev.plant_app_file(src, f'cache/{base}', min_bytes=100000)    # valid mp4: passes setDataSourceFd
    else:
        ed.dev.sh(f"run-as com.myzesty sh -c 'cp {src} cache/{base}'")
    _2fe03193_edit_drag(ed, r)
    ed.dev.setprop(_2FE_HOOK, '1')
    try:
        t0 = _2fe03193_reverse(ed, 'trigger Reverse')
        ed.require_log(_2FE_REPL_CACHE, timeout=3, since=t0, why='cached branch: replace ~0.1 s after trim')
        _2fe03193_crash_wait(ed, t0)
    finally:
        ed.dev.setprop(_2FE_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l5_1_b_r1103140620(ed, r):
    """Play Vivo T1 5G (stack only): uncached Reverse, the real reverse output replaces the clip, seen as audio-less (hook)."""
    src, base = _2fe03193_open(ed)
    ed.dev.clear_app_cache(base)                     # no cache/<clip>: a real reverse must run
    _2fe03193_edit_drag(ed, r)
    ed.dev.setprop(_2FE_HOOK, '1')
    try:
        t0 = _2fe03193_reverse(ed, 'Reverse (uncached)')
        ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=10, since=t0, why='real reverse runs')
        ed.require_log(_2FE_REPL_CACHE, timeout=120, since=t0, why='reverse done -> replaceMedia')
        _2fe03193_crash_wait(ed, t0)
    finally:
        ed.dev.setprop(_2FE_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l5_1_c_r1103140620(ed, r):
    """Field trigger variant: real Reverse, Undo, then Redo (fromStack) reuses cache/<clip>, seen as audio-less (hook)."""
    src, base = _2fe03193_open(ed)
    ed.dev.clear_app_cache(base)
    _2fe03193_edit_drag(ed, r)
    t0 = _2fe03193_reverse(ed, 'Reverse #1 (hook off)')
    ed.require_log(_2FE_REPL_CACHE, timeout=120, since=t0, why='first reverse finished normally')
    ed.idle(r.uniform(2, 4))
    t0 = ed.log_mark()
    ed.undo(1)
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path (?!\S*/cache/)\S+', timeout=10, since=t0, why='undo -> original clip')
    ed.idle(r.uniform(1.5, 3))
    _2fe03193_edit_drag(ed, r)
    ed.dev.setprop(_2FE_HOOK, '1')
    try:
        t0 = ed.log_mark()
        ed.redo(1)
        ed.require_log(_2FE_PRE, timeout=8, since=t0, why='redo runs the REVERSE preamble (fromStack)')
        ed.require_log(_2FE_REPL_CACHE, timeout=3, since=t0, why='redo takes the cached branch')
        _2fe03193_crash_wait(ed, t0)
    finally:
        ed.dev.setprop(_2FE_HOOK, '0')
