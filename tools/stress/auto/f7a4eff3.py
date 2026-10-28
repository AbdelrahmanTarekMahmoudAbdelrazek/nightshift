# Night Shift auto repros for f7a4eff327f9009210c5164e8a1148d0


# 2026-10-26 13:08 level 2 attempt 1
_F7_DIED = r'(Killing \d+:com\.myzesty|am_proc_died.*com\.myzesty|Process com\.myzesty .*has died)'


def _f7a4eff3_gate_build(ed):
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName|firstInstallTime|lastUpdateTime"')
    ed.log('    install: ' + ' | '.join(l.strip() for l in out.splitlines()[:6]))
    if '800054890' not in out or 'com.android.vending' not in out:
        raise UIError('not the Play-installed 1.25.2 (800054890) the field crashed on')


def _f7a4eff3_top_not_main(ed, why):
    top = ed.dev.sh('dumpsys activity activities | grep -m1 mResumedActivity')
    ed.log(f'    top before kill: {top.strip()[:160]}')
    if 'com.myzesty' not in top or '.MainActivity' in top:
        raise UIError(f'app not left on a screen past MainActivity ({why})')


def _f7a4eff3_reclaim_relaunch(ed, r, cycles=3):
    """Field checkpoints 2-5: process reclaimed while the task stays in recents, then cold relaunch (task restore), repeated."""
    for i in range(cycles):
        mark = ed.log_mark()
        ed.kill_bg()
        ed.require_log(_F7_DIED, 10, since=mark, why='process must die with the task kept in recents')
        ed.idle(r.uniform(3, 6))                     # field relaunch gap 4-6 s
        mark = ed.log_mark()
        ed.step(f'cold relaunch {i + 1}/{cycles} into the restored task')
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='cold launch -> performLaunchActivity')
        ed.mon.allow_death = False
        ed.log('    ' + ed.wait_log(r'START u0 .*cmp=com\.myzesty/', 5, since=mark)[:200])
        ed.settle(8)                                 # the field NPE lands <1 s after process start


def _f7a4eff3_home(ed):
    ed.dev.launch()
    ed.ui.wait('id:home_cta_row', timeout=30)


