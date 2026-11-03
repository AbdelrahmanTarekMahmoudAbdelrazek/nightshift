# Night Shift: frozen copy of the registered repro ns_2fe03193_l3_2_b (1103110143); later runs cannot change it
# Night Shift auto repros for 2fe03193209d272d69500de7526df59f


# 2026-11-02 19:14 level 3 attempt 1
def _2fe03193_cache(ed):
    """Log the app's cache/ listing (size of the reversed file); debug build: run-as."""
    out = ed.dev.sh('run-as com.myzesty ls -l cache/ 2>/dev/null | grep -i mp4', timeout=15)
    ed.log(f'    cache/: {out.strip()[:300] or "(no mp4)"}')


def _2fe03193_reverse_tap(ed):
    """Field context: Edit tool, drag the clip on the canvas (shift/rotate), then the Reverse tile (Constants.REVERSE)."""
    ed.set_playing(False)
    ed.clip_tools()                                              # ve_edit_tool_btn
    s = ed.screen()
    if s is not None and s.has('id:surface_view'):
        x, y = s.find('id:surface_view').center
        for _ in range(3):
            ed.dev.swipe(x, y, x + r_dx(), y + r_dx() // 2, 300)  # MsgApplyFreeShift like the field
            ed.idle(0.4)
    ed.menu_tap('reverse')


def r_dx():
    return int(time.time() * 1000) % 120 - 60


def _2fe03193_first_reverse(ed, during=None):
    """Real reverse (no cache yet): MsgReverseVideo; `during(ed)` runs while it encodes; returns True if it completed."""
    m = ed.log_mark()
    _2fe03193_reverse_tap(ed)
    ed.require_log(r'MsgReverseVideo: media_layer 0 media_id 0 path \S+/cache/', 20, since=m,
                   why='first Reverse must run a real reverse into cache/<photoUri name> (checkpoint 2)')
    if during:
        during(ed)
    done = ed.wait_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S+/cache/', 150, since=m)
    _2fe03193_cache(ed)
    return bool(done)


def _2fe03193_cached_reverse(ed, how='tap'):
    """Checkpoint 4: speed/curve/trim preamble then MsgReplaceVideo with the cached file, no MsgReverseVideo."""
    m = ed.log_mark()
    if how == 'redo':
        ed.redo(1)
    else:
        _2fe03193_reverse_tap(ed)
    ed.require_log(r'MsgSetMediaCurveSpeed layer 0 media_id 0 index 0', 15, since=m, why='REVERSE preamble')
    hit = ed.wait_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S+/cache/|MsgReverseVideo', 30, since=m)
    if 'MsgReverseVideo' in hit:
        ed.log('    cached file was gone: a real reverse ran instead of the cached branch')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S+/cache/', 150, since=m,
                   why='cached-branch replace with cache/<photoUri name> (checkpoint 4)')
    ed.settle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l3_1_a_r1103110143(ed, r):
    """Firebase vivo V2150 + Play Vivo T1: complete reverse, app away under critical pressure + camera, back, Reverse->original, Reverse (cached file)."""
    ed.open_fixture('2fe03193')
    m = ed.log_mark()
    ed.require_log(r'MCAudioNormalizer initialized successfully', 20, since=m - 30 if isinstance(m, (int, float)) else m,
                   why='media 0 must have a live audio decoder (checkpoint 1)')
    if not _2fe03193_first_reverse(ed):
        raise UIError('first reverse did not finish into cache/')
    background_keep_screen(ed, r.uniform(15, 30), pressure='RUNNING_CRITICAL', camera=True)
    m = ed.log_mark()
    _2fe03193_reverse_tap(ed)                                   # reversed clip -> handleOriginal (photoUri)
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path (?!\S+/cache/)\S+', 30, since=m,
                   why='second Reverse must restore the original')
    ed.idle(2)
    _2fe03193_cached_reverse(ed, 'tap')


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l3_1_b_r1103110143(ed, r):
    """Firebase vivo V2150 + Play Vivo T1: Home + camera + critical pressure in the MIDDLE of the reverse (abort), back, Reverse (cached file if left)."""
    ed.open_fixture('2fe03193')
    def away(ed):
        ed.idle(r.uniform(4, 9))                                # into the encode phase of a ~15-25 s reverse
        background_keep_screen(ed, r.uniform(8, 20), pressure='RUNNING_CRITICAL', camera=True)
    done = _2fe03193_first_reverse(ed, during=away)
    ed.log(f'    reverse finished before the app went away: {done}')
    ed.idle(2)
    if done:                                                    # clip is reversed: back to the original first
        _2fe03193_reverse_tap(ed)
        ed.idle(3)
    _2fe03193_cached_reverse(ed, 'tap')


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l3_1_c_r1103110143(ed, r):
    """Firebase vivo V2150 + Play Vivo T1: reverse on a slow phone with slow storage, then Undo + Redo of the reverse (fromStack cached branch)."""
    ed.open_fixture('2fe03193')
    ed.dev.slow_phone(r.randint(30, 45))
    ed.dev.busy_storage(True)
    try:
        ok = _2fe03193_first_reverse(ed)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)
    if not ok:
        raise UIError('first reverse did not finish into cache/')
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
    m = ed.log_mark()
    ed.undo(1)                                                  # undo REVERSE -> handleOriginal
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path (?!\S+/cache/)\S+', 30, since=m,
                   why='undo of the reverse must restore the original')
    ed.idle(2)
    _2fe03193_cached_reverse(ed, 'redo')                        # redo -> fromStack, cachedFile.exists()


