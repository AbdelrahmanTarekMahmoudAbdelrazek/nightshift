# Night Shift focused repro for 501bb526 (hand-written 2026-10-22, from the field log + yesterday's lab facts)
#
# Field: a long clip with several freezes; a speed change makes the engine re-extract EVERY freeze on the layer
# (set_video_speed -> reset_freeze_images + time_loader_for_freeze) on the MsgLooper thread, while
# PlayerActivity.freezeLoader() spins on main in Player.freezeProgress(). On a slow phone that takes > 5 s -> ANR.
# This recipe: (1) a project with ONE long clip at speed 1.0 and 5 real Freeze-tool freezes spread over it, built once
# per device and kept as fixture "501bb526f" (snapshot restored before every run); (2) speed applies on that clip,
# small changes only (a big speed-up pushes the freezes out of the clip, which is the OTHER, endless form).

_F5_KEY = '501bb526f'
_F5_FRZ = r'MsgAddVideoFreezeDuration:\s+start_time \d+ , end_time \d+,layer_id 0'


def _f5_newest(ed, path):
    """Make `path` the gallery's newest video (the picker sorts by MediaStore date_modified) -> its tile index."""
    real = path.replace('/sdcard/', '/storage/emulated/0/')
    name = path.rsplit('/', 1)[-1]
    for c in (f'content call --uri content://media --method scan_file --arg {real}',
              'content call --uri content://media --method scan_volume --arg external_primary'):
        ed.dev.sh(c, timeout=300)
        time.sleep(4)
        rows = ed.dev.sh('content query --uri content://media/external/video/media --projection _data:date_modified '
                         '--sort "date_modified DESC"', timeout=60)
        names = [m.group(1).rsplit('/', 1)[-1] for m in re.finditer(r'Row: \d+ _data=(\S+?),', rows)]
        if name in names and names.index(name) < 9:
            return names.index(name)
    raise UIError(f'the long test clip {name} is not among the first gallery tiles')


def _f5_build(ed):
    ed.step('focus: build the long-clip project with 5 freezes (once per device)')
    ed.fixture_begin()
    src = ed.dev.fresh_video(tag='f5long', duration_s=100)          # the gallery clip closest to 100 s, new path
    os.environ['ZESTY_PICK_TILE'] = str(_f5_newest(ed, src))
    ed.dev.restore_env()
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
    os.environ.pop('ZESTY_PICK_TILE', None)
    ed.require_log(r'MsgAddVideo: media_layer 0', 240, since=mark, why='the long clip reached the engine')
    ed.settle(3)
    ed.main_nav()
    ed.set_playing(False)
    _, tot = ed.read_time()
    if not tot or tot < 60:
        raise UIError(f'the new project is {tot} s long; it needs a clip of 60 s or more')
    ed.tap_tool('freeze')
    for i, f in enumerate((0.15, 0.3, 0.45, 0.6, 0.75)):        # ascending: the play-forward seek never goes back
        ed.step(f'focus: freeze {i + 1} at {f:.0%}')
        _fx_501bb526_freeze(ed, f * tot + 1.4 * i, i + 1)         # helper in fx_501bb526.py (long-press = real freeze)
    ed.main_nav()
    ed.idle(2)
    ed.save_fixture(_F5_KEY, f'one {tot:.0f} s clip at speed 1.0 with 5 Freeze-tool freezes at 15-75% (layer 0)')


