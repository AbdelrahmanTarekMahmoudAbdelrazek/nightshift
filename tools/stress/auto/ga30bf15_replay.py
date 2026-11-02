# Night Shift engine replays for 2bc43cd6d24a25e5305f8167703618a8~a30bf155 (turbo)


# 2026-11-01 01:39 attempt 1
@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ga30bf15_rp1_a(ed, r):
    """Crashlytics [libMYJNILIB26.so] getAudioOverlayId: failed layer-1 overlay add, then overlay volume 1/0 (field order)."""
    ed.open_slideshow(2)
    time.sleep(3)
    ed.jni("addVideo(/storage/emulated/0/VidMate/download/ns_missing_overlay_360p.mp4;30.0;14977000.0;1);"
           "updateOverlayVideoVolume(100;1;0)", thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_ga30bf15_rp1_b(ed, r):
    """Crashlytics [libMYJNILIB26.so] getAudioOverlayId: draft open, failed add on never-used layer 9, then overlay volume 9/0."""
    time.sleep(3)
    ed.jni("addVideo(/storage/emulated/0/VidMate/download/ns_missing_overlay_360p.mp4;30.0;14977000.0;9);"
           "sleep(20);updateOverlayVideoVolume(100;9;0)", thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ga30bf15_rp1_c(ed, r):
    """Crashlytics [libMYJNILIB26.so] getAudioOverlayId: overlay volume on a pre-sized empty layer with no add at all."""
    ed.open_slideshow(2)
    time.sleep(3)
    ed.jni("updateOverlayVideoVolume(100;1;0)", thread="main")
    ed.idle(5)


# 2026-11-01 01:44 attempt 2
@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ga30bf15_rp2_a(ed, r):
    """Crashlytics [libMYJNILIB26.so] getAudioOverlayId: failed layer-1 overlay add, then overlay volume 1/0 (field restore order)."""
    ed.open_slideshow(2)
    time.sleep(3)
    ed.jni("addVideo(/storage/emulated/0/VidMate/download/ns_missing_overlay_360p.mp4,449.0,14977000.0,1);"
           "updateOverlayVideoVolume(100,1,0)", thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ga30bf15_rp2_b(ed, r):
    """Crashlytics [libMYJNILIB26.so] getAudioOverlayId: overlay volume 1/0 on the pre-sized empty layer 1, no add at all."""
    ed.open_slideshow(2)
    time.sleep(3)
    ed.jni("updateOverlayVideoVolume(100,1,0)", thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_ga30bf15_rp2_c(ed, r):
    """Crashlytics [libMYJNILIB26.so] getAudioOverlayId: failed add on layer 2, 20 ms gap, volume 2/0 sent from the UI thread."""
    ed.open_slideshow(2)
    time.sleep(3)
    ed.jni("addVideo(/storage/emulated/0/VidMate/download/ns_missing_overlay_360p.mp4,449.0,14977000.0,2);"
           "sleep(20);updateOverlayVideoVolume(100,2,0)", thread="main")
    ed.idle(5)