@scenario('nightshift', 'auto')
def ns_f7a4eff3_l2_1_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5): video editor Stickers panel open, process reclaimed, relaunch restores PlayerActivity."""
    _f7a4eff3_gate_build(ed)
    ed.set_playing(False)
    ed.step('open Stickers (StickersPresenter -> getAllImageEditorResources(table, ...))')
    ed.ui.tap(T.STICKER, timeout=10)
    ed.idle(r.uniform(3, 5))                         # let the sticker categories load from Realm
    _f7a4eff3_top_not_main(ed, 'editor with Stickers panel')
    _f7a4eff3_reclaim_relaunch(ed, r)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_b(ed, r):
    """All 20 instances: Image Editor (photo resources from Realm) left open, process reclaimed, relaunch restores the photo activity."""
    _f7a4eff3_gate_build(ed)
    _f7a4eff3_home(ed)
    ed.step('Home -> Image Editor -> first image')
    ed.ui.tap('id:home_cta_image', timeout=15)
    ed.ui.tap('id:image_tab', timeout=5)
    ed.ui.tap('id:gridrl', timeout=15)
    for sel in ('id:done', 'id:btn_continue', 'textc:next'):
        try:
            ed.ui.tap(sel, timeout=3)
        except UIError:
            pass
    ed.idle(4)
    try:
        ed.tap_tool('sticker')                       # a Realm-backed resource tool (stickers/frames) like the field user
    except UIError:
        ed.log('    no sticker tool in the image editor bar; leaving the editor as is')
    ed.idle(3)
    _f7a4eff3_top_not_main(ed, 'image editor')
    _f7a4eff3_reclaim_relaunch(ed, r)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_c(ed, r):
    """All 20 instances: a home template opened (template preview past MainActivity), process reclaimed, relaunch restores it."""
    _f7a4eff3_gate_build(ed)
    _f7a4eff3_home(ed)
    ed.step('Home -> first Trending template card')
    ed.ui.tap('id:thumbnailCard', timeout=15)
    ed.idle(r.uniform(4, 7))                         # template preview loads (progressTitle "Loading Template..")
    _f7a4eff3_top_not_main(ed, 'template preview')
    _f7a4eff3_reclaim_relaunch(ed, r)


# 2026-10-26 13:15 level 2 attempt 2
_F7_DIED = r'(Killing \d+:com\.myzesty|am_proc_died.*com\.myzesty|Process com\.myzesty .*has died)'


def _f7a4eff3_gate_build(ed):
    """Checkpoint 1: Play 1.25.2 on Android 11, updated IN PLACE over an older used build (not a fresh install)."""
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName|firstInstallTime|lastUpdateTime"')
    ed.log('    install: ' + ' | '.join(l.strip() for l in out.splitlines()[:6]))
    if '800054890' not in out or 'com.android.vending' not in out:
        raise UIError('not the Play-installed 1.25.2 (800054890) the field crashed on')
    first = [l.split('=', 1)[1].strip() for l in out.splitlines() if 'firstInstallTime' in l]
    last = [l.split('=', 1)[1].strip() for l in out.splitlines() if 'lastUpdateTime' in l]
    if not first or not last or first[0] >= last[0]:
        raise UIError('fresh install of 1.25.2 (firstInstallTime == lastUpdateTime): the field phones were updated in '
                      'place over an older Play build; install + use an older build, then update via the internal-test track')


def _f7a4eff3_home(ed):
    ed.grant_permissions()
    ed.dev.launch()
    ed.ui.wait('id:home_cta_row', timeout=30)


def _f7a4eff3_reclaim_relaunch(ed, r, activity, cycles=3):
    """Checkpoints 2-5: process reclaimed with `activity` on top of the task, cold relaunch 4-6 s later restores it."""
    top = ed.dev.sh('dumpsys activity activities | grep -m1 mResumedActivity')
    ed.log(f'    top before kill: {top.strip()[:160]}')
    if activity not in top:
        raise UIError(f'{activity} is not on top before the kill')
    for i in range(cycles):
        mark = ed.log_mark()
        ed.kill_bg()
        ed.require_log(_F7_DIED, 10, since=mark, why='process must die with the task kept in recents')
        ed.idle(r.uniform(4, 6))                     # field relaunch gap 4-6 s
        mark = ed.log_mark()
        ed.step(f'cold relaunch {i + 1}/{cycles}: task restore of {activity}')
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/\S+ for pre-top-activity \{com\.myzesty/\S*' + activity, 15,
                       since=mark, why=f'cold launch must restore {activity} (performLaunchActivity)')
        ed.mon.allow_death = False
        ed.settle(8)                                 # the field NPE lands <1 s after process start


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5): SlideShow (QuickCutActivity) left open after an in-place update, process reclaimed, relaunch loop."""
    _f7a4eff3_gate_build(ed)
    ed.open_slideshow(3)
    ed.require_log(r'Displayed com\.myzesty/\S*QuickCutActivity', 30, why='slideshow screen past MainActivity')
    ed.idle(r.uniform(3, 5))
    _f7a4eff3_reclaim_relaunch(ed, r, 'QuickCutActivity')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_b(ed, r):
    """All 20 instances: Full Video Editor (PlayerActivity, Stickers from Realm) left open after an in-place update, process reclaimed, relaunch loop."""
    _f7a4eff3_gate_build(ed)
    _f7a4eff3_home(ed)
    ed.step('Home -> Full Video Editor -> first video')
    mark = ed.log_mark()
    ed.ui.tap('id:home_cta_video', timeout=15)
    ed.ui.tap('id:video_tab', timeout=5)
    s = ed.ui.wait('id:gridrl', timeout=20)
    if s is None or not s.find_all('id:gridrl'):
        raise UIError('Full Video Editor did not open the gallery picker')
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed.idle(1)
    ed._picker_confirm()
    ed.require_log(r'Displayed com\.myzesty/\S*PlayerActivity', 150, since=mark, why='video editor past MainActivity')
    ed.idle(3)
    ed.ui.tap(T.STICKER, timeout=5)                  # sticker categories read through RealmWrapper
    ed.idle(r.uniform(3, 5))
    _f7a4eff3_reclaim_relaunch(ed, r, 'PlayerActivity')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_c(ed, r):
    """All 20 instances: Image Editor (PhotoActivity, photo resources from Realm) left open after an in-place update, process reclaimed, relaunch loop."""
    _f7a4eff3_gate_build(ed)
    _f7a4eff3_home(ed)
    ed.step('Home -> Image Editor (PhotoActivity) -> first image')
    mark = ed.log_mark()
    ed.ui.tap('id:home_cta_image', timeout=15)
    ed.require_log(r'Displayed com\.myzesty/\S*PhotoActivity', 30, since=mark, why='photo editor past MainActivity')
    s = ed.ui.wait(('id:gridrl', 'id:select_cover'), timeout=15)
    tiles = (s.find_all('id:gridrl') or s.find_all('id:select_cover')) if s is not None else []
    if tiles:
        ed.dev.tap(*tiles[0].center)
        ed.idle(1)
        for sel in ('id:done', 'id:btn_continue', 'id:next_button'):
            ed.ui.tap(sel, timeout=3)
    ed.idle(4)
    try:
        ed.tap_tool('sticker')                       # Realm-backed resource panel, like the field user
    except UIError:
        ed.log('    no sticker tool in the image editor bar; leaving the editor as is')
    ed.idle(3)
    _f7a4eff3_reclaim_relaunch(ed, r, 'PhotoActivity')


# 2026-10-26 13:19 level 2 attempt 3
_F7_DIED = r'(Killing \d+:com\.myzesty|am_proc_died.*com\.myzesty|Process com\.myzesty .*has died)'


def _f7a4eff3_home(ed):
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName|firstInstallTime|lastUpdateTime"')
    ed.log('    install: ' + ' | '.join(l.strip() for l in out.splitlines()[:6]))
    if '800054890' not in out or 'com.android.vending' not in out:
        raise UIError('not the Play-installed 1.25.2 (800054890) the field crashed on')
    ed.grant_permissions()
    ed.dev.launch()
    ed.ui.wait('id:home_cta_row', timeout=30)


def _f7a4eff3_open(ed, sels, act_re, why):
    """Tap the first selector that exists (home may need All Tools first) and require the resource screen."""
    mark = ed.log_mark()
    for sel in sels:
        s = ed.screen()
        if s is not None and s.has((sel,)):
            ed.dev.tap(*s.find((sel,)).center)
            break
    ed.require_log(r'Displayed com\.myzesty/\S*' + act_re, 30, since=mark, why=why)


def _f7a4eff3_restore_loop(ed, r, act_re, cycles=2):
    """Checkpoints 2-5: HOME (state saved) -> process reclaimed, task kept -> relaunch 4-6 s later restores act_re."""
    top = ed.dev.sh('dumpsys activity activities | grep -m1 mResumedActivity')
    ed.log(f'    top before kill: {top.strip()[:160]}')
    for i in range(cycles):
        mark = ed.log_mark()
        ed.kill_bg()
        ed.require_log(_F7_DIED, 10, since=mark, why='process must die with the task kept in recents (no force-stop)')
        ed.idle(r.uniform(4, 6))                     # field relaunch gap 4-6 s
        mark = ed.log_mark()
        ed.step(f'relaunch {i + 1}/{cycles}: restore {act_re} in a new process')
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/\S+ for (pre-)?top-activity \{com\.myzesty/\S*' + act_re, 15,
                       since=mark, why=f'cold launch must restore {act_re} (performLaunchActivity)')
        ed.mon.allow_death = False
        ed.settle(8)                                 # field NPE lands <1 s after process start


