# Night Shift engine replays for 2bc43cd6d24a25e5305f8167703618a8~e6a57918 (turbo)


# 2026-11-02 21:48 attempt 1
SEG = 'setSegmentationModelPath(/data/user/0/com.myzesty/files/pp_humansegv2_mobile_256x256.tflite);initNativeSegmenter(1,/data/user/0/com.myzesty/code_cache)'
MASKS = '/sdcard/Android/data/com.myzesty/files'

def _rb_clip(ed):
    """Fresh-named clip (no cached mask track) ~20 s long: (path, frames, seconds)."""
    dur = min(ed.dev.video_lengths(), key=lambda c: abs(c[1] - 20))[1]
    return ed.dev.fresh_video(tag='rb', duration_s=dur), int(dur * 30), round(dur, 2)

def _rb_count(ed, layer):
    out = ed.jni(f'getMediaCounts({layer})') or ['-> 0']
    return int(out[-1].rsplit('->', 1)[1].strip())

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_a(ed, r):
    """Crashlytics ge6a5791: changeVisualMediaLayer nulls [2][i] (:245..:260) while the build sink writes it (event 1)."""
    p, f, d = _rb_clip(ed)
    i = _rb_count(ed, 2)                       # built slot; a filler at i+1 keeps slot i valid after each erase
    ed.jni(f'addVideo({p},{f},{d},2);addVideo({p},{f},{d},2);{SEG}')
    ed.jni(f'startNativeRemoveBgBuild({i},1,{MASKS},2);sleep(1500);nativeRemoveBgBuildProgress()')
    j = _rb_count(ed, 1)
    hop = f'changeVisualMediaLayer({i},2,1);changeVisualMediaLayer({j},1,2);'   # [2][i] out (null window), back to the tail
    ed.jni(hop * 30 + 'sleep(40)', thread='bg', repeat=12, timeout=50)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_b(ed, r):
    """Crashlytics ge6a5791: delete_media erase on the build's layer nulls the built slot while the victim is destroyed (event 2)."""
    p, f, d = _rb_clip(ed)
    v = _rb_count(ed, 1)                       # v = victim, v+1 = built, v+2 = filler
    ed.jni(f'addVideo({p},{f},{d},1);addVideo({p},{f},{d},1);addVideo({p},{f},{d},1);{SEG}')
    ed.jni(f'startNativeRemoveBgBuild({v + 1},1,{MASKS},1);sleep(1500);nativeRemoveBgBuildProgress()')
    # erase: slot[v] = move(slot[v+1]) releases slot[v+1] BEFORE the old victim's decoders are torn down
    cycle = f'deleteMedia({v},1);sleep({r.randint(60, 140)});addVideo({p},{f},{d},1);sleep(250);'
    ed.jni(cycle * 8 + 'nativeRemoveBgBuildProgress()', thread='bg', repeat=4, timeout=55)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_c(ed, r):
    """Crashlytics ge6a5791: event 1 order - delete layer-1 overlay, then move the built (2,i) into layer 1 while playing."""
    p, f, d = _rb_clip(ed)
    i = _rb_count(ed, 2)
    ed.jni(f'addVideo({p},{f},{d},2);{SEG}')
    for _ in range(6):                         # each round: new build, then the field's delete -> move, then move back
        j = _rb_count(ed, 1)
        ed.jni(f'addVideo({p},{f},{d},1);startNativeRemoveBgBuild({i},1,{MASKS},2);sleep({r.randint(1200, 2500)});'
               f'startPlaying();sleep(300);deleteMedia({j},1);sleep({r.randint(100, 900)});'
               f'changeVisualMediaLayer({i},2,1);sleep(200);pausePlaying();'
               f'changeVisualMediaLayer({j},1,2)', thread='bg', timeout=20)
    ed.idle(5)
