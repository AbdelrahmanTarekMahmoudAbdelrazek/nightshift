# Night Shift auto repros for 7200d24e35f7fea6f67064c99e27adeb


# 2026-10-10 20:07 level 2 attempt 1
def _7200d24e_stickers(ed, r, tab=None):
    """Editor -> Stickers panel (sticker category Realm read); optionally pick a category tab."""
    ed.main_nav()
    ed.menu_tap('sticker')
    ed.ui.wait(T.STICKER_LIST, timeout=12)
    ed.idle(r.uniform(1, 2))
    if tab:
        ed.ui.tap((f'desc:ve_cat_sticker_{tab}', f'text:{tab.capitalize()}'), timeout=5)
        ed.idle(r.uniform(1, 2))


@scenario('nightshift', 'auto')
def ns_7200d24e_l2_1_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2): leave the app on the sticker panel, the OS kills it, the user comes back -> restored launch."""
    _7200d24e_stickers(ed, r, tab=r.choice(['animation', 'neon']))
    ed.step('home on the sticker panel; open the camera like a user, then wait for the OS to drop the process')
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
    time.sleep(3)
    ed.dev.sh(f'am send-trim-memory {PKG} COMPLETE')
    ed.idle(r.uniform(40, 70))
    ed.dev.key('KEYCODE_HOME')
    ed.idle(2)
    ed.dev.launch()                                  # recents/launcher: re-creates the task's top Activity (performLaunchActivity)
    ed.idle(6)
    ed.mon.allow_death = False
    ed.ui.tap(T.STICKER, timeout=5)                  # the user carries on with stickers on the restored screen
    ed.idle(4)


@scenario('nightshift', 'auto')
def ns_7200d24e_l2_1_b(ed, r):
    """All 6 (FOREGROUND, launch path): after adding a sticker ('Recent' tab appears), go home and come back, then reopen the sticker panel and browse every category."""
    ed.add_sticker()                                 # writes a recent sticker -> category list changes on next open
    ed.idle(2)
    _7200d24e_stickers(ed, r)
    ed.step('home with the sticker panel open, return through the launcher')
    ed.dev.key('KEYCODE_HOME')
    ed.idle(r.uniform(8, 20))
    ed.dev.launch()
    ed.idle(4)
    for tab in ('recent', 'animation', 'neon', 'trending', 'reactions', 'smileys', 'animals', 'others'):
        ed.ui.tap((f'desc:ve_cat_sticker_{tab}',), timeout=5)
        ed.idle(r.uniform(0.8, 1.6))
    ed.dev.key('KEYCODE_BACK')
    ed.idle(2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l2_1_c(ed, r):
    """All 6 (cold start): a new process opens the draft and goes straight to the sticker panel while the asset worker is still filling Realm."""
    ed.step('cold start -> draft -> stickers at once')
    ed.dev.force_stop()
    ed.idle(2)
    ed.dev.launch()
    ed.idle(r.uniform(2, 4))
    ed.open_draft()
    _7200d24e_stickers(ed, r, tab='animation')
    ed.ui.tap(('desc:ve_cat_sticker_trending',), timeout=5)
    ed.idle(3)
    ed.dev.key('KEYCODE_BACK')
    ed.idle(1)
    ed.leave_editor()
    ed.open_draft()                                  # second launch of PlayerActivity in the same young process
    _7200d24e_stickers(ed, r, tab='neon')
    ed.idle(3)


# 2026-10-10 20:15 level 2 attempt 2
def _7200d24e_open_stickers(ed, r):
    """Editor -> sticker panel: wizard 'Stickers' button if shown, else drag the main bar to its end and tap item 6."""
    ed.step('open the sticker panel')
    ed.main_nav()
    ed.seek_start()                                  # the button refuses with < 0.5 s left on the timeline
    sel = ('id:sticker', 'id:stickerTv', T.STICKER)
    for _ in range(4):
        s = ed.screen()
        if s is not None and s.has(T.STICKER_LIST):
            break
        if s is not None and s.has(sel):
            ed.dev.tap(*s.find(sel).center)
        else:
            bar, items, back = ed.bar.read()         # main bar is invisible to uiautomator: drag it, no fling
            if bar is not None:
                l, t, rr, b = bar.b
                ed.dev.drag_no_fling(min(rr, ed.dev.w) - 80, t + 12, l + 80)
                ed.idle(1)
            try:
                ed.menu_tap('sticker')
            except UIError as e:
                ed.log(f'    main bar: {e}')
        ed.idle(2.5)
    ed.ui.wait(T.STICKER_LIST, timeout=12)           # trigger step: raises if the panel never opened
    ed.idle(r.uniform(1, 2))


def _7200d24e_tabs(ed, r, tabs):
    for tab in tabs:
        ed.ui.tap((f'desc:ve_cat_sticker_{tab}', f'text:{tab.capitalize()}'), timeout=5)
        ed.idle(r.uniform(0.8, 1.6))


def _7200d24e_killed_in_background(ed, r):
    """HOME, the OS drops the cached process (am kill keeps the task + saved state), user returns via the launcher."""
    ed.step('home on the sticker panel -> process killed in background -> return (restored launch)')
    ed.mon.allow_death = True
    old = ed.dev.pid()
    ed.dev.key('KEYCODE_HOME')
    ed.idle(r.uniform(4, 8))
    for _ in range(3):
        ed.dev.sh(f'am kill {PKG}')
        ed.idle(2)
        if ed.dev.pid() in ('', None):
            break
    ed.log(f'    pid {old} -> {ed.dev.pid() or "dead"}')
    ed.dev.launch()                                  # brings the old task back: performLaunchActivity with savedState
    ed.idle(6)
    ed.mon.allow_death = False


@scenario('nightshift', 'auto')
def ns_7200d24e_l2_2_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2, restore path): sticker panel open, app killed in background, user returns."""
    _7200d24e_open_stickers(ed, r)
    _7200d24e_tabs(ed, r, [r.choice(['neon', 'trending', 'reactions'])])
    _7200d24e_killed_in_background(ed, r)
    _7200d24e_tabs(ed, r, ['animation', 'trending', 'smileys'])   # carries on in the restored panel
    ed.idle(3)


