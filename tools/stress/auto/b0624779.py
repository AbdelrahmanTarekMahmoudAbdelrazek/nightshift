# Night Shift auto repros for b0624779923c1f52e97b73f75b8c5950


# 2026-10-14 19:11 level 3 attempt 1
def _b0624779_dka(ed, on):
    """'Don't keep activities' through the Settings app (the only switch that takes effect on the realme), settings put as fallback."""
    ok = ed._dka_ui(on)
    if not ok:
        ed.dont_keep_activities(on)
    return ok


def _b0624779_open_cover(ed):
    """Editor (recreated under DKA) -> pause at 0 -> Cover thumbnail -> CoverActivity filmstrip (id:timeline)."""
    ed.dev.launch()                                  # PlayerActivity comes back recreated after the Settings trip
    ed.idle(5)
    ed.set_playing(False)
    ed.seek_start()                                  # cover_thumbnail sits left of clip 0, only reachable near 0
    ed.idle(1)
    mark = ed.log_mark()
    ed.step('open Cover (PlayerActivity is destroyed behind it under DKA)')
    if not ed.ui.tap('id:cover_thumbnail', timeout=10):
        raise UIError('cover_thumbnail not on the editor track')
    s = ed.ui.wait('id:timeline', timeout=10)
    if s is None:
        raise UIError('CoverActivity filmstrip (id:timeline) did not open')
    return s.find('id:timeline').b, mark


def _b0624779_scrub(ed, r, box, secs):
    """Keep dragging the Cover seek box: every move -> seekPreview -> Player.seekTo -> JNI_seekTo."""
    x1, y1, x2, y2 = box
    y, end, fwd = (y1 + y2) // 2, time.time() + secs, True
    while time.time() < end:
        a, b = x1 + int((x2 - x1) * r.uniform(0.1, 0.4)), x1 + int((x2 - x1) * r.uniform(0.6, 0.9))
        ed.dev.swipe(a if fwd else b, y, b if fwd else a, y, r.randint(250, 450))
        fwd = not fwd
        ed.check()


@scenario('nightshift', 'auto')
def ns_b0624779_l3_1_a(ed, r):
    """Pixel 6a x4, vivo V2149 x2, M2101K7AI (JNI_seekTo): critical memory pressure + DKA destroy the editor while Cover's filmstrip is scrubbed."""
    try:
        _b0624779_dka(ed, True)
        box, _ = _b0624779_open_cover(ed)
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_CRITICAL')
        _b0624779_scrub(ed, r, box, r.uniform(12, 16))  # teardown lands ~8 s after Cover opens; keep seeks flowing past it
        ed.settle(3)
    finally:
        _b0624779_dka(ed, False)


@scenario('nightshift', 'auto')
def ns_b0624779_l3_1_b(ed, r):
    """Play Pixel 6a stack (CoverActivity surfaceDestroyed <- performStop): Home from Cover right after '~MsgLooper ended'."""
    try:
        _b0624779_dka(ed, True)
        box, mark = _b0624779_open_cover(ed)
        _b0624779_scrub(ed, r, box, 1.5)             # checkpoint 1: live seeks on Cover
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_CRITICAL')
        hit = ed.wait_log(r'~MsgLooper ended', 15, since=mark)
        ed.log(f'    teardown under Cover: {bool(hit)}')
        ed.mon.allow_death = False
        ed.dev.key('KEYCODE_HOME')                   # Cover stops -> surfaceDestroyed -> Player.onSurfaceDestroyed
        ed.settle(3)
        ed.dev.launch()                              # back to Cover: surfaceChanged -> seekPreview on the dead looper
        ed.idle(2)
        ed.ui.tap('id:tab_gallery', timeout=5)       # hides the surface -> onSurfaceDestroyed again
        ed.settle(3)
    finally:
        _b0624779_dka(ed, False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_b0624779_l3_1_c(ed, r):
    """Redmi Note 7/7S, Tecno LD7j (ss_export_start -> QuickCutActivity ss_on_resume, no engine): slideshow export, process reclaimed, return -> ExportDialog.onResume -> JNI_isInBackgroundState."""
    ed.open_slideshow(2)
    ed.idle(3)
    ed.export_start()                                # ss_export_start, ExportDialog on top of QuickCutActivity
    ed.idle(r.uniform(0.5, 1.5))
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_CRITICAL')
    ed.kill_bg()                                     # Home + the system reclaims the process (low-RAM field phones)
    ed.idle(r.uniform(2, 5))
    if ed.dev.pid():
        ed.dev.sh(f'am kill {PKG}')
        ed.idle(1)
    ed.log(f'    process reclaimed: {ed.dev.pid() == ""}')
    ed.mon.allow_death = False                       # from here a death is the field crash
    ed.dev.launch()                                  # task restore: QuickCutActivity + ExportDialog, no createPlayer yet
    ed.settle(6)
