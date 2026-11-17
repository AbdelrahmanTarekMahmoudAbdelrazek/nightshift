# Night Shift engine replays for 2bc43cd6d24a25e5305f8167703618a8~e6a57918 (turbo)


# 2026-11-03 20:37 attempt 1
CACHE = '/data/user/0/com.myzesty/cache'

def _out(lines):
    return (lines or ['-> 0'])[-1].rsplit('->', 1)[-1].strip()

def _clip(ed, want):
    lens = [l for l in (ed.dev.video_lengths() or []) if l[1] >= 2]
    d = min(lens, key=lambda l: abs(l[1] - want))[1] if lens else want
    p = ed.dev.fresh_video(tag='rbg', duration_s=d)
    return p, d

def _add(p, d, layer):
    return f'addVideo({p},{int(d * 30)}.0,{d * 1000:.1f},{layer})'

def _running(ed):
    s = _out(ed.jni('nativeRemoveBgBuildProgress()')).strip('[]() ').split(',')
    try:
        return int(s[2].strip()) == 1
    except (IndexError, ValueError):
        return True

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_a(ed, r):
    """Crashlytics ge6a5791 (ev1): changeVisualMediaLayer of the overlay a live inference build is streaming into."""
    p, d = _clip(ed, 17)
    ed.jni(f'initNativeSegmenter(1,{CACHE})')
    a = int(_out(ed.jni(_add(p, d, 2))))
    ed.jni(_add(p, d, 2))                       # 2nd clip keeps [2][a] in range after each move, so the build lives on
    n1 = int(_out(ed.jni('getMediaCounts(1)')))
    ed.jni(f'startNativeRemoveBgBuild({a},1,{CACHE},2);sleep(2500)')
    cyc = f'changeVisualMediaLayer({a},2,1);getMediaCounts(2);changeVisualMediaLayer({n1},1,2);getMediaCounts(1);sleep(40)'
    for i in range(15):
        if not _running(ed):
            ed.jni(f'startNativeRemoveBgBuild({a},1,{CACHE},2);sleep(1200)')
        ed.jni(';'.join([cyc] * 12))
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_b(ed, r):
    """Crashlytics ge6a5791 (ev2): deleteMedia of media 0 on the layer whose media 1 is being built, then play."""
    p, d = _clip(ed, 22)
    ed.jni(f'initNativeSegmenter(1,{CACHE})')
    base = int(_out(ed.jni(_add(p, d, 1))))
    ed.jni(_add(p, d, 1)); ed.jni(_add(p, d, 1))   # [base, base+1 (built), base+2]
    ed.jni(f'startNativeRemoveBgBuild({base + 1},1,{CACHE},1);sleep(2500)')
    for i in range(14):
        if not _running(ed):
            ed.jni(f'startNativeRemoveBgBuild({base + 1},1,{CACHE},1);sleep(1200)')
        # erase shifts left: the deleted VisualMedia is destroyed while slot base+1 is moved-from (null)
        ed.jni(f'deleteMedia({base},1);{_add(p, d, 1)};resumePlaying();sleep({r.randint(150, 400)});pausePlaying();sleep(100)')
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_c(ed, r):
    """Crashlytics ge6a5791: layer move racing a mask-cache replay burst (dense appends on the builder thread)."""
    p, d = _clip(ed, 3)
    ed.jni(f'initNativeSegmenter(1,{CACHE})')
    a = int(_out(ed.jni(_add(p, d, 2))))
    ed.jni(_add(p, d, 2))
    n1 = int(_out(ed.jni('getMediaCounts(1)')))
    ed.jni(f'startNativeRemoveBgBuild({a},1,{CACHE},2)')
    end = time.time() + 30
    while time.time() < end and _running(ed):  # let the first build finish so it is cached
        time.sleep(1)
    burst = f'startNativeRemoveBgBuild({a},1,{CACHE},2);changeVisualMediaLayer({a},2,1);changeVisualMediaLayer({n1},1,2);sleep({r.randint(5, 40)})'
    for i in range(10):
        ed.jni(';'.join([burst] * 6))
    ed.idle(5)