def _f7a4eff3_photo(ed):
    ed.step('Home -> Image Editor -> first image')
    _f7a4eff3_open(ed, ['id:home_cta_image'], r'PhotoActivity', 'photo editor past MainActivity')
    s = ed.ui.wait(('id:gridrl', 'id:select_cover', 'id:image', 'textc:sample'), timeout=15)
    for sel in ('id:gridrl', 'id:select_cover', 'id:image', 'textc:sample'):
        if s is not None and s.find_all(sel):
            ed.dev.tap(*s.find_all(sel)[0].center)
            break
    ed.idle(1)
    for sel in ('id:done', 'id:btn_continue', 'id:next_button'):
        try:
            ed.ui.tap(sel, timeout=3)
        except UIError:
            pass
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5): Image Editor sticker store (StickerResourcesActivity/ResourceActivity) restored after process death."""
    _f7a4eff3_home(ed)
    _f7a4eff3_photo(ed)
    ed.step('stickers -> open the sticker store (Realm resource screen)')
    ed.tap_tool('sticker')
    ed.idle(3)
    _f7a4eff3_open(ed, ['textc:see all', 'textc:view all', 'textc:more', 'id:download_icon', 'id:icon_premium'],
                   r'(StickerResourcesActivity|ResourceActivity)', 'resource screen launched from the photo editor')
    ed.idle(r.uniform(3, 5))                         # categories load from Realm
    _f7a4eff3_restore_loop(ed, r, r'(StickerResourcesActivity|ResourceActivity)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_b(ed, r):
    """All 20 instances: Frames tool (FramesActivity, frame resources from Realm) restored after process death, crash pair on relaunch."""
    _f7a4eff3_home(ed)
    ed.step('Home -> Frames')
    s = ed.screen()
    if s is None or not s.has(('textc:frames',)):
        ed.ui.tap('id:section_action', timeout=10)    # "All Tools"
        ed.idle(2)
    _f7a4eff3_open(ed, ['textc:frames', 'textc:frame'], r'FramesActivity', 'frames screen past MainActivity')
    ed.idle(r.uniform(4, 6))
    _f7a4eff3_restore_loop(ed, r, r'FramesActivity')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_c(ed, r):
    """All 20 instances: Poster/Collage tool (template resources from Realm) restored after process death, crash pair on relaunch."""
    _f7a4eff3_home(ed)
    ed.step('Home -> Poster (or Collage)')
    s = ed.screen()
    if s is None or not s.has(('textc:poster',)) and not s.has(('textc:collage',)):
        ed.ui.tap('id:section_action', timeout=10)
        ed.idle(2)
    _f7a4eff3_open(ed, ['textc:poster', 'textc:collage'], r'(PosterActivity|CollageActivity)',
                   'poster/collage screen past MainActivity')
    ed.idle(r.uniform(4, 6))
    _f7a4eff3_restore_loop(ed, r, r'(PosterActivity|CollageActivity)')


# 2026-10-26 13:24 level 3 attempt 1
_F7_DIED = r'(Killing \d+:com\.myzesty|am_proc_died.*com\.myzesty|Process com\.myzesty .*has died)'


def _f7a4eff3_install(ed):
    """Checkpoint 1 status: Play 1.25.2, and whether it was updated in place (first < last) or freshly installed."""
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName|firstInstallTime|lastUpdateTime"')
    ed.log('    install: ' + ' | '.join(l.strip() for l in out.splitlines()[:6]))
    if '800054890' not in out or 'com.android.vending' not in out:
        raise UIError('not the Play-installed 1.25.2 (800054890) the field crashed on')
    t = {k: l.split('=', 1)[1].strip() for l in out.splitlines() for k in ('firstInstallTime', 'lastUpdateTime') if k in l}
    ed.log(f"    checkpoint 1 in-place update: {t.get('firstInstallTime', '?') < t.get('lastUpdateTime', '?')}")


def _f7a4eff3_open_collage(ed):
    """Home -> Collage (CollageActivity restores and stays on top after a process kill, unlike FramesActivity)."""
    ed.grant_permissions()
    ed.dev.launch()
    ed.ui.wait('id:home_cta_row', timeout=30)
    mark = ed.log_mark()
    try:
        ed.ui.tap('textc:collage', timeout=5)
    except UIError:
        ed.ui.tap('id:section_action', timeout=10)    # "All Tools"
        ed.ui.tap('textc:collage', timeout=10)
    ed.require_log(r'Displayed com\.myzesty/\S*CollageActivity', 30, since=mark, why='checkpoint 2: a screen past MainActivity')
    ed.idle(4)                                       # let its Realm-backed resources load


def _f7a4eff3_loop(ed, r, activity, before_relaunch, cycles=3):
    """Checkpoints 2-5: the process dies with the task kept in recents, then a cold relaunch 4-6 s later, repeated."""
    for i in range(cycles):
        mark = ed.log_mark()
        ed.kill_bg()
        ed.require_log(_F7_DIED, 10, since=mark, why='checkpoint 2: process dies, task stays in recents')
        before_relaunch()
        ed.idle(r.uniform(4, 6))                     # field relaunch gap
        mark = ed.log_mark()
        ed.step(f'cold relaunch {i + 1}/{cycles}')
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/\S+ for pre-top-activity \{com\.myzesty/\S*' + activity, 15,
                       since=mark, why=f'checkpoint 3: cold launch runs performLaunchActivity for {activity}')
        ed.mon.allow_death = False
        ed.settle(8)                                 # the field NPE lands <1 s after process start


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5): CollageActivity restored in a new process with the app cache trimmed and the phone offline."""
    _f7a4eff3_install(ed)
    _f7a4eff3_open_collage(ed)
    try:
        _f7a4eff3_loop(ed, r, 'CollageActivity',
                       lambda: (ed.dev.clear_app_cache(), ed.dev.network(False)))
    finally:
        ed.dev.network(True)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_b(ed, r):
    """All 20: CollageActivity recreated by a config change (dark mode + rotation) to save its Bundle, then killed under memory pressure and restored."""
    _f7a4eff3_install(ed)
    _f7a4eff3_open_collage(ed)
    try:
        ed.dev.dark_mode(True)
        ed.idle(3)
        ed.dev.rotate(True)
        ed.idle(3)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(1)
        _f7a4eff3_loop(ed, r, 'CollageActivity',
                       lambda: ed.dev.sh('am send-trim-memory com.myzesty COMPLETE'))
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_c(ed, r):
    """All 20: the launcher path itself; MainActivity cold-launched again and again on a slow, offline phone with the cache trimmed."""
    _f7a4eff3_install(ed)
    ed.grant_permissions()
    ed.dev.launch()
    ed.ui.wait('id:home_cta_row', timeout=30)
    ed.idle(3)
    try:
        for i in range(3):
            mark = ed.log_mark()
            ed.kill_bg()
            ed.require_log(_F7_DIED, 10, since=mark, why='checkpoint 2: process dies, task stays in recents')
            ed.dev.clear_app_cache()
            ed.dev.network(False)
            ed.dev.slow_phone(30)                    # low-end launch timing
            ed.idle(r.uniform(4, 6))
            mark = ed.log_mark()
            ed.step(f'cold launcher start {i + 1}/3 (offline, cache trimmed, slow CPU)')
            ed.dev.launch()
            ed.require_log(r'Start proc \d+:com\.myzesty/', 20, since=mark, why='checkpoint 3: cold launch')
            ed.mon.allow_death = False
            ed.settle(10)
            ed.dev.slow_phone(0)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-10-26 13:31 level 3 attempt 2
