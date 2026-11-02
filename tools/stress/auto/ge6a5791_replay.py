# Night Shift engine replays for 2bc43cd6d24a25e5305f8167703618a8~e6a57918 (turbo)


# 2026-11-01 15:56 attempt 1
CACHE = '/data/user/0/com.myzesty/cache'
MODEL = '/data/user/0/com.myzesty/files/pp_humansegv2_mobile_256x256.tflite'
SEG = 'setSegmentationModelPath(%s);initNativeSegmenter(1,%s);' % (MODEL, CACHE)


@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_a(ed, r):
    """Crashlytics ge6a5791: SIGSEGV append_remove_bg_track_mask - layer move 2->1->2 of the overlay being built."""
    # layer0=[main], layer1=[A], layer2=[B]; build streams on (layer 2, index 0)
    ed.jni(SEG + 'duplicateMedia(0,0);duplicateMedia(0,0);'
           'changeVisualMediaLayer(1,0,1);changeVisualMediaLayer(1,0,2)', thread='bg')
    end = time.time() + 40
    while time.time() < end:
        ed.jni('startNativeRemoveBgBuild(0,1,%s,2);sleep(1200)' % CACHE, thread='bg')
        for _ in range(15):  # move-out at VisualTimeLine.cpp:245 nulls slot (2,0) while masks land
            ed.jni('changeVisualMediaLayer(0,2,1);changeVisualMediaLayer(1,1,2);sleep(%d)' % r.randint(20, 90), thread='bg')
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_b(ed, r):
    """Crashlytics ge6a5791: SIGSEGV append_remove_bg_track_mask - delete on the build's own layer shifts index 1->0 (event 2)."""
    # layer1=[A, B]; build on (layer 1, index 1); deleteMedia(0,1) erase moves B into slot 0 and nulls slot 1 while A is torn down
    ed.jni(SEG + 'duplicateMedia(0,0);duplicateMedia(0,0);'
           'changeVisualMediaLayer(1,0,1);changeVisualMediaLayer(1,0,1)', thread='bg')
    end = time.time() + 40
    while time.time() < end:
        ed.jni('startNativeRemoveBgBuild(1,1,%s,1);sleep(%d);deleteMedia(0,1)' % (CACHE, r.randint(900, 1800)), thread='bg')
        ed.jni('sleep(300);duplicateMedia(0,1)', thread='bg')  # restore layer1=[B, B']
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_ge6a5791_rp1_c(ed, r):
    """Crashlytics ge6a5791: SIGSEGV append_remove_bg_track_mask - field event 1 order: delete layer-1 overlay, then move built overlay 2->1."""
    # layer1=[A], layer2=[B]; build on (layer 2, index 0); delete A, then move B 2->1 while masks stream
    ed.jni(SEG + 'duplicateMedia(0,0);duplicateMedia(0,0);'
           'changeVisualMediaLayer(1,0,1);changeVisualMediaLayer(1,0,2)', thread='bg')
    end = time.time() + 40
    while time.time() < end:
        ed.jni('startNativeRemoveBgBuild(0,1,%s,2);sleep(1200);deleteMedia(0,1);sleep(%d);changeVisualMediaLayer(0,2,1)'
               % (CACHE, r.randint(40, 400)), thread='bg')
        # restore layer2=[B], layer1=[B']
        ed.jni('sleep(200);changeVisualMediaLayer(0,1,2);duplicateMedia(0,2);changeVisualMediaLayer(1,2,1)', thread='bg')
    ed.idle(5)