# 2026-11-03 20:41 attempt 2
CACHE = '/data/user/0/com.myzesty/cache'

def _out(lines):
    try:
        return int((lines or ['-> 0'])[-1].rsplit('->', 1)[-1].strip())
    except ValueError:
        return 0

def _ready(ed):
    ed.idle(4)                                   # rp1 died in Java while the draft was still loading
    for _ in range(10):
        if _out(ed.jni('getMediaCounts(0)')) > 0:
            break
        time.sleep(1)

def _add(p, d, layer):
    return f'addVideo({p},{int(d * 30)}.0,{d * 1000:.1f},{layer})'

def _fresh(ed, want):
    lens = [l for l in (ed.dev.video_lengths() or []) if l[1] >= 2]
    d = min(lens, key=lambda l: abs(l[1] - want))[1] if lens else want
    return ed.dev.fresh_video(tag='rbg', duration_s=d), d

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp2_a(ed, r):
    """Crashlytics ge6a5791 (ev1): changeVisualMediaLayer of [2][0] while live inference appends to it."""
    _ready(ed)
    p, d = _fresh(ed, 17)
    ed.jni(f'initNativeSegmenter(1,{CACHE})')
    ed.jni(_add(p, d, 2)); ed.jni(_add(p, d, 2))          # filler keeps [2][0] valid after each move
    n1 = _out(ed.jni('getMediaCounts(1)'))
    ed.jni(f'startNativeRemoveBgBuild(0,1,{CACHE},2);sleep(2000)')
    for _ in range(8):
        ed.jni(f'changeVisualMediaLayer(0,2,1);changeVisualMediaLayer({n1},1,2);sleep({r.randint(2, 15)})', repeat=60)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp2_b(ed, r):
    """Crashlytics ge6a5791 (ev2): deleteMedia(0) on the layer whose media 1 is built; slot 1 is null while media 0 is destroyed."""
    _ready(ed)
    p, d = _fresh(ed, 20)
    ed.jni(f'initNativeSegmenter(1,{CACHE})')
    for _ in range(3):
        ed.jni(_add(p, d, 1))                             # [X, A(built), F]
    ed.jni(f'startNativeRemoveBgBuild(1,1,{CACHE},1);sleep(2000)')
    for _ in range(14):
        # erase: slot[0]=move(slot[1]) releases slot 1, then runs X's (slow) teardown; index 1 stays valid after
        ed.jni(f'resumePlaying();sleep({r.randint(150, 400)});deleteMedia(0,1);pausePlaying();{_add(p, d, 1)};sleep(100)')
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp2_c(ed, r):
    """Crashlytics ge6a5791: layer move of [2][0] racing the dense appends of a mask-cache replay."""
    _ready(ed)
    lens = sorted([l for l in (ed.dev.video_lengths() or []) if l[1] >= 1], key=lambda l: l[1])
    p, d = (lens[0][0], lens[0][1]) if lens else _fresh(ed, 2)   # stable path: cache survives across runs
    ed.jni(f'initNativeSegmenter(1,{CACHE})')
    ed.jni(_add(p, d, 2)); ed.jni(_add(p, d, 2))
    n1 = _out(ed.jni('getMediaCounts(1)'))
    ed.jni(f'startNativeRemoveBgBuild(0,1,{CACHE},2)')
    time.sleep(min(22, d * 30 * 0.25 + 3))                # first walk writes the cache (instant on later runs)
    burst = f'startNativeRemoveBgBuild(0,1,{CACHE},2);' + ';'.join(
        [f'changeVisualMediaLayer(0,2,1);changeVisualMediaLayer({n1},1,2)'] * 8) + f';sleep({r.randint(5, 30)})'
    for _ in range(6):
        ed.jni(burst, repeat=8)
    ed.idle(5)