_F7_DIED = r'(Killing \d+:com\.myzesty|am_proc_died.*com\.myzesty|Process com\.myzesty .*has died)'


def _f7a4eff3_update_in_place(ed):
    """Checkpoint 1: replace the installed Play 1.25.2 in place (data kept, installer = Play) so lastUpdateTime > firstInstallTime."""
    paths = [l.split(':', 1)[1].strip() for l in ed.dev.sh('pm path com.myzesty').splitlines() if l.startswith('package:')]
    if not paths:
        raise UIError('com.myzesty is not installed')
    ed.step(f'in-place update of 1.25.2 over its own used data ({len(paths)} splits)')
    ed.mon.allow_death = True                        # the package replace kills the backgrounded process
    ed.dev.sh('mkdir -p /data/local/tmp/ns_f7')
    out = ed.dev.sh('pm install-create -r -i com.android.vending', timeout=30)
    if '[' not in out:
        raise UIError(f'install session not created: {out.strip()[:120]}')
    sid = out.split('[', 1)[1].split(']', 1)[0]
    for i, p in enumerate(paths):
        tmp = f'/data/local/tmp/ns_f7/{i}_{p.rsplit("/", 1)[1]}'
        ed.dev.sh(f'cp {p} {tmp}', timeout=120)
        ed.dev.sh(f'pm install-write {sid} {i}_{p.rsplit("/", 1)[1]} {tmp}', timeout=180)
    res = ed.dev.sh(f'pm install-commit {sid}', timeout=180)
    if 'Success' not in res:
        raise UIError(f'in-place update failed: {res.strip()[:160]}')
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName|firstInstallTime|lastUpdateTime"')
    ed.log('    install: ' + ' | '.join(l.strip() for l in out.splitlines()[:6]))
    t = {k: l.split('=', 1)[1].strip() for l in out.splitlines() for k in ('firstInstallTime', 'lastUpdateTime') if k in l}
    if '800054890' not in out or 'installerPackageName=com.android.vending' not in out or \
            not t.get('firstInstallTime', '') < t.get('lastUpdateTime', ''):
        raise UIError('checkpoint 1 not met: need Play-installer 800054890 with firstInstallTime < lastUpdateTime')


def _f7a4eff3_relaunch_loop(ed, r, cycles=3):
    """Checkpoints 3-5: cold launch 4-6 s after the process died, repeated like the field crash loop."""
    for i in range(cycles):
        ed.idle(r.uniform(4, 6))
        mark = ed.log_mark()
        ed.step(f'cold launch {i + 1}/{cycles} after the in-place update')
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='checkpoint 3: cold launch (performLaunchActivity)')
        ed.mon.allow_death = False
        if ed.wait_log(r'com\.pairip\.licensecheck\.LicenseActivity', 3, since=mark):
            raise UIError('PairIP rejected the shell-committed update: reinstall 1.25.2 from the Play internal-test track')
        ed.settle(8)                                 # the field NPE lands <1 s after process start
        if i < cycles - 1:
            mark = ed.log_mark()
            ed.kill_bg()
            ed.require_log(_F7_DIED, 10, since=mark, why='checkpoint 2: process dies, task stays in recents')


