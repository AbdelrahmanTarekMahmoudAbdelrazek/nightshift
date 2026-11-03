# Night Shift engine replays for 2fe03193209d272d69500de7526df59f (turbo)


# 2026-11-03 13:20 attempt 2
CACHE = '/data/user/0/com.myzesty/cache/'

def _nums(lines):
    out = []
    for ln in lines or []:
        for t in str(ln).replace('[', ' ').replace(']', ' ').replace(',', ' ').split():
            try: out.append(float(t))
            except ValueError: pass
    return out

def _make_video_only_mp4(ed, tag):
    """Write a video-only mp4 with the engine: export an image-only timeline."""
    png, mp4 = CACHE + 'ns_rp2_%s.png' % tag, CACHE + 'ns_rp2_%s.mp4' % tag
    ed.jni('exportImage(%s);addImage(%s;2.0;1080;0)'.replace(';', ',', 1).replace('(%s;', '(%s,') % (png, png)
           if False else 'exportImage(%s);sleep(300);addImage(%s,2.0,1080,0);sleep(300)' % (png, png), thread='bg')
    tok = int((_nums(ed.jni('detachMedia(0,0)', thread='bg')) or [0])[-1])
    assert tok > 0, 'detachMedia refused'
    ed.jni('exportVideo(%s,640,360,30,1,-1.0,true,%s)' % (mp4, png), thread='bg')
    for _ in range(60):
        time.sleep(0.5)
        if 'true' in ' '.join(map(str, ed.jni('isExportingFinished()', thread='bg'))).lower():
            break
    ed.jni('restoreMedia(%d,0);sleep(300);deleteMedia(1,0);sleep(300)' % tok, thread='bg')
    return mp4

def _clip_dur(ed):
    n = [x for x in _nums(ed.jni('getMediaDuration(0,0)', thread='bg')) if x > 0]
    return max(n) if n else None

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_a(ed, r):
    """Crashlytics [libmedia.so] AMediaCodec_configure: Reverse cached-branch order, then replace with a video-only mp4."""
    mp4 = _make_video_only_mp4(ed, 'a')
    d = _clip_dur(ed)
    for _ in range(4):  # 'active' is uninitialised: a 0 read throws cleanly, retry with a fresh decoder
        pre = 'setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);'
        if d: pre += 'trimVideo(0,0.0,%s,0);' % d
        ed.jni(pre + 'sleep(100);replaceMedia(0,%s,0)' % mp4, thread='bg')
        time.sleep(1.5)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_b(ed, r):
    """Crashlytics [libmedia.so] AMediaCodec_configure: bare replaceMedia (no speed/curve/trim prelude) with a video-only mp4."""
    mp4 = _make_video_only_mp4(ed, 'b')
    for _ in range(4):
        ed.jni('replaceMedia(0,%s,0)' % mp4, thread='bg')
        time.sleep(1.5)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_c(ed, r):
    """Crashlytics [libmedia.so] AMediaCodec_configure: audio decoder warmed by playback, drag shifts and seeks, then Reverse calls on main."""
    mp4 = _make_video_only_mp4(ed, 'c')
    ed.jni('seekTo(0.0);startPlaying();sleep(1500);pausePlaying()', thread='bg')
    for _ in range(4):
        sh = ';'.join('applyFreeShift(0,%.3f,%.3f,0);applyFreeRotate(0,0.0,0)' % (r.uniform(-.4, .4), r.uniform(-.1, .1))
                      for _ in range(6))
        ed.jni(sh + ';seekTo(%.1f);sleep(200)' % r.uniform(0, 3), thread='bg')
        ed.jni('setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);replaceMedia(0,%s,0)' % mp4, thread='main')
        time.sleep(1.5)
    ed.idle(5)


# 2026-11-03 13:28 attempt 3
CACHE = '/data/user/0/com.myzesty/cache/'

def _vo(ed, tag):
    """Plant a real video-only mp4 (audio stripped) under a unique cache name; never the clip's own name."""
    vids = [v for v in ed.dev.video_lengths() if v[1] >= 3] or ed.dev.video_lengths()
    src = min(vids, key=lambda v: v[1])[0]
    ed.dev.plant_app_file(src, 'cache/ns_rp3_%s.mp4' % tag, video_only=True)
    ed.log('    clip 0 has audio: %s' % ed.jni('isVideoHaveAudio(0,0)', thread='bg'))
    return CACHE + 'ns_rp3_%s.mp4' % tag

def _secs(ed):
    for ln in ed.jni('getMediaDuration(0,0)', thread='bg') or []:
        s = str(ln)
        if s.startswith('getMediaDuration') and '->' in s:
            n = [float(t) for t in s.split('->')[1].replace('[', ' ').replace(']', ' ').replace(',', ' ').split()
                 if t.replace('.', '', 1).isdigit()]
            if n:
                d = max(n)
                return d / 1e6 if d > 1e4 else d
    return None

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp3_a(ed, r):
    """Crashlytics [libmedia.so] reset_state: Reverse cached-branch order (speed 1, curve 0, trim) then replaceMedia(video-only) on bg."""
    vo, d = _vo(ed, 'a'), _secs(ed)
    pre = 'setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);' + ('trimVideo(0,0.0,%.3f,0);' % d if d else '')
    for _ in range(5):   # uninitialised 'active': a 0 read throws cleanly; the next fresh decoder gets new garbage
        ed.jni(pre + 'sleep(100);replaceMedia(0,%s,0)' % vo, thread='bg')
        time.sleep(1.2)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp3_b(ed, r):
    """Crashlytics [libmedia.so] reset_state: bare replaceMedia(video-only) on a clip with audio, heap churned by seeks between tries."""
    vo = _vo(ed, 'b')
    for _ in range(6):
        ed.jni(';'.join('seekTo(%.2f)' % r.uniform(0, 3) for _ in range(5)) + ';sleep(150)', thread='bg')
        ed.jni('replaceMedia(0,%s,0)' % vo, thread='bg')
        time.sleep(1.0)
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp3_c(ed, r):
    """Crashlytics [libmedia.so] reset_state: audio decoder warmed by playback plus field drags, then Reverse prelude + replace on main."""
    vo = _vo(ed, 'c')
    ed.jni('seekTo(0.0);startPlaying();sleep(1500);pausePlaying()', thread='bg')
    for _ in range(4):
        ed.jni(';'.join('applyFreeShift(0,%.3f,%.3f,0);applyFreeRotate(0,0.0,0)' % (r.uniform(-.4, .4), r.uniform(-.1, .1))
                        for _ in range(6)) + ';seekTo(%.1f);sleep(200)' % r.uniform(0, 3), thread='bg')
        ed.jni('setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);replaceMedia(0,%s,0)' % vo, thread='main')
        time.sleep(1.2)
    ed.idle(5)