# 2026-11-03 20:45 attempt 3
CACHE = '/data/user/0/com.myzesty/cache'

def _n(lines):
    try:
        return int((lines or ['-> 0'])[-1].rsplit('->', 1)[-1].strip())
    except ValueError:
        return 0

def _setup(ed, want, shortest=False):
    # rp1/rp2 all died in Java 2-5 s after the runner's "open draft", before any engine call: use a slideshow engine
    ed.open_slideshow(1)
    for _ in range(15):
        if _n(ed.jni('getMediaCounts(0)')) > 0:
            break
        time.sleep(1)
    ed.idle(2)
    lens = [l for l in (ed.dev.video_lengths() or []) if l[1] >= 1]
    if shortest and lens:
        p, d = min(lens, key=lambda l: l[1])          # stable path: the mask cache survives between runs
    else:
        d = min(lens, key=lambda l: abs(l[1] - want))[1] if lens else want
        p = ed.dev.fresh_video(tag='rbg', duration_s=d)
    ed.jni(f'initNativeSegmenter(1,{CACHE})')
    return p, d

def _add(p, d, layer):
    return f'addVideo({p},{int(d * 30)}.0,{d * 1000:.1f},{layer})'

@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ge6a5791_rp3_a(ed, r):
    """Crashlytics ge6a5791 (ev1): async changeVisualMediaLayer of [2][0] while live inference appends to [2][0]."""
    p, d = _setup(ed, 17)
    a = _n(ed.jni(_add(p, d, 2))); ed.jni(_add(p, d, 2))     # [A, F]: index a stays valid after each move
    n1 = _n(ed.jni('getMediaCounts(1)'))
    ed.jni(f'startNativeRemoveBgBuild({a},1,{CACHE},2);sleep(2500)')
    for _ in range(6):                                       # Set() is async: the looper runs the moves back to back
        ed.jni(f'changeVisualMediaLayer({a},2,1);changeVisualMediaLayer({n1},1,2);sleep({r.randint(0, 3)})', repeat=150)
        time.sleep(2)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ge6a5791_rp3_b(ed, r):
    """Crashlytics ge6a5791: layer moves of [2][0] racing the dense appends of a mask-cache replay."""
    p, d = _setup(ed, 1, shortest=True)
    a = _n(ed.jni(_add(p, d, 2))); ed.jni(_add(p, d, 2))
    n1 = _n(ed.jni('getMediaCounts(1)'))
    ed.jni(f'startNativeRemoveBgBuild({a},1,{CACHE},2)')
    time.sleep(min(24, d * 30 * 0.3 + 3))                    # first full walk writes the cache (instant if cached)
    mv = ';'.join([f'changeVisualMediaLayer({a},2,1);changeVisualMediaLayer({n1},1,2)'] * 10)
    for _ in range(8):                                       # Get(start) cancels+joins, then replays every mask at PNG speed
        ed.jni(f'startNativeRemoveBgBuild({a},1,{CACHE},2);{mv};sleep({r.randint(2, 20)})', repeat=6)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ge6a5791_rp3_c(ed, r):
    """Crashlytics ge6a5791 (ev2): deleteMedia(0) on the build's layer; erase's slot0=move(slot1) tears X down while slot 1 is null."""
    p, d = _setup(ed, 20)
    for _ in range(4):
        ed.jni(_add(p, d, 1))                                # [X, B(built), F, G]
    ed.jni(f'startNativeRemoveBgBuild(1,1,{CACHE},1);sleep(2000)')
    for _ in range(14):                                      # play first so X's decoders/surface exist: slow teardown
        ed.jni(f'resumePlaying();sleep({r.randint(200, 450)});deleteMedia(0,1);sleep(30);pausePlaying();{_add(p, d, 1)};sleep(80)')
    ed.idle(5)