def _f7a4eff3_home(ed):
    ed.grant_permissions()
    ed.dev.launch()
    ed.ui.wait('id:home_cta_row', timeout=30)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_2_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5): Collage left in recents, app updated in place, then a cold relaunch loop."""
    _f7a4eff3_home(ed)
    mark = ed.log_mark()
    if not ed.ui.wait('textc:collage', timeout=5):
        ed.ui.tap('id:section_action', timeout=10)   # "All Tools"
    ed.ui.tap('textc:collage', timeout=10)
    ed.require_log(r'Displayed com\.myzesty/\S*CollageActivity', 30, since=mark, why='checkpoint 2: a screen past MainActivity')
    ed.idle(4)
    ed.dev.key('KEYCODE_HOME')                       # onSaveInstanceState, task kept in recents
    ed.idle(3)
    _f7a4eff3_update_in_place(ed)
    _f7a4eff3_relaunch_loop(ed, r)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_2_b(ed, r):
    """All 20: SlideShow (QuickCutActivity) used, app updated in place, then cold launches offline with the app cache cleared."""
    ed.open_slideshow(3)
    ed.require_log(r'Displayed com\.myzesty/\S*QuickCutActivity', 30, why='checkpoint 2: slideshow screen past MainActivity')
    ed.idle(r.uniform(3, 5))
    ed.dev.key('KEYCODE_HOME')
    ed.idle(3)
    _f7a4eff3_update_in_place(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.network(False)                        # Realm resources cannot be refetched on the first post-update launch
        _f7a4eff3_relaunch_loop(ed, r)
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_2_c(ed, r):
    """All 20: app updated in place while backgrounded on Home, then cold launches on a slow phone under memory pressure."""
    _f7a4eff3_home(ed)
    ed.idle(r.uniform(4, 6))                         # let the home rows (templates, AI Studio) write their Realm data
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.idle(2)
    _f7a4eff3_update_in_place(ed)
    try:
        ed.dev.slow_phone(30)                        # low-end launch timing, like the OnePlus/Honor field phones under load
        _f7a4eff3_relaunch_loop(ed, r)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-10-26 13:43 level 3 attempt 3
_F7_START = r'START u0 \{[^}]*cmp=com\.myzesty/'


def _f7a4eff3_check_install(ed):
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName|firstInstallTime|lastUpdateTime"')
    ed.log('    install: ' + ' | '.join(l.strip() for l in out.splitlines()[:6]))
    if '800054890' not in out or 'com.android.vending' not in out:
        raise UIError('not the Play-installed 1.25.2 (800054890) the field crashed on')


def _f7a4eff3_launch_loop(ed, r, cmds, reps=2):
    """Checkpoints 3-5: each intent becomes the BASE intent of a new task (force-stop first, so recents relaunches
    replay the same intent), cold-launched, then launched again 4-6 s later like the field crash pairs."""
    started = 0
    for cmd in cmds:
        for k in range(reps):
            ed.mon.allow_death = True
            ed.dev.force_stop()
            ed.idle(r.uniform(4, 6))
            mark = ed.log_mark()
            ed.step(f'cold launch {k + 1}/{reps}: {cmd[:110]}')
            ed.dev.sh(cmd, timeout=20)
            if not ed.wait_log(_F7_START, 8, since=mark):
                ed.log('    intent refused / not resolved; next one')
                break
            started += 1
            ed.require_log(r'Start proc \d+:com\.myzesty/', 10, since=mark, why='checkpoint 3: new process for this launch')
            ed.mon.allow_death = False
            ed.settle(7)                             # field NPE lands <1 s after process start, inside performLaunchActivity
    if not started:
        raise UIError('no launch intent reached com.myzesty: checkpoint 3 never happened')


def _f7a4eff3_filters(ed):
    """Exported activities, custom schemes and authorities from the installed APK's Activity Resolver Table."""
    out = ed.dev.sh('dumpsys package com.myzesty', timeout=30).split('Receiver Resolver Table')[0]
    comps = sorted(set(re.findall(r'com\.myzesty/[\w.$]+', out)) - {'com.myzesty/.MainActivity', 'com.myzesty/com.myzesty.MainActivity'})
    schemes = sorted(set(re.findall(r'Scheme: "([\w.+-]+)"', out)) - {'http', 'https', 'file', 'content'})
    hosts = sorted(set(re.findall(r'Authority: "([^"]+)"', out)))
    ed.log(f'    exported={comps[:8]} schemes={schemes} hosts={hosts[:6]}')
    return comps, schemes, hosts


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_3_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5): a push notification tapped while the app is dead -> MainActivity cold-launched with FCM data extras but no table."""
    _f7a4eff3_check_install(ed)
    base = ('am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -f 0x10000000 '
            '-n com.myzesty/.MainActivity --es google.message_id 0:ns{} --es from 1 --es collapse_key com.myzesty ')
    payloads = ['--es Type STICKERS', '--es type 2 --es featureType frames', '--es Type 1 --es category trending',
                '--es screen stickers --es table ""']
    r.shuffle(payloads)
    try:
        ed.dev.network(False)                        # pushed content cannot be fetched: launch reads only local Realm
        _f7a4eff3_launch_loop(ed, r, [base.format(r.randint(1000, 9999)) + p for p in payloads[:3]])
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_3_b(ed, r):
    """All 20: a deep link (notification / ad / web) opens the app cold with a URI that carries no table parameter."""
    _f7a4eff3_check_install(ed)
    comps, schemes, hosts = _f7a4eff3_filters(ed)
    uris = [f'{s}://{h}' for s in schemes for h in (hosts or [''])][:3] + [f'{s}://' for s in schemes][:1]
    uris += [f'https://{h}/' for h in hosts if '.' in h][:2]
    if not uris:
        raise UIError('the installed 1.25.2 declares no deep link (VIEW scheme) to launch')
    _f7a4eff3_launch_loop(ed, r, [f'am start -a android.intent.action.VIEW -d {shlex.quote(u)} -p com.myzesty' for u in uris[:4]])


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_3_c(ed, r):
    """All 20: a launcher shortcut / exported tool Activity started cold with an empty intent (no table extra), relaunched like the field loop."""
    _f7a4eff3_check_install(ed)
    comps, _, _ = _f7a4eff3_filters(ed)
    sc = ed.dev.sh('dumpsys shortcut 2>/dev/null | grep -A40 "Package: com.myzesty" | grep -oE "cmp=com\\.myzesty/[^ }]+"')
    comps = sorted(set(comps) | {c[4:] for c in sc.split()}) or []
    ed.log(f'    shortcut/exported targets: {comps[:8]}')
    if not comps:
        raise UIError('no exported non-Main Activity or shortcut target in the installed 1.25.2')
    r.shuffle(comps)
    _f7a4eff3_launch_loop(ed, r, [f'am start -f 0x10000000 -n {c}' for c in comps[:4]])


# 2026-10-26 13:49 level 4 attempt 1
_F7_DIED = r'(Killing \d+:com\.myzesty|am_proc_died.*com\.myzesty|Process com\.myzesty .*has died)'


def _f7a4eff3_try(ed, sel, t=4):
    try:
        return bool(ed.ui.tap(sel, timeout=t))
    except UIError:
        return False


def _f7a4eff3_top(ed):
    """Checkpoint 2: the resumed activity must be a screen past MainActivity (that is what a restored task relaunches)."""
    out = ed.dev.sh('dumpsys activity activities | grep -m1 -E "mResumedActivity|topResumedActivity"')
    m = re.search(r'com\.myzesty/(\S+?)[ }]', out)
    cls = m.group(1).rsplit('.', 1)[-1] if m else ''
    ed.log(f'    top activity: {cls or out.strip()[:100]}')
    if not cls or cls == 'MainActivity':
        raise UIError('checkpoint 2 not reached: still on MainActivity, no deep screen to restore')
    return cls


def _f7a4eff3_pick_first(ed):
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=15)
    if s is None:
        return
    tiles = s.find_all('id:gridrl')
    if not tiles:
        raise UIError('picker shows no media tile')
    ed.dev.tap(*tiles[0].center)
    ed.idle(2)
    if ed.ui.wait('id:gridrl', timeout=2):
        ed._picker_confirm()


def _f7a4eff3_restore_loop(ed, r, cls, cycles=4):
    """Checkpoints 2-5: HOME + am kill (task and Bundle kept), relaunch 4-6 s later -> performLaunchActivity of the
    restored top; the next kill lands 0.3-1.5 s after it is drawn, while its Realm resources are still loading."""
    for i in range(cycles):
        mark = ed.log_mark()
        ed.kill_bg()
        ed.require_log(_F7_DIED, 10, since=mark, why='checkpoint 2: process dies, task stays in recents')
        if ed.wait_log(r'Force removing ActivityRecord.*com\.myzesty.*no saved state', 2, since=mark):
            raise UIError('task was dropped (no saved state): restore cannot be tested')
        ed.idle(r.uniform(4, 6))                     # field relaunch gap
        mark = ed.log_mark()
        ed.step(f'cold relaunch {i + 1}/{cycles}: restore {cls}')
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/\S+ for pre-top-activity \{com\.myzesty/\S*' + cls, 15,
                       since=mark, why=f'checkpoint 3: cold launch restores {cls} (performLaunchActivity)')
        ed.mon.allow_death = False
        if i < cycles - 1:
            ed.wait_log(r'Displayed com\.myzesty/', 8, since=mark)
            ed.idle(r.uniform(0.3, 1.5))             # kill inside the restored screen's load window
        else:
            ed.settle(8)


def _f7a4eff3_home(ed):
    ed.grant_permissions()
    ed.dev.launch()
    ed.ui.wait('id:home_cta_row', timeout=30)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_1_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5): Image Editor resource panel (sync getAllImageEditorResources) restored after an am kill, loop."""
    _f7a4eff3_home(ed)
    if not _f7a4eff3_try(ed, 'id:home_cta_image', 10):
        raise UIError('no Image Editor button on home')
    _f7a4eff3_pick_first(ed)
    ed.idle(4)
    for name in ('stickers', 'filters', 'frames', 'effects', 'overlay'):
        if _f7a4eff3_try(ed, f'textc:{name}', 3):
            break
    ed.idle(r.uniform(0.5, 2))                       # HOME while the panel's resources load
    _f7a4eff3_restore_loop(ed, r, _f7a4eff3_top(ed))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_1_b(ed, r):
    """All 20: CineMagic (Realm LocalFilters) left on top, process killed, restored again and again 4-6 s apart."""
    _f7a4eff3_home(ed)
    if not (_f7a4eff3_try(ed, 'id:btn_cine_magic') or _f7a4eff3_try(ed, 'textc:cinemagic')):
        _f7a4eff3_try(ed, 'id:section_action', 10)   # "All Tools"
        if not _f7a4eff3_try(ed, 'textc:cinemagic', 10):
            raise UIError('no CineMagic entry')
    _f7a4eff3_pick_first(ed)
    ed.idle(r.uniform(2, 4))
    _f7a4eff3_restore_loop(ed, r, _f7a4eff3_top(ed))