@scenario('nightshift', 'auto')
def ns_7200d24e_l2_2_b(ed, r):
    """All 6 (config-change relaunch): sticker panel open, system dark mode flips -> PlayerActivity re-created with the panel."""
    _7200d24e_open_stickers(ed, r)
    _7200d24e_tabs(ed, r, ['animals'])
    try:
        for on in (True, False):
            ed.step(f'dark mode {"on" if on else "off"} with the sticker panel open')
            ed.dev.dark_mode(on)
            ed.idle(5)
            _7200d24e_tabs(ed, r, [r.choice(['neon', 'others', 'reactions'])])
    finally:
        ed.dev.dark_mode(False)
    ed.idle(3)


@scenario('nightshift', 'auto')
def ns_7200d24e_l2_2_c(ed, r):
    """All 6 (returning sticker user): a recent sticker exists ('Recent' tab first), panel reopened, then process death + return."""
    ed.add_sticker() if False else None              # add_sticker uses the broken index path; do it by hand
    _7200d24e_open_stickers(ed, r)
    s = ed.screen()
    tiles = s.items(T.STICKER_LIST) if s else []
    if tiles:
        ed.dev.tap(*r.choice(tiles[:6]).center)      # pick a sticker -> written to RecentStickers
        ed.idle(3)
        ed.ui.tap(('desc:ve_sticker_apply', T.DONE), timeout=5)
        ed.idle(2)
    _7200d24e_open_stickers(ed, r)                   # reopen: Recent tab now first, tab 1 auto-selected
    _7200d24e_tabs(ed, r, ['recent', 'animation'])
    _7200d24e_killed_in_background(ed, r)
    _7200d24e_tabs(ed, r, ['recent', 'neon', 'trending'])
    ed.idle(3)


# 2026-10-10 20:28 level 3 attempt 1
def _7200d24e_restore(ed, r, pressure='COMPLETE'):
    """HOME -> memory pressure -> am kill (keeps the task and saved state, unlike force-stop) -> back via launcher."""
    ed.step('home -> trim memory -> am kill -> relaunch (performLaunchActivity with savedInstanceState)')
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')
    ed.idle(r.uniform(3, 6))
    ed.dev.sh(f'am send-trim-memory {PKG} {pressure}')
    for _ in range(3):
        ed.dev.sh(f'am kill {PKG}')
        ed.idle(2)
        if not ed.dev.pid():
            break
    ed.log(f'    pid after kill: {ed.dev.pid() or "dead"}')
    ed.dev.launch()                                  # restores the task's top Activity, not MainActivity
    ed.idle(6)
    ed.mon.allow_death = False


