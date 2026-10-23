# Night Shift engine replays for 2bc43cd6d24a25e5305f8167703618a8~e7a32fec (turbo)


# 2026-10-20 22:47 attempt 1
@scenario('nightshift', 'auto', 'replay')
def ns_ge7a32fe_rp1_a(ed, r):
    """Crashlytics [libMYJNILIB26.so] Sticker::add_triggered_keyframe: H1 keyframe on a sticker id that never existed."""
    ed.jni("pausePlaying();setPreviewState(false);sleep(100);"
           "addTriggeredKeyFrame(999;1.0;2;xshift=100|yshift=200|xscale=150|yscale=150|angel=0;0)".replace(";1.0;2;", ",1.0,2,").replace("(999;", "(999,").replace("angel=0;0)", "angel=0,0)"),
           thread="bg")
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge7a32fe_rp1_b(ed, r):
    """Crashlytics [libMYJNILIB26.so] Sticker::add_triggered_keyframe: H1 field order (drag, delete, save, then keyframe on the deleted id)."""
    kf = "xshift=166|yshift=591|xscale=206|yscale=206|angel=0"
    ed.jni("createWebpSticker(/sdcard/Download/lab_sticker.webp,0);sleep(300)", thread="bg")
    drags = ";".join(f"setStickerCoordinates({i},209.0,{590 + j}.0,206.0,206.0,0.0,62.0,443.0)"
                     for i in range(3) for j in range(5))
    ed.jni(drags, thread="bg")
    ed.jni("setPreviewState(false);" + ";".join(f"deleteSticker({i})" for i in range(3))
           + ";saveDraft();sleep(2500);"
           + ";".join(f"addTriggeredKeyFrame({i},3.0,2,{kf},0)" for i in range(3)), thread="bg")
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge7a32fe_rp1_c(ed, r):
    """Crashlytics [libMYJNILIB26.so] Sticker::add_triggered_keyframe: H2 keyframe on a live sticker whose image failed to load."""
    kf = "xshift=100|yshift=200|xscale=150|yscale=150|angel=30"
    ed.jni("createWebpSticker(/nonexistent/missing.webp,0);sleep(300);"
           + ";".join(f"setStickerTime({i},0.0,5.0)" for i in range(3)) + ";"
           + ";".join(f"addTriggeredKeyFrame({i},1.0,2,{kf},0)" for i in range(3)), thread="bg")
    ed.idle(5)


# 2026-10-20 22:48 attempt 2
KF = "xshift=166|yshift=591|xscale=206|yscale=206|angel=0"

@scenario('nightshift', 'auto', 'replay')
def ns_ge7a32fe_rp2_a(ed, r):
    """Crashlytics [libMYJNILIB26.so] Sticker::add_triggered_keyframe: H1 keyframe on a sticker id that never existed (null from get_sticker)."""
    ed.jni(f"pausePlaying();setPreviewState(false);sleep(100);addTriggeredKeyFrame(7,1.0,2,{KF},0)", thread="bg")
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge7a32fe_rp2_b(ed, r):
    """Crashlytics [libMYJNILIB26.so] Sticker::add_triggered_keyframe: H1 field order: create, drag, delete, save, then keyframe on the deleted id."""
    out = ed.jni("createWebpSticker(/sdcard/Download/lab_sticker.webp,0);sleep(300)", thread="bg")
    sid = int(str(out[-1]).split("->")[-1].strip()) if out else 0
    ed.jni(f"setStickerTime({sid},3.0,6.0);" + ";".join(
        f"setStickerCoordinates({sid},209.0,{590 + j}.0,206.0,206.0,0.0,62.0,443.0)" for j in range(30)), thread="bg")
    ed.jni(f"setPreviewState(false);deleteSticker({sid});saveDraft();sleep(2500);"
           f"addTriggeredKeyFrame({sid},3.0,2,{KF},0)", thread="bg")
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_ge7a32fe_rp2_c(ed, r):
    """Crashlytics [libMYJNILIB26.so] Sticker::add_triggered_keyframe: H2 control, keyframe on a live sticker (expected no crash)."""
    out = ed.jni("createWebpSticker(/sdcard/Download/lab_sticker.webp,0);sleep(300)", thread="bg")
    sid = int(str(out[-1]).split("->")[-1].strip()) if out else 0
    ed.jni(f"setStickerTime({sid},0.0,5.0);pausePlaying();addTriggeredKeyFrame({sid},1.0,2,{KF},0);"
           f"addTriggeredKeyFrame({sid},2.0,2,{KF},0)", thread="bg")
    ed.idle(5)