@scenario('nightshift', 'auto')
def ns_f7a4eff3_l4_1_c(ed, r):
    """All 20: video editor with the Stickers panel (Realm DynamicResource) open, killed in the background, restored in a loop."""
    ed.set_playing(False)
    if not _f7a4eff3_try(ed, T.STICKER, 8):
        raise UIError('Stickers panel did not open')
    ed.idle(r.uniform(0.5, 2))
    _f7a4eff3_restore_loop(ed, r, _f7a4eff3_top(ed))


# 2026-10-26 14:00 level 4 attempt 2
_F7_DL = r'START u0 \{[^}]*act=android\.intent\.action\.VIEW[^}]*cmp=com\.myzesty/\S*DeepLinkEntryActivity'
_F7_TOOLS = ['stickers', 'frames', 'filters', 'overlays', 'effects', 'backgrounds', 'fonts', 'cinemagic', 'ns_unknown_tool', '']


def _f7a4eff3_check(ed):
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName"')
    if '800054890' not in out or 'com.android.vending' not in out:
        raise UIError('not the Play-installed 1.25.2 (800054890) the field crashed on')


def _f7a4eff3_link(ed, url, mark):
    """A link tap (notification / web / ad): VIEW intent into DeepLinkEntryActivity, which stores it in deeplink.prefs."""
    ed.dev.sh(f"am start -a android.intent.action.VIEW -c android.intent.category.BROWSABLE -d '{url}' -p com.myzesty", timeout=20)
    return bool(ed.wait_log(_F7_DL, 6, since=mark))