def _f5_speed(ed, step_frac):
    """Speed tool on the selected clip: move the bar a little and APPLY (only apply sends MsgSetVideoSpeed and runs
    freezeLoader on main). Then touch the screen while main is blocked, as the user did, so input dispatch times out."""
    ed.clip_tool('speed')
    s = ed.ui.wait(T.SPEED_BAR, timeout=8)
    if s is None:
        raise UIError('speed bar not found')
    l, t, r, b = s.find(T.SPEED_BAR).b
    y, x0 = (t + b) // 2, (l + r) // 2
    mark = ed.log_mark()
    ed.dev.swipe(x0, y, int(x0 + (r - l) * step_frac), y, 400)
    ed.idle(0.6)
    s = ed.screen()
    if s is None or not s.has(T.DONE):
        raise UIError('speed: no apply button')
    ed.dev.tap(*s.find(T.DONE).center)
    if not ed.wait_log(r'MsgSetVideoSpeed', 8, since=mark):
        raise UIError('speed apply did not reach the engine (no MsgSetVideoSpeed)')
    for _ in range(4):                                             # taps during the block -> MotionEvent ANR like the field
        time.sleep(1.5)
        ed.dev.tap((l + r) // 2, max(200, t - 400))
    ed.idle(20)                                                    # the ANR arrives ~8-10 s after the block starts


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_focus(ed, r):
    """Focused 501bb526: long clip + 5 freezes, small speed applies; the freeze re-extraction must block main > 5 s."""
    mark = ed.log_mark()
    try:
        ed.open_fixture(_F5_KEY)
    except UIError:
        _f5_build(ed)
        mark = ed.log_mark()                                       # the freezes load DURING open: mark before it
        ed.open_fixture(_F5_KEY)
    ed.require_log(r'MsgFreezeLoader layer_id 0', 40, since=mark, why='the project loads its freezes (Kotlin FREEZE items)')
    ed.settle(3)
    for k, frac in enumerate((0.08, -0.08, 0.12, -0.12, 0.06)):   # ~1x <-> ~1.5x: freezes stay inside the clip
        ed.step(f'focus: speed apply {k + 1}/5')
        _f5_speed(ed, frac)


def _f5_measure_apply(ed, k, frac):
    """One speed apply; returns (main-thread skipped frames in the 5 s after it, worst single skip, engine reloads
    skipped as 'unchanged', MsgSetVideoSpeed count)."""
    mark = ed.log_mark()
    ed.clip_tool('speed')
    s = ed.ui.wait(T.SPEED_BAR, timeout=8)
    if s is None:
        raise UIError('speed bar not found')
    l, t, r, b = s.find(T.SPEED_BAR).b
    y, x0 = (t + b) // 2, (l + r) // 2
    ed.dev.swipe(x0, y, int(x0 + (r - l) * frac), y, 400)
    ed.idle(0.6)
    s = ed.screen()
    if s is None or not s.has(T.DONE):
        raise UIError('speed: no apply button')
    t_apply = time.time()
    ed.dev.tap(*s.find(T.DONE).center)
    if not ed.wait_log(r'MsgSetVideoSpeed', 8, since=mark):
        raise UIError('speed apply did not reach the engine (no MsgSetVideoSpeed)')
    for _ in range(3):                                   # touches while the engine works, like the user
        time.sleep(1.0)
        ed.dev.tap((l + r) // 2, max(200, t - 400))
    ed.idle(max(0.0, 6 - (time.time() - t_apply)))
    pid = ed.dev.pid()
    lc = ed.dev.sh(f"logcat -d -T '{mark}'", timeout=30)
    skips = [int(m.group(1)) for m in re.finditer(rf'\s{pid}\s+{pid}\s.*Choreographer: Skipped (\d+) frames', lc)] if pid else []
    kept = len(re.findall(r'freezes kept \(no re-extraction\)', lc))
    sets = len(re.findall(r'MsgSetVideoSpeed: speed', lc))
    ed.log(f'    MEASURE apply {k}: main skipped {sum(skips)} frames (~{sum(skips) * 16.7 / 1000:.2f} s, worst '
           f'{max(skips or [0]) * 16.7 / 1000:.2f} s); MsgSetVideoSpeed x{sets}, re-extractions skipped {kept}')
    return sum(skips), max(skips or [0]), kept, sets


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_measure(ed, r):
    """Measure for 501bb526: main-thread block after each speed apply on the 5-freeze project (before/after a fix)."""
    mark = ed.log_mark()
    ed.open_fixture(_F5_KEY)
    ed.require_log(r'MsgFreezeLoader layer_id 0', 40, since=mark, why='the project loads its freezes')
    ed.settle(3)
    ed.dev.sh('setprop debug.zesty.mainwatch_ms 300')   # the lab watch samples main blocks over 0.3 s (what blocks it)
    tot = []
    for k, frac in enumerate((0.08, -0.08, 0.12, -0.12, 0.06, 0.0), 1):   # the last one applies the SAME speed
        ed.step(f'measure: speed apply {k}/6')
        tot.append(_f5_measure_apply(ed, k, frac))
    ed.dev.sh('setprop debug.zesty.mainwatch_ms 4000')
    lc = ed.dev.sh(f"logcat -d -s ZestyLab:W -T '{mark}'", timeout=60)
    tops = {}
    for blk in re.findall(r'LAB MAINSTACK begin[^\n]*\n((?:[^\n]*LAB MAINSTACK   at [^\n]*\n){1,60})', lc):
        frames = [x.split('LAB MAINSTACK   at ', 1)[1].strip() for x in blk.splitlines()]
        app = [f for f in frames if 'myzesty' in f][:3]           # the app's own frames say what main was waiting in
        key = ' <- '.join(app or frames[:3])
        tops[key] = tops.get(key, 0) + 1
    for k_, n_ in sorted(tops.items(), key=lambda x: -x[1])[:6]:
        ed.log(f'    MEASURE main blocked in ({n_}x): {k_[:300]}')
    ed.log(f'    MEASURE total: main skipped {sum(x[0] for x in tot)} frames (~{sum(x[0] for x in tot) * 16.7 / 1000:.2f} s) '
           f'over {len(tot)} applies; worst single block {max(x[1] for x in tot) * 16.7 / 1000:.2f} s; '
           f're-extractions skipped {sum(x[2] for x in tot)} of {sum(x[3] for x in tot)} speed sets')