def _7200d24e_animation(ed, r):
    ed.step('home -> Animation screen (the only sticker host in this lab APK)')
    ed.ui.tap(('id:btnAnimation', 'text:ANIMATION'), timeout=15)   # trigger step: raises if missing
    ed.idle(r.uniform(3, 5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_1_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), restore path: sticker host screen, process killed in background, user returns."""
    _7200d24e_animation(ed, r)
    _7200d24e_restore(ed, r, 'RUNNING_CRITICAL')
    _7200d24e_restore(ed, r, 'COMPLETE')
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_1_b(ed, r):
    """All 6, cold data path: offline + empty cache, sticker host recreated by a config change, then a restore relaunch."""
    ed.dev.clear_app_cache()
    ed.dev.network(False)
    try:
        _7200d24e_animation(ed, r)
        for s in (1.3, 1.0):                         # fontScale is not in configChanges: real recreate
            ed.step(f'font scale {s}')
            ed.dev.font_scale(s)
            ed.idle(5)
        _7200d24e_restore(ed, r)
    finally:
        ed.dev.restore_env()
    ed.idle(4)


@scenario('nightshift', 'auto')
def ns_7200d24e_l3_1_c(ed, r):
    """All 6, unknown host screen: start any photo/image/sticker Activity the APK has, then restore-relaunch offline."""
    ed.step('probe the installed APK for an image-editor / sticker Activity')
    out = ed.dev.sh(f"dumpsys package {PKG} | grep -oiE '[A-Za-z0-9_.]*(Photo|Image|Sticker)[A-Za-z0-9_]*Activity' | sort -u")
    ed.log(f'    candidates: {out.strip() or "none"}')
    for name in [n for n in out.split() if n][:4]:
        ed.dev.sh(f'am start -n {PKG}/{name}')
        ed.idle(4)
        _7200d24e_restore(ed, r)
    ed.dev.network(False)
    try:
        _7200d24e_restore(ed, r)                     # editor restored offline (no sticker data reachable)
    finally:
        ed.dev.restore_env()
    ed.idle(4)


# 2026-10-10 20:33 level 3 attempt 2
def _7200d24e_hosts(ed):
    """Setup gate. Only the shipped host build has the caller of getAllImageEditorResources. The lab APK does not
    (StickersPresenter is never created), so stop at this step until 1.25.1 (800054867) is installed."""
    ed.step('check the installed build and find the image-editor / sticker host Activities')
    ver = ed.dev.sh(f'dumpsys package {PKG} | grep -m1 -oE "versionCode=[0-9]+"').strip()
    ed.log(f'    installed {ver or "unknown"}')
    out = ed.dev.sh(f'dumpsys package {PKG} | grep -oE "{PKG}/[A-Za-z0-9_.]*(Photo|Image|Sticker|Resource|Editor)[A-Za-z0-9_]*" | sort -u')
    hosts = [h for h in out.split() if 'VideoEditor' not in h and 'PlayerActivity' not in h]
    ed.log(f'    host candidates: {hosts or "none"}')
    if '800054867' not in ver or not hosts:
        raise UIError('setup: the shipped 1.25.1 (800054867) host image-editor APK is not installed; '
                      'nothing in this APK calls getAllImageEditorResources')
    return hosts[:4]


def _7200d24e_kill_return(ed, r):
    """HOME -> trim memory -> am kill (task and saved state kept) -> launcher: the top Activity is re-created."""
    ed.step('home -> trim COMPLETE -> am kill -> return (restore launch)')
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')
    ed.idle(r.uniform(3, 6))
    ed.dev.sh(f'am send-trim-memory {PKG} COMPLETE')
    for _ in range(3):
        ed.dev.sh(f'am kill {PKG}')
        ed.idle(2)
        if not ed.dev.pid():
            break
    ed.dev.launch()
    ed.idle(6)
    ed.mon.allow_death = False


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_2_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), restore path: host sticker screen open, process killed in background, user returns."""
    for h in _7200d24e_hosts(ed):
        ed.dev.sh(f'am start -n {h}')
        ed.idle(r.uniform(3, 5))
        _7200d24e_kill_return(ed, r)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_2_b(ed, r):
    """All 6, missing-extra path: a fresh process launches the host screen straight away, without the table extra."""
    for h in _7200d24e_hosts(ed):
        ed.step(f'cold launch {h} with no extras')
        ed.mon.allow_death = True
        ed.dev.sh(f'am kill {PKG}')
        ed.idle(1)
        ed.mon.allow_death = False
        ed.dev.sh(f'am start -W -n {h}')
        ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_2_c(ed, r):
    """All 6, config-change path: host sticker screen re-created by dark mode and font scale, then a restore relaunch."""
    hosts = _7200d24e_hosts(ed)
    try:
        for h in hosts:
            ed.dev.sh(f'am start -n {h}')
            ed.idle(4)
            for on in (True, False):
                ed.step(f'dark mode {on} on {h}')
                ed.dev.dark_mode(on)
                ed.idle(4)
            ed.dev.font_scale(1.3)
            ed.idle(4)
            _7200d24e_kill_return(ed, r)
    finally:
        ed.dev.restore_env()


# 2026-10-10 20:37 level 3 attempt 3
def _7200d24e_dump(ed, args, path='/data/local/tmp/ns_7200d24e.txt'):
    ed.dev.sh(f'{args} > {path} 2>/dev/null')              # file first: piping dumpsys breaks ("Broken pipe")
    return path


def _7200d24e_host(ed):
    """Setup gate: find the installed 1.25.1 (8000548xx) build under ANY package and its image-editor/sticker Activities."""
    ed.step('find the shipped 1.25.1 image-editor build (any package) and its sticker/image Activities')
    pkgs = [p.split(':', 1)[1].strip() for p in ed.dev.sh('pm list packages').split()
            if p.startswith('package:') and ('zesty' in p.lower() or 'mitrotek' in p.lower())]
    for pkg in pkgs:
        f = _7200d24e_dump(ed, f'dumpsys package {pkg}')
        ver = ed.dev.sh(f'grep -m1 -oE "versionCode=[0-9]+" {f}').strip()
        acts = ed.dev.sh(f'grep -oE "{pkg}/[A-Za-z0-9_.$]*(Photo|Image|Sticker|Editor|Collage)[A-Za-z0-9_]*Activity" {f} | sort -u').split()
        acts = [a for a in acts if 'VideoEditor' not in a and 'Player' not in a]
        ed.log(f'    {pkg}: {ver or "?"} activities={acts or "none"}')
        if '8000548' in ver and acts:
            return pkg, acts[:3]
    raise UIError('setup: no installed package is 1.25.1 (8000548xx) with an image-editor/sticker Activity; '
                  'this lab APK never calls getAllImageEditorResources (StickersPresenter is never created)')


def _7200d24e_return(ed, pkg):
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')   # brings the old task back, like Recents
    ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_3_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), process-death restore: host sticker screen, HOME, trim + am kill, return."""
    pkg, acts = _7200d24e_host(ed)
    for a in acts:
        ed.dev.sh(f'am start -n {a}')
        ed.idle(r.uniform(3, 5))
        ed.step(f'{a}: home -> trim COMPLETE -> am kill -> return (savedInstanceState launch)')
        ed.mon.allow_death = True
        ed.dev.key('KEYCODE_HOME')
        ed.idle(r.uniform(3, 6))
        ed.dev.sh(f'am send-trim-memory {pkg} COMPLETE')
        ed.dev.sh(f'am kill {pkg}')
        ed.idle(2)
        ed.mon.allow_death = False
        _7200d24e_return(ed, pkg)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_3_b(ed, r):
    """All 6, activity-destroyed restore (OEM aggressive reclaim): 'Don't keep activities' on, host screen, HOME, return."""
    pkg, acts = _7200d24e_host(ed)
    ed.dev.sh('settings put global always_finish_activities 1')
    try:
        for a in acts:
            ed.dev.sh(f'am start -n {a}')
            ed.idle(r.uniform(3, 5))
            ed.step(f'{a}: home (activity destroyed with saved state) -> return')
            ed.dev.key('KEYCODE_HOME')
            ed.idle(r.uniform(2, 4))
            _7200d24e_return(ed, pkg)
    finally:
        ed.dev.sh('settings put global always_finish_activities 0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l3_3_c(ed, r):
    """All 6, config-change relaunch: host sticker screen re-created by dark mode, font scale and rotation."""
    pkg, acts = _7200d24e_host(ed)
    try:
        for a in acts:
            ed.dev.sh(f'am start -n {a}')
            ed.idle(4)
            for step, fn in (('dark on', lambda: ed.dev.dark_mode(True)), ('font 1.3', lambda: ed.dev.font_scale(1.3)),
                             ('landscape', lambda: ed.dev.rotate(True)), ('back to normal', ed.dev.restore_env)):
                ed.step(f'{a}: {step}')
                fn()
                ed.idle(4)
    finally:
        ed.dev.restore_env()


# 2026-10-10 20:41 level 4 attempt 1
_7200d24e_STAGED = '/data/local/tmp/ns_host_1251.apk'


def _7200d24e_host(ed):
    """Setup gate: the shipped 1.25.1 (8000548xx) build that can call getAllImageEditorResources. Never auto-replaces the lab APK."""
    ed.step('setup: find the shipped 1.25.1 host build and its image-editor/sticker Activities')
    if 'ns_host_1251.apk' in ed.dev.sh('ls /data/local/tmp'):
        ed.log('    ' + ed.dev.sh(f'pm install -r -d {_7200d24e_STAGED} 2>&1').strip())
    pkgs = [p.split(':', 1)[1].strip() for p in ed.dev.sh('pm list packages').split() if 'zesty' in p.lower()]
    for pkg in pkgs:
        f = '/data/local/tmp/ns_7200d24e.txt'
        ed.dev.sh(f'dumpsys package {pkg} > {f} 2>/dev/null')
        ver = ed.dev.sh(f'grep -m1 -oE "versionCode=[0-9]+" {f}').strip()
        acts = [a for a in ed.dev.sh(f'grep -oE "{pkg}/[A-Za-z0-9_.$]*(Photo|Image|Sticker|Collage)[A-Za-z0-9_]*Activity" {f} | sort -u').split()]
        ed.log(f'    {pkg}: {ver or "?"} {acts or "no host activity"}')
        if '8000548' in ver and acts:
            return pkg, acts[:3]
    raise UIError(f'setup: shipped 1.25.1 (800054867) not installed and not staged at {_7200d24e_STAGED}; '
                  'lab APK 80005266 never constructs StickersPresenter, the only caller of getAllImageEditorResources')


def _7200d24e_kill_return(ed, pkg, away):
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')
    ed.idle(away)
    ed.dev.sh(f'am kill {pkg}')                     # not force-stop: the task and its saved state survive
    ed.idle(0.5)
    ed.mon.allow_death = False
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')   # like Recents: restores the top Activity
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_1_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), restore race: host sticker screen, repeated HOME + am kill + quick return."""
    pkg, acts = _7200d24e_host(ed)
    for a in acts:
        ed.step(f'{a}: 6 kill/restore cycles, short time away')
        ed.dev.sh(f'am start -n {a}')
        ed.idle(r.uniform(2, 4))
        for _ in range(6):
            _7200d24e_kill_return(ed, pkg, r.uniform(0.5, 3))


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_1_b(ed, r):
    """All 6, cold-start race: the host screen launched straight into a dead process (Constants/Realm not yet set up)."""
    pkg, acts = _7200d24e_host(ed)
    for a in acts:
        ed.step(f'{a}: 8 cold launches straight into the screen')
        for _ in range(8):
            ed.mon.allow_death = True
            ed.dev.sh(f'am kill {pkg}')
            ed.dev.key('KEYCODE_HOME')
            ed.idle(r.uniform(0.3, 1))
            ed.mon.allow_death = False
            ed.dev.sh(f'am start -n {a}')
            ed.idle(r.uniform(1, 3))


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_1_c(ed, r):
    """All 6, config-relaunch race: dark mode / font scale flipped quickly while the host sticker screen relaunches."""
    pkg, acts = _7200d24e_host(ed)
    try:
        for a in acts:
            ed.dev.sh(f'am start -n {a}')
            ed.idle(3)
            ed.step(f'{a}: config-change storm')
            for i in range(8):
                ed.dev.dark_mode(i % 2 == 0) if r.random() < 0.6 else ed.dev.font_scale(1.3 if i % 2 == 0 else 1.0)
                ed.idle(r.uniform(0.2, 0.8))
            _7200d24e_kill_return(ed, pkg, 2)
    finally:
        ed.dev.restore_env()


# 2026-10-10 20:44 level 4 attempt 2
_7200d24e_DIRS = ('/data/local/tmp', '/sdcard/Download', '/sdcard/NightShift', '/sdcard/DCIM/NightShift')
_7200d24e_VIDEO = ('MainActivity', 'PlayerActivity', 'QuickCutActivity', 'BaseVideoEditorActivity', 'CoverActivity',
                   'MtpPopupActivity', 'AnimationActivity', 'UCropActivity', 'Provider')


def _7200d24e_host(ed):
    """Setup gate: install the staged shipped 1.25.1 (800054867) APK if found, then list its non-video Activities."""
    ed.step('setup: stage/install shipped 1.25.1 host APK, list its image-editor/sticker Activities')
    for d in _7200d24e_DIRS:
        for apk in ed.dev.sh(f'ls {d} 2>/dev/null | grep -iE "\\.apk$" | grep -E "1251|1\\.25\\.1|800054867"').split():
            ed.log(f'    install {d}/{apk}: ' + ed.dev.sh(f'pm install -r -d {d}/{apk} 2>&1').strip()[-80:])
    f = '/data/local/tmp/ns_7200d24e.txt'
    ed.dev.sh(f'dumpsys package {PKG} > {f} 2>/dev/null')           # file first: piping dumpsys -> Broken pipe
    ver = ed.dev.sh(f'grep -m1 -oE "versionCode=[0-9]+" {f}').strip()
    acts = sorted(set(ed.dev.sh(f'grep -oE "{PKG}/[A-Za-z0-9_.$]+Activity" {f}').split()))
    acts = [a for a in acts if not any(v in a for v in _7200d24e_VIDEO)]
    pref = [a for a in acts if any(k in a for k in ('Sticker', 'Photo', 'Image', 'Collage', 'Editor'))]
    ed.log(f'    {ver or "?"} hosts={pref or acts or "none"}')
    if '8000548' not in ver or not acts:
        raise UIError(f'setup: shipped 1.25.1 (800054867) APK not staged in {_7200d24e_DIRS}; lab APK {ver} never '
                      'constructs StickersPresenter, the only caller of getAllImageEditorResources')
    return (pref or acts)[:4]


def _7200d24e_kill_back(ed, away):
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')
    ed.idle(away)
    ed.dev.sh(f'am kill {PKG}')                                        # not force-stop: saved state survives
    ed.idle(0.3)
    ed.mon.allow_death = False
    ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1')  # like Recents: re-creates the top Activity
    ed.idle(3)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_2_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), restore race: host sticker screen, HOME, am kill, quick return x6."""
    for a in _7200d24e_host(ed):
        ed.step(f'{a}: 6 process-death restores')
        ed.dev.sh(f'am start -n {a}')
        ed.idle(r.uniform(2, 4))
        for _ in range(6):
            _7200d24e_kill_back(ed, r.uniform(0.5, 3))


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_2_b(ed, r):
    """All 6, cold-start race: host screen started straight into a dead process with no extras (table/statics unset)."""
    for a in _7200d24e_host(ed):
        ed.step(f'{a}: 8 cold launches, no extras')
        for _ in range(8):
            ed.mon.allow_death = True
            ed.dev.sh(f'am kill {PKG}')
            ed.idle(r.uniform(0.2, 0.8))
            ed.mon.allow_death = False
            ed.dev.sh(f'am start -n {a}')
            ed.idle(r.uniform(0.8, 2.5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_2_c(ed, r):
    """All 6, 'Don't keep activities' (OEM reclaim on Huawei/OnePlus): host screen destroyed on HOME, returned fast."""
    ed.dev.sh('settings put global always_finish_activities 1')
    try:
        for a in _7200d24e_host(ed):
            ed.step(f'{a}: 6 destroy/recreate cycles')
            ed.dev.sh(f'am start -n {a}')
            ed.idle(3)
            for _ in range(6):
                ed.dev.key('KEYCODE_HOME')
                ed.idle(r.uniform(0.3, 2))
                ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1')
                ed.idle(r.uniform(1, 3))
    finally:
        ed.dev.sh('settings put global always_finish_activities 0')


# 2026-10-10 20:48 level 4 attempt 3
# Setup gate. The lab APK (80005266, debug-signed, built from this repo) never constructs StickersPresenter, the only
# caller of getAllImageEditorResources, and this Mac has no 1.25.1 artifact (only app-productionInternal-debug.apk).
# The engineer drops the Play/release APK at repro_assets/host_1.25.1.apk. We push it, install it, and check the version.
_7200d24e_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'repro_assets', 'host_1.25.1.apk')
_7200d24e_DST = '/data/local/tmp/ns_host_1251.apk'
_7200d24e_SKIP = ('MainActivity', 'PlayerActivity', 'QuickCutActivity', 'BaseVideoEditorActivity', 'CoverActivity',
                  'MtpPopupActivity', 'AnimationActivity', 'UCropActivity')


def _7200d24e_setup(ed):
    """Push + install the shipped 1.25.1 build, then return its image-editor/sticker Activities (else UIError)."""
    ed.step('setup: push repro_assets/host_1.25.1.apk, install it, list host Activities')
    if os.path.exists(_7200d24e_SRC):
        ed.dev.adb('push', _7200d24e_SRC, _7200d24e_DST, timeout=300)
        out = ed.dev.sh(f'pm install -r -d {_7200d24e_DST} 2>&1').strip()
        ed.log(f'    install: {out[-120:]}')   # release vs debug signature -> INSTALL_FAILED_UPDATE_INCOMPATIBLE
    f = '/data/local/tmp/ns_7200d24e.txt'
    ed.dev.sh(f'dumpsys package {PKG} > {f} 2>/dev/null')            # file first: a pipe gives "Broken pipe"
    ver = ed.dev.sh(f'grep -m1 -oE "versionCode=[0-9]+" {f}').strip()
    acts = sorted(set(ed.dev.sh(f'grep -oE "{PKG}/[A-Za-z0-9_.$]+Activity" {f}').split()))
    acts = [a for a in acts if not any(s in a for s in _7200d24e_SKIP)]
    pref = [a for a in acts if any(k in a for k in ('Sticker', 'Photo', 'Image', 'Collage', 'Editor'))]
    ed.log(f'    {ver or "?"} hosts={pref or acts or "none"}')
    if '8000548' not in ver or not acts:
        raise UIError(f'setup: {PKG} is {ver}, not 1.25.1 (800054867). Put the release APK at {_7200d24e_SRC} '
                      '(if its signature differs, uninstall the debug build by hand first)')
    ed.dev.launch()
    ed.idle(3)
    return (pref or acts)[:4]


def _7200d24e_open(ed, a):
    ed.dev.sh(f'am start -n {a}')
    ed.idle(3)


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_3_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), process-death restore race: host sticker screen, HOME, am kill, Recents x6."""
    for a in _7200d24e_setup(ed):
        ed.step(f'{a}: 6 HOME -> am kill -> relaunch with savedInstanceState')
        _7200d24e_open(ed, a)
        for _ in range(6):
            ed.mon.allow_death = True
            ed.dev.key('KEYCODE_HOME')
            ed.idle(r.uniform(0.5, 3))
            ed.dev.sh(f'am kill {PKG}')                               # not force-stop: the task keeps its saved state
            ed.idle(0.3)
            ed.mon.allow_death = False
            ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1')
            ed.idle(r.uniform(1, 3))


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_3_b(ed, r):
    """All 6, cold-start race: host screen started straight into a dead process with no extras (table/statics unset)."""
    for a in _7200d24e_setup(ed):
        ed.step(f'{a}: 8 cold direct launches, no extras')
        for _ in range(8):
            ed.mon.allow_death = True
            ed.dev.sh(f'am kill {PKG}')
            ed.dev.key('KEYCODE_HOME')
            ed.idle(r.uniform(0.2, 0.8))
            ed.mon.allow_death = False
            ed.dev.sh(f'am start -n {a}')
            ed.idle(r.uniform(0.8, 2.5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l4_3_c(ed, r):
    """All 6, config/OEM-reclaim relaunch race: dark-mode/font storm, then 'Don't keep activities' HOME/return x6."""
    try:
        for a in _7200d24e_setup(ed):
            _7200d24e_open(ed, a)
            ed.step(f'{a}: config-change storm')
            for i in range(8):
                if r.random() < 0.6:
                    ed.dev.dark_mode(i % 2 == 0)
                else:
                    ed.dev.font_scale(1.3 if i % 2 == 0 else 1.0)
                ed.idle(r.uniform(0.2, 0.8))
            ed.dev.restore_env()
            ed.step(f'{a}: activity destroyed on HOME, returned fast')
            ed.dev.sh('settings put global always_finish_activities 1')
            _7200d24e_open(ed, a)
            for _ in range(6):
                ed.dev.key('KEYCODE_HOME')
                ed.idle(r.uniform(0.3, 2))
                ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1')
                ed.idle(r.uniform(1, 3))
    finally:
        ed.dev.sh('settings put global always_finish_activities 0')
        ed.dev.restore_env()