# 2026-11-02 19:28 level 3 attempt 2
def _2fe03193_open(ed):
    """Open the fixture; checkpoint 1: media 0 comes from durable media (not cache/). Returns its file name."""
    m = ed.log_mark()
    ed.open_fixture('2fe03193')
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: (?!\S*/cache/)\S+', 40, since=m,
                          why='media 0 with audio from durable media (checkpoint 1)')
    path = re.search(r'path: (\S+?),', line).group(1)
    return path.rsplit('/', 1)[1]


def _2fe03193_plant(ed, name, secs):
    """Checkpoint 2: a VALID video-only mp4 (adb screenrecord: H.264, no audio track) at cache/<photoUri name>."""
    ed.step(f'plant a {secs}s video-only mp4 at cache/{name}')
    src = '/sdcard/Download/ns_2fe03193_noaudio.mp4'
    ed.dev.sh(f'rm -f {src}; screenrecord --time-limit {secs} --bit-rate 2000000 --size 720x1600 {src}', timeout=secs + 30)
    ed.dev.sh(f'run-as {PKG} rm -f cache/{name}')
    ed.dev.sh(f"cat {src} | run-as {PKG} sh -c 'cat > cache/{name}'", timeout=60)
    size = ed.dev.sh(f'run-as {PKG} stat -c %s cache/{name}').strip()
    ed.log(f'    planted cache/{name}: {size} bytes')
    if not size.isdigit() or int(size) < 50000:
        raise UIError(f'video-only cache file was not planted (size {size!r})')


def _2fe03193_edit_drag(ed, drags=3):
    """Checkpoint 3: Edit tool (ve_edit_tool_btn), then drag the clip on the canvas (MsgApplyFreeShift)."""
    ed.set_playing(False)
    m = ed.log_mark()
    try:
        ed.clip_tools()
    except UIError:
        ed.tap_tool('edit')
    ed.require_log(r'Event: \S*ve_edit_tool_btn', 10, since=m, why='Edit tool open (checkpoint 3)')
    s = ed.screen()
    if s is not None and s.has('id:surface_view'):
        x, y = s.find('id:surface_view').center
        for _ in range(drags):
            ed.dev.swipe(x, y, x + ed.rng.randint(-80, 80), y + ed.rng.randint(-60, 60), 300)
            ed.idle(0.4)


def _2fe03193_reverse_cached(ed, name):
    """Checkpoint 4/5: Reverse tile -> preamble -> MsgReplaceVideo cache/<name>, no transcode -> 'no audio' -> crash."""
    m = ed.log_mark()
    try:
        ed.menu_tap('reverse')
    except UIError:
        ed.tap_tool('reverse')
    ed.require_log(r'MsgSetMediaCurveSpeed layer 0 media_id 0 index 0', 15, since=m, why='REVERSE preamble (checkpoint 4)')
    hit = ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S+/cache/|MsgReverseVideo', 30, since=m,
                         why='cached-file branch replace (checkpoint 4)')
    if 'MsgReverseVideo' in hit or name not in hit:
        raise UIError(f'Reverse did not take the cached branch for cache/{name}: {hit[-120:]}')
    bad = ed.wait_log(r'incorrect file', 4, since=m)
    if bad:
        raise UIError('planted cache file rejected by the extractor (incorrect file), not the field no-audio path')
    ed.require_log(r'-Error-Audio-Constructor- no audio', 10, since=m, why='no-audio early return (checkpoint 5)')
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l3_2_a_r1103110143(ed, r):
    """Firebase vivo V2150 (+ Play Vivo T1, same stack): video-only cached reverse file present, Edit + canvas drag, Reverse tap."""
    name = _2fe03193_open(ed)
    _2fe03193_plant(ed, name, 12)
    _2fe03193_edit_drag(ed, r.randint(3, 6))
    _2fe03193_reverse_cached(ed, name)


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l3_2_b_r1103110143(ed, r):
    """Firebase vivo V2150 seeks + Play Vivo T1: video-only cached file, Edit, drag, scrub seeks under critical memory pressure, Reverse."""
    name = _2fe03193_open(ed)
    _2fe03193_plant(ed, name, 20)
    _2fe03193_edit_drag(ed, r.randint(2, 4))
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_CRITICAL')
    for _ in range(r.randint(4, 7)):                      # field: VideoPlayer::seek ... interrupted by new seek
        ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(60, 200))
        ed.idle(r.uniform(0.1, 0.4))
    ed.idle(1.5)
    _2fe03193_reverse_cached(ed, name)


@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_l3_2_c_r1103110143(ed, r):
    """Play Vivo T1 5G + Firebase vivo V2150 (low-end Vivo): full-length video-only cached file, Reverse on a slow phone with slow storage."""
    name = _2fe03193_open(ed)
    _2fe03193_plant(ed, name, 35)
    _2fe03193_edit_drag(ed, 2)
    ed.dev.slow_phone(r.randint(30, 45))
    ed.dev.busy_storage(True)
    try:
        _2fe03193_reverse_cached(ed, name)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)
