# Night Shift auto repros for f7a4eff327f9009210c5164e8a1148d0


# 2026-10-26 04:16 level 2 attempt 1
_F7A4_START = r'Start proc \d+:com\.myzesty|am_proc_start.*com\.myzesty'


def _f7a4eff3_crash_loop(ed, r, n=3):
    """Field crash loop: cold launcher start, wait past onCreate, relaunch 4-6 s later with the stored state unchanged."""
    for k in range(n):
        ed.step(f'cold launch #{k + 1} (field relaunch loop)')
        ed.mon.allow_death = True
        ed.dev.force_stop()                          # a true cold start (am kill lets Android restore the old task)
        time.sleep(r.uniform(4, 6) if k else 1)
        ed.mon.allow_death = False
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(_F7A4_START, 10, since=mark, why='checkpoint 3: new process for the shipped launch Activity')
        ed.idle(6)                                   # the field NPE comes <1 s into onCreate; a crash raises here


@scenario('nightshift', 'auto')
def ns_f7a4eff3_l2_1_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5), path A: Realm filled online by stickers, then cold relaunch loop."""
    ed.dev.restore_env()                             # online: DownloadAssetsWorker + sticker picker write asset tables
    ed.idle(r.uniform(8, 15))
    ed.add_sticker()                                 # raises 'sticker list empty (offline?)' if nothing reached Realm
    ed.idle(3)
    ed.leave_editor()
    ed.idle(r.uniform(3, 6))
    _f7a4eff3_crash_loop(ed, r, n=3)


@scenario('nightshift', 'auto')
def ns_f7a4eff3_l2_1_b(ed, r):
    """All 20 instances, path B: app reclaimed in the background from the sticker screen, then relaunch restores saved state."""
    ed.dev.restore_env()
    ed.idle(5)
    ed.main_nav()
    ed.menu_tap('sticker')                           # leave the Realm-backed sticker screen open in the saved state
    ed.idle(r.uniform(4, 8))
    ed.kill_bg()                                     # the system reclaims the process; Bundle/extras stay with the task
    time.sleep(r.uniform(5, 15))
    for k in range(3):
        ed.step(f'relaunch #{k + 1} after process death (restore path)')
        ed.mon.allow_death = False
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(_F7A4_START, 10, since=mark, why='checkpoint 3: new process on relaunch')
        ed.idle(6)
        ed.kill_bg()
        time.sleep(r.uniform(4, 6))
    _f7a4eff3_crash_loop(ed, r, n=2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_c(ed, r):
    """All 20 instances, path C: cold launch from a push notification tap (extras without a resource table), then relaunches."""
    ed.dev.restore_env()
    ed.dev.launch()
    ed.idle(8)                                       # one normal session: prefs/Realm written by this build
    ed.kill_bg()
    time.sleep(3)
    ed.dev.fcm_push('New stickers', 'Check out the new pack', data={'type': 'sticker', 'screen': 'stickers'})
    time.sleep(3)
    ed.dev.swipe(540, 5, 540, 1400, 300)             # open the notification shade like a user
    time.sleep(1.5)
    ed.mon.allow_death = False
    mark = ed.log_mark()
    if not ed.ui.tap('textc:New stickers', timeout=5):
        ed.dev.key('KEYCODE_BACK')
        ed.dev.launch()                              # no notification shown: plain launcher cold start
    ed.require_log(_F7A4_START, 10, since=mark, why='checkpoint 3: cold start from the notification/launcher')
    ed.idle(6)
    _f7a4eff3_crash_loop(ed, r, n=2)


# 2026-10-26 04:24 level 2 attempt 2
_F7A4_START = r'Start proc \d+:com\.myzesty/'
_F7A4_PAIRIP = r'LicenseActivity|Process com\.myzesty \(pid \d+\) has died'


def _f7a4eff3_require_shipped(ed):
    """Checkpoint 1: Android 11 + Play-installed 1.25.2 (800054890); a sideloaded PairIP copy dies before any app code."""
    rel = ed.dev.getprop('ro.build.version.release').strip()
    pkg = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode=|installerPackageName="')
    ed.log(f'    android={rel} {" ".join(pkg.split())[:160]}')
    if rel != '11' or 'versionCode=800054890' not in pkg or 'installerPackageName=com.android.vending' not in pkg:
        raise UIError('checkpoint 1 missed: need Android 11 + Play install of 800054890 (no adb install, no pm clear)')


def _f7a4eff3_cold_launch(ed, r, gap):
    """Checkpoint 3/4: new process for the launcher Activity; the field NPE comes <1 s into onCreate (raises in idle)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()                              # true cold start; app data stays (never cleared)
    time.sleep(gap)
    ed.mon.allow_death = False
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(_F7A4_START, 10, since=mark, why='checkpoint 3: new process for the shipped launch Activity')
    if ed.wait_log(_F7A4_PAIRIP, 3, since=mark) and 'LicenseActivity' in ed.wait_log('LicenseActivity', 1, since=mark):
        raise UIError('PairIP LicenseActivity on launch: not a Play-licensed install, launch path never runs')
    ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5): online session keeps its data, then launcher cold-start loop 4-6 s apart."""
    _f7a4eff3_require_shipped(ed)
    ed.dev.restore_env()
    _f7a4eff3_cold_launch(ed, r, 1)                  # session 1: prefs + Realm (assets via DownloadAssetsWorker) written
    ed.idle(r.uniform(15, 25))
    for k in range(3):                               # field pairs 08:08:12/08:08:16, 07:17:33/07:17:37
        ed.step(f'cold relaunch #{k + 1} with stored state unchanged')
        _f7a4eff3_cold_launch(ed, r, r.uniform(4, 6))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_b(ed, r):
    """All 20 instances, restore path: the system reclaims the app in the background, the relaunch recreates the task (saved Bundle)."""
    _f7a4eff3_require_shipped(ed)
    ed.dev.restore_env()
    _f7a4eff3_cold_launch(ed, r, 1)
    ed.idle(r.uniform(10, 20))
    for k in range(3):
        ed.step(f'reclaimed in background, relaunch #{k + 1}')
        ed.kill_bg()                                 # no force-stop: Android keeps the task and its saved state
        time.sleep(r.uniform(4, 6))
        ed.mon.allow_death = False
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(_F7A4_START, 10, since=mark, why='checkpoint 3: new process on relaunch (performLaunchActivity)')
        if 'LicenseActivity' in ed.wait_log('LicenseActivity', 3, since=mark):
            raise UIError('PairIP LicenseActivity on launch: not a Play-licensed install')
        ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_c(ed, r):
    """All 20 instances, offline path: stored state from an online session, then cold launches with no network (asset tables unfetched)."""
    _f7a4eff3_require_shipped(ed)
    ed.dev.restore_env()
    _f7a4eff3_cold_launch(ed, r, 1)
    ed.idle(r.uniform(10, 15))
    ed.dev.network(False)
    try:
        for k in range(3):
            ed.step(f'offline cold relaunch #{k + 1}')
            _f7a4eff3_cold_launch(ed, r, r.uniform(4, 6))
    finally:
        ed.dev.network(True)