def _f7a4eff3_loop(ed, r, urls, race=False, relaunch=2):
    """Cold start through each link (or race it against a launcher cold start), then launcher relaunches 4-6 s apart:
    a link kept in deeplink.prefs is routed again on every launch, as in the field crash loop."""
    hit = 0
    for url in urls:
        ed.mon.allow_death = True
        ed.dev.force_stop()
        ed.idle(r.uniform(1, 2))
        mark = ed.log_mark()
        ed.step(f'cold link {"race " if race else ""}{url}')
        if race:                                     # MainActivity onCreate still running when the link arrives
            ed.dev.launch()
            ed.wait_log(r'Start proc \d+:com\.myzesty/', 8, since=mark)
            ed.idle(r.uniform(0.1, 0.7))
        if not _f7a4eff3_link(ed, url, mark):
            ed.log('    link not routed to DeepLinkEntryActivity; next')
            continue
        hit += 1
        ed.require_log(r'Start proc \d+:com\.myzesty/', 10, since=mark, why='checkpoint 3: cold start for this launch')
        ed.mon.allow_death = False
        ed.settle(5)                                 # field NPE: <1 s after process start, in performLaunchActivity
        for k in range(relaunch):                    # checkpoint 5: the stored link replays on a plain relaunch
            ed.mon.allow_death = True
            ed.kill_bg()
            ed.idle(r.uniform(4, 6))
            mark = ed.log_mark()
            ed.step(f'launcher relaunch {k + 1}/{relaunch} after {url}')
            ed.dev.launch()
            ed.require_log(r'Start proc \d+:com\.myzesty/', 12, since=mark, why='checkpoint 3: cold relaunch')
            ed.mon.allow_death = False
            ed.settle(4)
    if not hit:
        raise UIError('no link reached DeepLinkEntryActivity: the stored-link launch never happened')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_2_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5): https://myzesty.com/openTool/<tool> link opens the app cold (known and unknown tools), then relaunch loop."""
    _f7a4eff3_check(ed)
    tools = _F7_TOOLS[:]
    r.shuffle(tools)
    _f7a4eff3_loop(ed, r, [f'https://myzesty.com/openTool/{t}' for t in tools[:5]])


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_2_b(ed, r):
    """All 20: myzesty:// scheme and /e/ short links with a missing tool part (no table), offline so nothing is refetched, relaunch loop."""
    _f7a4eff3_check(ed)
    t = r.choice(_F7_TOOLS[:7])
    urls = [f'myzesty://openTool/{t}', 'myzesty://openTool/', 'myzesty://open', f'myzesty://tool?name={t}',
            'https://myzesty.com/e/ns', 'https://myzesty.com/openTool/']
    r.shuffle(urls)
    try:
        ed.dev.network(False)
        _f7a4eff3_loop(ed, r, urls[:4])
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_2_c(ed, r):
    """All 20: an openTool link lands while MainActivity is still launching (race on a slow phone), then the relaunch loop."""
    _f7a4eff3_check(ed)
    tools = _F7_TOOLS[:]
    r.shuffle(tools)
    try:
        ed.dev.slow_phone(r.randint(25, 40))         # low-end launch timing: the link arrives inside onCreate
        _f7a4eff3_loop(ed, r, [f'https://myzesty.com/openTool/{t}' for t in tools[:4]], race=True)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-26 14:09 level 4 attempt 3
_F7_PROC = r'Start proc \d+:com\.myzesty/\S+ for (?:pre-top-activity|top-activity|activity) \{com\.myzesty/([\w.$]+)\}'


def _f7a4eff3_check(ed):
    out = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName"')
    if '800054890' not in out or 'com.android.vending' not in out:
        raise UIError('not the Play-installed 1.25.2 (800054890) the field crashed on')


def _f7a4eff3_top(ed):
    """Checkpoint 2: a screen past MainActivity is on top (the task the system will restore)."""
    out = ed.dev.sh('dumpsys activity activities | grep -m1 -E "mResumedActivity|topResumedActivity"')
    m = re.search(r'com\.myzesty/(\S+?)[ }]', out)
    cls = m.group(1) if m else ''
    ed.log(f'    top activity: {cls or out.strip()[:100]}')
    if not cls or cls.endswith('MainActivity'):
        raise UIError('checkpoint 2 not reached: MainActivity on top, nothing past it to restore')
    return cls


def _f7a4eff3_reclaim(ed):
    """HOME + am kill until the pid is really gone (one am kill missed in l4_2_c); the task + Bundle must survive."""
    mark = ed.log_mark()
    ed.kill_bg()
    for _ in range(6):
        if not ed.dev.pid():
            break
        ed.dev.sh('am kill com.myzesty')
        time.sleep(1)
    if ed.dev.pid():
        raise UIError('process not reclaimed: the relaunch would be warm, not a performLaunchActivity')
    ed.require_log(r'(am_kill.*com\.myzesty|Killing \d+:com\.myzesty|am_proc_died.*com\.myzesty)', 5, since=mark,
                   why='checkpoint 2: process dies while the task stays in recents')
    if ed.wait_log(r'Force removing ActivityRecord.*com\.myzesty.*no saved state', 1, since=mark):
        raise UIError('task dropped with no saved state: restore cannot be tested')


def _f7a4eff3_relaunch(ed, r, n=3):
    """Checkpoints 3-5: cold launcher relaunch 4-6 s after each death (field pairs 08:08:12/08:08:16), n times."""
    for i in range(n):
        _f7a4eff3_reclaim(ed)
        ed.idle(r.uniform(4, 6))
        mark = ed.log_mark()
        ed.step(f'cold relaunch {i + 1}/{n} on the stored state')
        ed.dev.launch()
        line = ed.require_log(_F7_PROC, 15, since=mark, why='checkpoint 3: new process, performLaunchActivity')
        ed.log(f'    launched: {line[-110:]}')
        if i == 0 and re.search(r'\{com\.myzesty/\S*\.MainActivity\}', line):
            raise UIError('checkpoint 3: the first relaunch restored MainActivity, not the saved screen')
        ed.mon.allow_death = False
        ed.settle(6)                                 # field NPE lands <1 s after Start proc