# 2026-10-10 20:53 level 5 attempt 1
_7200d24e_HOOK = 'debug.zesty.hook.null_sticker_table'


@scenario('nightshift', 'auto')
def ns_7200d24e_l5_1_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), restore path: editor in background, am kill, back from Recents -> onCreate(saved)."""
    ed.idle(r.uniform(2, 4))
    ed.dev.setprop(_7200d24e_HOOK, '1')
    try:
        ed.step('HOME, am kill (keeps saved state), relaunch -> PlayerActivity re-created')
        ed.mon.allow_death = True
        ed.dev.key('KEYCODE_HOME')
        ed.idle(r.uniform(1, 3))
        ed.dev.sh(f'am kill {PKG}')
        ed.idle(0.5)
        ed.mon.allow_death = False
        ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1')
        ed.idle(6)
    finally:
        ed.dev.setprop(_7200d24e_HOOK, '0')


@scenario('nightshift', 'auto')
def ns_7200d24e_l5_1_b(ed, r):
    """All 6, config relaunch path: dark mode / rotation re-creates the live PlayerActivity in the foreground."""
    ed.idle(r.uniform(2, 4))
    ed.dev.setprop(_7200d24e_HOOK, '1')
    try:
        ed.step('dark mode on -> PlayerActivity relaunch')
        ed.dev.dark_mode(True)
        ed.idle(5)
        ed.step('rotate -> another relaunch, in case dark mode did not recreate it')
        ed.dev.rotate(True)
        ed.idle(5)
    finally:
        ed.dev.setprop(_7200d24e_HOOK, '0')
        ed.dev.restore_env()


@scenario('nightshift', 'auto')
def ns_7200d24e_l5_1_c(ed, r):
    """All 6, fresh launch path: from My Projects the user opens a draft -> new PlayerActivity, no saved state."""
    ed.leave_editor()
    ed.idle(2)
    ed.dev.setprop(_7200d24e_HOOK, '1')
    try:
        ed.step('open draft -> fresh PlayerActivity launch')
        ed.open_draft()
        ed.idle(5)
    finally:
        ed.dev.setprop(_7200d24e_HOOK, '0')


# 2026-10-10 20:54 level 5 attempt 2
_7200d24e_HOOK = 'debug.zesty.hook.null_sticker_table'


def _7200d24e_open_base_editor(ed):
    """MainActivity -> REVAMP UI (btn_revamped_ui, seen on the lab MainActivity) -> BaseVideoEditorActivity.onCreate."""
    s = ed.screen()
    if s is None or not s.has(('id:btn_revamped_ui',)):
        ed.dev.force_stop()
        ed.dev.launch()                                   # launcher -> MainActivity (no CrashCatcher installed yet)
        ed.idle(4)
    ed.ui.tap('id:btn_revamped_ui', timeout=15)           # the trigger step: may raise UIError


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l5_2_a(ed, r):
    """All 6 (HRY-LX1T x4, OnePlus8Pro x2), fresh launch: the screen's onCreate loads stickers with table=null (hook)."""
    ed.step('fresh launch of BaseVideoEditorActivity with the null-table hook armed')
    ed.dev.setprop(_7200d24e_HOOK, '1')
    try:
        _7200d24e_open_base_editor(ed)
        ed.idle(6)                                        # performLaunchActivity -> NPE 'parameter table' -> FATAL
    finally:
        ed.dev.setprop(_7200d24e_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_7200d24e_l5_2_b(ed, r):
    """All 6, process-death restore: screen open, HOME, am kill, back from launcher -> onCreate(saved) with table=null."""
    ed.dev.setprop(_7200d24e_HOOK, '0')
    ed.step('open BaseVideoEditorActivity normally (hook off)')
    _7200d24e_open_base_editor(ed)
    ed.idle(r.uniform(3, 5))
    try:
        ed.step('HOME, arm hook, am kill (keeps saved state), relaunch -> re-create from Bundle')
        ed.mon.allow_death = True
        ed.dev.key('KEYCODE_HOME')
        ed.idle(r.uniform(1, 3))
        ed.dev.setprop(_7200d24e_HOOK, '1')
        ed.dev.sh(f'am kill {PKG}')                       # not force-stop: the task keeps its saved state
        ed.idle(1)
        ed.mon.allow_death = False
        ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1')
        ed.idle(6)
    finally:
        ed.mon.allow_death = False
        ed.dev.setprop(_7200d24e_HOOK, '0')