def _f7a4eff3_tap_first(ed, sels, t=8):
    s = ed.ui.wait(sels, timeout=t)
    for sel in sels:
        items = s.find_all(sel) if s is not None else []
        if items:
            ed.dev.tap(*items[0].center)
            return True
    return False


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_3_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5): CineMagic downloads its overlay/bokeh resources (saved with no table) -> killed on top -> cold restore loop."""
    _f7a4eff3_check(ed)
    ed.grant_permissions()
    ed.dev.sh('am start -n com.myzesty/.cinemagic.ui.activity.CineMagicActivity')
    ed.require_log(r'START u0 \{[^}]*cmp=com\.myzesty/\S*CineMagicActivity', 8, why='CineMagic screen opened')
    ed.idle(4)                                       # list + LocalFilters fetch/save from the server
    if _f7a4eff3_tap_first(ed, ('id:rvExamples', 'id:recycler', 'id:recycler_view', 'textc:try')):
        ed.idle(3)
        if _f7a4eff3_tap_first(ed, ('id:select_cover', 'id:gridrl'), t=10):
            ed.idle(1)
            ed._picker_confirm()
        ed.idle(r.uniform(3, 6))                     # into the tools: overlay/bokeh lists written to Realm
    _f7a4eff3_top(ed)
    _f7a4eff3_relaunch(ed, r, 3)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_3_b(ed, r):
    """All 20: SlideShow with its music library loading on a slow network, killed mid-load, cold restore of QuickCutActivity in a loop."""
    _f7a4eff3_check(ed)
    ed.open_slideshow(2)
    try:
        ed.dev.slow_network(48)                      # the library sync is still writing when the process dies
        ed.ui.tap('id:add_music', timeout=5)
        ed.idle(r.uniform(0.4, 1.5))
        _f7a4eff3_top(ed)
        ed.dev.slow_phone(r.randint(20, 35))         # low-end launch timing on the relaunches
        _f7a4eff3_relaunch(ed, r, 3)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_3_c(ed, r):
    """All 20: Image Editor resource panel storm: process killed 0.2-1.2 s into each resource sync, then cold relaunch, 4 cycles."""
    _f7a4eff3_check(ed)
    ed.grant_permissions()
    ed.dev.sh('pm trim-caches 999G')                 # no cached resource lists: each panel refetches and rewrites
    try:
        ed.dev.slow_network(64)
        for k in range(4):
            ed.step(f'image editor sync/kill cycle {k + 1}/4')
            ed.dev.launch()
            if not ed.ui.tap('id:home_cta_image', timeout=20):
                raise UIError('no Image Editor button on home')
            if _f7a4eff3_tap_first(ed, ('id:gridrl', 'id:select_cover'), t=15):
                ed.idle(1)
                ed._picker_confirm()
            ed.idle(3)
            for name in ('stickers', 'filters', 'frames', 'effects', 'overlay'):
                if ed.ui.tap(f'textc:{name}', timeout=3):
                    break
            ed.idle(r.uniform(0.2, 1.2))             # kill inside the panel's Realm write
            if k == 0:
                _f7a4eff3_top(ed)
            _f7a4eff3_relaunch(ed, r, 1 if k else 2)
    finally:
        ed.dev.restore_env()


# 2026-10-26 14:17 level 5 attempt 3
def _f7a4eff3_relaunch_twice(ed, why):
    """Cold launch from the launcher (restores the saved task if one is kept), then again 5 s later (field crash loop)."""
    for k in range(2):
        ed.mon.allow_death = True
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'{why}: cold start {k + 1}')
        ed.idle(5)
        ed.mon.allow_death = False
        ed.dev.key('KEYCODE_HOME')
        ed.dev.kill_bg()                             # reclaim, not force-stop: the task and its Bundle survive


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l5_3_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5): hook passes table=null into RealmWrapper during launch, 2 cold starts."""
    ed.dev.force_stop()
    ed.dev.setprop('debug.zesty.hook.null_table', '1')
    try:
        _f7a4eff3_relaunch_twice(ed, 'launch with null-table hook')
    finally:
        ed.dev.setprop('debug.zesty.hook.null_table', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l5_3_b(ed, r):
    """OnePlus8Pro crash pairs (08:08:12/16, 07:17:33/37, 09:51:23/29): slideshow left on top, process reclaimed, restored twice."""
    ed.open_slideshow(2)
    ed.idle(3)
    ed.dev.key('KEYCODE_HOME')
    mark = ed.log_mark()
    ed.dev.kill_bg()
    ed.require_log(r'(am_proc_died|am_kill|Killing \d+:com\.myzesty)', 15, since=mark,
                   why='process must die with the QuickCut task kept in recents')
    _f7a4eff3_relaunch_twice(ed, 'restore QuickCutActivity task')


@scenario('nightshift', 'auto')
def ns_f7a4eff3_l5_3_c(ed, r):
    """HRY-LX1T instances: editor (PlayerActivity) left on top after a play, process reclaimed, restored twice."""
    ed.set_playing(True)
    ed.idle(3)
    ed.set_playing(False)
    ed.dev.key('KEYCODE_HOME')
    mark = ed.log_mark()
    ed.dev.kill_bg()
    ed.require_log(r'(am_proc_died|am_kill|Killing \d+:com\.myzesty)', 15, since=mark,
                   why='process must die with the editor task kept in recents')
    _f7a4eff3_relaunch_twice(ed, 'restore PlayerActivity task')
