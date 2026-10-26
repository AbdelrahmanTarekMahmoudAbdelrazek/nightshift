# Night Shift auto repros for f7a4eff327f9009210c5164e8a1148d0


# 2026-10-26 11:36 level 2 attempt 1
def _f7a4eff3_relaunch_loop(ed, act_re, gap=5):
    """Field crash loop: cold launch into whatever the saved task/state is, then again 4-6 s later, nothing cleared."""
    for k in range(2):
        ed.step(f'cold relaunch {k + 1}/2 (field: OnePlus8Pro 08:08:12 -> 08:08:16)')
        mark = ed.log_mark()
        ed.mon.allow_death = True
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='a NEW process must start (cold launch)')
        ed.require_log(act_re, 15, since=mark, why='performLaunchActivity must run the restored/launch activity')
        ed.mon.allow_death = False
        ed.idle(gap)


@scenario('nightshift', 'auto')
def ns_f7a4eff3_l2_1_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5), saved-task path: sticker panel (Realm reader) open, process reclaimed, relaunch twice."""
    ed.set_playing(False)
    ed.main_nav()
    ed.menu_tap('sticker')                           # StickersFragmentPresenter -> getAllResources/getSearchTags(table)
    if not ed.ui.wait('id:stickers_recycler', timeout=15):
        raise UIError('sticker panel did not open: no Realm-backed screen in the saved state')
    ed.idle(r.uniform(2, 4))
    ed.kill_bg()                                     # saved Bundle (fragment args) kept by the system, process gone
    ed.idle(r.uniform(3, 8))
    _f7a4eff3_relaunch_loop(ed, r'wm_on_create_called: \[\d+,\d+,com\.video\.myzesty\.PlayerActivity')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_b(ed, r):
    """All 20 instances, CineMagic path: CineMagic (saves Bokeh/Overlay lists to Realm) left on top, process reclaimed, relaunch twice."""
    ed.dev.restore_env()
    ed.dev.launch()
    ed.idle(6)
    mark = ed.log_mark()
    ed.ui.tap('id:btn_cine_magic', timeout=15)
    ed.require_log(r'wm_on_create_called: \[\d+,\d+,com\.myzesty\.cinemagic\.ui\.activity\.CineMagicActivity', 15,
                   since=mark, why='CineMagic must be open so its Realm state is what the relaunch restores')
    ed.idle(r.uniform(5, 9))                         # Bokeh/Overlay lists downloaded and saved via saveDataToRealm
    ed.kill_bg()
    ed.idle(r.uniform(3, 8))
    _f7a4eff3_relaunch_loop(ed, r'wm_on_create_called: \[\d+,\d+,com\.myzesty\.')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_c(ed, r):
    """All 20 instances, plain-launcher path: Realm filled by a previous session, then offline cold launches from the icon, twice."""
    ed.dev.restore_env()
    ed.dev.launch()
    ed.idle(r.uniform(10, 15))                       # earlier session: DownloadAssetsWorker fills the Realm tables
    ed.dev.force_stop()
    ed.dev.clear_app_cache()                         # cached content gone, Realm file (files/) kept
    ed.dev.network(False)                            # relaunch cannot refresh: launch code works from stored state only
    try:
        ed.idle(2)
        _f7a4eff3_relaunch_loop(ed, r'wm_on_create_called: \[\d+,\d+,com\.myzesty\.', gap=r.uniform(4, 6))
    finally:
        ed.dev.network(True)


# 2026-10-26 11:42 level 2 attempt 2
_F7A4_NEW_ACT = r'wm_on_create_called: \[\d+,com\.(?!myzesty\.MainActivity)[\w.]+'


def _f7a4eff3_home(ed):
    """Checkpoint 1 (shipped build on Android 11), then a real cold start onto the shipped home screen."""
    ed.dev.restore_env()
    vc = ed.dev.sh('dumpsys package com.myzesty | grep versionCode')
    if '800054890' not in vc or ed.dev.getprop('ro.build.version.sdk').strip() != '30':
        raise UIError(f'field needs Play build 800054890 on Android 11; phone has {vc.strip()[:60]} sdk '
                      f'{ed.dev.getprop("ro.build.version.sdk").strip()}')
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='cold start of the shipped launcher')
    for _ in range(8):
        s = ed.screen()
        if s is not None and s.has(('id:home_cta_image', 'id:home_cta_video')):
            return
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    raise UIError('shipped home screen (home_cta_image) never showed')


def _f7a4eff3_open_kill_relaunch(ed, r, sel, why):
    """Open a Realm-backed screen like the user, process reclaimed, then field crash loop: relaunch twice 4-6 s apart."""
    mark = ed.log_mark()
    ed.ui.tap(sel, timeout=15)
    ed.require_log(_F7A4_NEW_ACT, 20, since=mark, why=why)
    ed.idle(r.uniform(6, 10))                        # resources/tags load and are written to Realm
    ed.kill_bg()                                     # task + saved Bundle kept, process gone (checkpoint 2)
    ed.idle(r.uniform(3, 8))
    for k in range(2):
        ed.step(f'cold relaunch {k + 1}/2 into the restored task (field: 08:08:12 -> 08:08:16)')
        mark = ed.log_mark()
        ed.mon.allow_death = True
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='a NEW process must start (cold launch)')
        ed.mon.allow_death = False
        ed.idle(r.uniform(4, 6))                     # NPE in performLaunchActivity lands here
        ed.kill_bg()
        ed.idle(1)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5), Image Editor path: photo editor (getAllImageEditorResources) restored on relaunch."""
    _f7a4eff3_home(ed)
    _f7a4eff3_open_kill_relaunch(ed, r, ('id:home_cta_image', 'text:Image Editor'),
                                 'Image Editor screen must be created (Realm-backed resources)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_b(ed, r):
    """All 20 instances, template path: a home template card opened, process reclaimed, relaunched twice."""
    _f7a4eff3_home(ed)
    _f7a4eff3_open_kill_relaunch(ed, r, ('id:thumbnailCard', 'id:row_cards'),
                                 'template screen must be created from the home row')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_c(ed, r):
    """All 20 instances, AI Studio path: AI Studio card opened, process reclaimed, relaunched twice."""
    _f7a4eff3_home(ed)
    _f7a4eff3_open_kill_relaunch(ed, r, ('id:home_ai_studio_card', 'id:ai_card_image', 'text:Ads Creator'),
                                 'AI Studio screen must be created from the home card')


# 2026-10-26 11:45 level 2 attempt 3
_F7A4_FATAL = r'NullPointerException.*parameter table|FATAL EXCEPTION: main'


def _f7a4eff3_gate(ed):
    """Checkpoint 1: the shipped Play build 800054890 on an Android 11 phone; anything else cannot reach this launch path."""
    ed.dev.restore_env()
    vc = ed.dev.sh('dumpsys package com.myzesty | grep -m1 versionCode')
    sdk = ed.dev.getprop('ro.build.version.sdk').strip()
    if '800054890' not in vc or sdk != '30':
        raise UIError(f'field needs Play build 800054890 on API 30; phone has [{vc.strip()[:50]}] sdk {sdk}')


def _f7a4eff3_cold(ed, why):
    """Our OWN cold start: the watch is armed before force-stop + launch, so 'Start proc' cannot be used up by the runner."""
    mark = ed.log_mark()
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why=why)
    return mark


def _f7a4eff3_loop(ed, r):
    """Checkpoints 3-5: cold launch, then a relaunch 4-6 s later with nothing cleared (OnePlus8Pro 08:08:12 -> 08:08:16)."""
    for k in range(2):
        ed.step(f'cold relaunch {k + 1}/2, state untouched')
        mark = ed.log_mark()
        ed.mon.allow_death = True
        ed.dev.launch()                              # process is dead: performLaunchActivity of the task's top activity
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='relaunch must be a NEW process')
        ed.mon.allow_death = False
        ed.idle(r.uniform(4, 6))
        ed.dev.sh('am kill com.myzesty')             # system reclaims it like after the field crash; task kept
        ed.idle(1)


def _f7a4eff3_home(ed):
    for _ in range(10):
        s = ed.screen()
        if s is not None and s.has(('id:home_cta_video', 'id:home_cta_image')):
            return s
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    raise UIError('shipped home screen (home_cta_video) never showed')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5), icon path: a full earlier session fills prefs/Realm, then icon cold launches."""
    _f7a4eff3_gate(ed)
    _f7a4eff3_cold(ed, 'earlier session: cold start of the shipped launcher')
    _f7a4eff3_home(ed)
    ed.idle(r.uniform(15, 25))                       # assets/templates download and are saved (persisted state, checkpoint 2)
    ed.dev.key('KEYCODE_HOME')
    ed.idle(2)
    _f7a4eff3_cold(ed, 'icon cold launch 1 (field T0)')
    ed.mon.allow_death = False
    ed.idle(r.uniform(4, 6))
    ed.dev.sh('am kill com.myzesty')
    _f7a4eff3_loop(ed, r)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_b(ed, r):
    """All 20 instances, restored-task path: Full Video Editor left open, process reclaimed, relaunch restores it twice."""
    _f7a4eff3_gate(ed)
    _f7a4eff3_cold(ed, 'cold start of the shipped launcher')
    s = _f7a4eff3_home(ed)
    ed.mon.allow_death = False
    mark = ed.log_mark()
    ed.dev.tap(*s.find(('id:home_cta_video', 'text:Full Video Editor')).center)
    ed.require_log(r'wm_on_create_called: \[\d+,[\w.]+(?<!MainActivity),', 20, since=mark,
                   why='a second activity must be on top so the relaunch restores it (saved Bundle = checkpoint 2)')
    ed.idle(r.uniform(5, 9))
    ed.kill_bg()                                     # Home + process reclaimed, task with saved state kept
    ed.idle(r.uniform(3, 8))
    _f7a4eff3_loop(ed, r)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_c(ed, r):
    """All 20 instances, notification path: a push arrives while the app is dead, the user taps it (launch with extras)."""
    _f7a4eff3_gate(ed)
    _f7a4eff3_cold(ed, 'earlier session: cold start of the shipped launcher')
    _f7a4eff3_home(ed)
    ed.idle(r.uniform(8, 12))
    ed.kill_bg()
    res = ed.dev.fcm_push(title='MyZesty', body='New templates are here', data={'type': 'template'}, wait=True)
    if 'REFUSED' in res:
        raise UIError(f'release build refuses lab pushes: {res}')
    ed.idle(3)
    ed.dev.sh('cmd statusbar expand-notifications')
    ed.idle(1.5)
    mark = ed.log_mark()
    ed.mon.allow_death = True
    ed.ui.tap('text:New templates are here', timeout=10)
    ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='notification tap must cold-start the app')
    ed.mon.allow_death = False
    ed.idle(r.uniform(4, 6))
    ed.dev.sh('am kill com.myzesty')
    _f7a4eff3_loop(ed, r)


# 2026-10-26 11:49 level 3 attempt 1
def _f7a4eff3_shipped(ed):
    """Checkpoint 1: Play build 800054890 on Android 11, else this run cannot count."""
    ed.dev.restore_env()
    vc, sdk = ed.dev.sh('dumpsys package com.myzesty | grep versionCode'), ed.dev.getprop('ro.build.version.sdk').strip()
    if '800054890' not in vc or sdk != '30':
        raise UIError(f'field needs Play build 800054890 on Android 11; phone has {vc.strip()[:60]} sdk {sdk}')


def _f7a4eff3_session(ed, r, settle=(8, 12)):
    """Earlier session on the shipped home (checkpoint 2): the app stores prefs/Realm data that survive a restart."""
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='earlier session must be a real cold start')
    if not ed.ui.wait('id:home_cta_image', timeout=20):
        raise UIError('shipped home screen (home_cta_image) never showed')
    ed.idle(r.uniform(*settle))                      # home templates/resources fetched and written to Realm


def _f7a4eff3_crash_loop(ed, r, kill=True):
    """Checkpoints 3-5: cold launch (new process, performLaunchActivity), then again 4-6 s later, nothing cleared."""
    for k in range(2):
        ed.step(f'cold launch {k + 1}/2 from stored state (field: OnePlus8Pro 08:08:12 -> 08:08:16)')
        ed.mon.allow_death = True
        if kill:
            ed.dev.force_stop()                      # a resume of a live process is not the field launch
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='a NEW process must start (cold launch)')
        ed.require_log(r'wm_on_create_called: \[\d+,com\.myzesty', 15, since=mark,
                       why='performLaunchActivity must run the launch activity')
        ed.mon.allow_death = False
        ed.idle(r.uniform(4, 6))                     # NPE in y4.d.d lands < 1 s after Start proc
        kill = True


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5), offline path: stored session, cache cleared, offline cold launches twice."""
    _f7a4eff3_shipped(ed)
    _f7a4eff3_session(ed, r)
    ed.dev.force_stop()
    ed.dev.clear_app_cache()                         # Realm file + prefs (files/, shared_prefs/) kept
    ed.dev.network(False)                            # launch code can only use stored state, no refresh
    try:
        _f7a4eff3_crash_loop(ed, r)
    finally:
        ed.dev.network(True)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_b(ed, r):
    """All 20 instances, reclaimed-task path: Image Editor open, memory pressure, system reclaims process, task restored twice."""
    _f7a4eff3_shipped(ed)
    _f7a4eff3_session(ed, r, settle=(4, 6))
    mark = ed.log_mark()
    ed.ui.tap('id:home_cta_image', timeout=10)
    ed.require_log(r'wm_on_create_called: \[\d+,com\.(?!myzesty\.MainActivity)', 20, since=mark,
                   why='a Realm-backed screen must be on top so the relaunch restores it from the saved Bundle')
    ed.idle(r.uniform(5, 8))
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.idle(1)
    ed.kill_bg()                                     # saved state kept, process gone: next launch restores the task
    ed.idle(r.uniform(3, 6))
    _f7a4eff3_crash_loop(ed, r, kill=False)          # first launch must restore the task, not force-stop it


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_c(ed, r):
    """All 20 instances, half-written state path: slow network, process killed mid-download, offline cold launches twice."""
    _f7a4eff3_shipped(ed)
    ed.dev.force_stop()
    ed.dev.clear_app_cache()
    ed.dev.slow_network(30)                          # resource/template lists arrive partially on first launch
    try:
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='session that writes partial state')
        ed.idle(r.uniform(3, 7))
        ed.dev.force_stop()                          # dies mid-download: prefs/Realm left half-written
        ed.dev.network(False)
        _f7a4eff3_crash_loop(ed, r)
    finally:
        ed.dev.restore_env()


# 2026-10-26 11:51 level 3 attempt 2
_F7A4_START = r'START u0 .*cmp=com\.myzesty/(?!\.MainActivity\b|com\.myzesty\.MainActivity\b)'


def _f7a4eff3_shipped(ed):
    """Checkpoint 1: Play build 800054890 on Android 11, and its launcher is NOT the developer menu (.MainActivity)."""
    ed.dev.restore_env()
    vc = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName"')
    sdk = ed.dev.getprop('ro.build.version.sdk').strip()
    act = ed.dev.sh('cmd package resolve-activity --brief -c android.intent.category.LAUNCHER com.myzesty').strip()
    act = act.splitlines()[-1] if act else ''
    if '800054890' not in vc or sdk != '30' or act.endswith('.MainActivity') and 'com.myzesty.MainActivity' in act:
        raise UIError(f'SETUP: field needs Play 1.25.2 (800054890) with the shipped launcher on Android 11; '
                      f'phone has [{" ".join(vc.split())[:90]}] sdk={sdk} launcher={act}. Install the Play internal-test '
                      f'build in place (install -r over older data), not the CPP-1.25.2 debug APK')
    return act


def _f7a4eff3_cold(ed, why):
    """Checkpoint 3: real cold start via the launcher intent, new process, shipped launch Activity created."""
    ed.mon.allow_death = True
    ed.dev.force_stop()                              # a resume of a live process is not the field launch
    mark = ed.log_mark()
    ed.dev.sh('monkey -p com.myzesty -c android.intent.category.LAUNCHER 1')
    ed.require_log(_F7A4_START, 10, since=mark, why='START must name the shipped launch Activity: ' + why)
    ed.require_log(r'Start proc \d+:com\.myzesty/', 10, since=mark, why='a NEW process must start (cold launch)')
    ed.mon.allow_death = False
    return mark


def _f7a4eff3_session(ed, r, settle=(8, 12)):
    """Checkpoint 2: an earlier session on the shipped home writes prefs/Realm data that survive a restart."""
    _f7a4eff3_cold(ed, 'earlier session')
    if not ed.ui.wait('id:home_cta_image', timeout=25):
        raise UIError('shipped home screen (home_cta_image) never showed')
    ed.idle(r.uniform(*settle))                      # home templates/resources fetched and written to Realm


def _f7a4eff3_loop(ed, r):
    """Checkpoints 4-5: launch, NPE < 1 s after Start proc, relaunch 4-6 s later with nothing cleared."""
    for k in range(2):
        ed.step(f'cold launch {k + 1}/2 from stored state (field: OnePlus8Pro 08:08:12 -> 08:08:16)')
        _f7a4eff3_cold(ed, f'crash-loop launch {k + 1}')
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_2_a(ed, r):
    """All 20 instances (OnePlus8Pro x15, HRY-LX1T x5), offline path: stored session, cache cleared, offline cold launches."""
    _f7a4eff3_shipped(ed)
    _f7a4eff3_session(ed, r)
    ed.dev.force_stop()
    ed.dev.clear_app_cache()                         # Realm + shared_prefs kept, only cache/ gone
    ed.dev.network(False)                            # launch code can only use stored state
    try:
        _f7a4eff3_loop(ed, r)
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_2_b(ed, r):
    """All 20 instances, reclaimed-task path: Image Editor open, critical memory pressure, system reclaims, task restored."""
    _f7a4eff3_shipped(ed)
    _f7a4eff3_session(ed, r, settle=(4, 6))
    mark = ed.log_mark()
    ed.ui.tap('id:home_cta_image', timeout=10)
    ed.require_log(r'wm_on_create_called: \[\d+,com\.(?!myzesty\.MainActivity)', 20, since=mark,
                   why='a Realm-backed screen must be on top so the relaunch restores it from its saved Bundle')
    ed.idle(r.uniform(5, 8))
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.idle(1)
    ed.kill_bg()                                     # saved state kept, process gone
    ed.idle(r.uniform(3, 6))
    for k in range(2):                               # relaunch WITHOUT force-stop: performLaunchActivity restores the task
        ed.step(f'restore launch {k + 1}/2 (no force-stop)')
        mark = ed.log_mark()
        ed.mon.allow_death = True
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='a NEW process must start (cold launch)')
        ed.mon.allow_death = False
        ed.idle(r.uniform(4, 6))
        ed.kill_bg()
        ed.idle(1)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_2_c(ed, r):
    """All 20 instances, half-written state on a slow phone: first session killed mid-download, then cold launch loop."""
    _f7a4eff3_shipped(ed)
    ed.dev.clear_app_cache()
    ed.dev.slow_network(30)                          # resource/template lists arrive partially
    ed.dev.slow_phone(30)                            # OnePlus8Pro/HRY-LX1T-class timing on the first session
    try:
        _f7a4eff3_cold(ed, 'session that writes partial state')
        ed.idle(r.uniform(3, 7))
        ed.dev.force_stop()                          # dies mid-download: prefs/Realm half-written
        ed.dev.network(False)
        _f7a4eff3_loop(ed, r)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-10-26 11:56 level 3 attempt 3
_F7A4_HOME = 'id:home_cta_video'                     # shipped home (seen on MainActivity in the Play build), never on the dev menu


def _f7a4eff3_gate(ed):
    """Checkpoint 1: Play 1.25.2 (800054890) on Android 11 whose cold start shows the SHIPPED home, not the dev menu."""
    ed.dev.restore_env()
    pk = ' '.join(ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName"').split())
    sdk = ed.dev.getprop('ro.build.version.sdk').strip()
    if '800054890' not in pk or sdk != '30' or 'com.android.vending' not in pk:
        raise UIError(f'SETUP: needs Play-installed 1.25.2 (800054890) on Android 11; phone: [{pk[:120]}] sdk={sdk}')
    _f7a4eff3_cold(ed, 'gate')
    if not ed.ui.wait(_F7A4_HOME, timeout=25):
        raise UIError('SETUP: cold start shows the CPP-1.25.2 developer menu, not the shipped home: install the Play '
                      'internal-test 1.25.2 in place (install -r over older data) before running this recipe')


def _f7a4eff3_cold(ed, why, kill=True):
    """Checkpoint 3: a NEW process runs performLaunchActivity of the launch Activity (NPE lands < 1 s after Start proc)."""
    ed.mon.allow_death = True
    if kill:
        ed.dev.force_stop()                          # a resume of a live process is not the field launch
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='a NEW process must start: ' + why)
    ed.require_log(r'wm_on_create_called: \[\d+,com\.myzesty', 15, since=mark, why='performLaunchActivity: ' + why)
    ed.mon.allow_death = False


def _f7a4eff3_loop(ed, r, kill=True):
    """Checkpoints 4-5: launch, then relaunch 4-6 s later with nothing cleared (OnePlus8Pro 08:08:12 -> 08:08:16)."""
    for k in range(3):
        ed.step(f'cold launch {k + 1}/3 from stored state')
        _f7a4eff3_cold(ed, f'crash-loop launch {k + 1}', kill=kill or k > 0)
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_3_a(ed, r):
    """OnePlus8Pro x15 + HRY-LX1T x5: user session writes prefs/Realm (home, Full Video Editor), then offline cold-launch loop."""
    _f7a4eff3_gate(ed)
    ed.ui.tap(_F7A4_HOME, timeout=10)                # editor entry stores its last-used state
    ed.idle(r.uniform(6, 9))
    ed.dev.key('KEYCODE_BACK')
    ed.idle(2)
    ed.dev.force_stop()
    ed.dev.clear_app_cache()                         # cache/ gone, shared_prefs + Realm kept (state that survives restart)
    ed.dev.network(False)                            # launch can only use stored state
    try:
        _f7a4eff3_loop(ed, r)
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_3_b(ed, r):
    """OnePlus8Pro x15 + HRY-LX1T x5, push path: app reclaimed, an FCM push cold-starts the process, user opens app twice."""
    _f7a4eff3_gate(ed)
    ed.idle(r.uniform(5, 8))
    ed.kill_bg()
    ed.idle(2)
    res = ed.dev.fcm_push('New templates are here', 'Tap to try them', data={'type': 'template'}, wait=False)
    ed.log(f'    push: {res}')
    ed.idle(r.uniform(3, 5))                         # receiver writes its payload into prefs/Realm in the bg process
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.kill_bg()
    _f7a4eff3_loop(ed, r, kill=False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_3_c(ed, r):
    """OnePlus8Pro x15 + HRY-LX1T x5, task-restore path: editor on top, dark mode change, process reclaimed, relaunch restores task."""
    _f7a4eff3_gate(ed)
    ed.ui.tap(_F7A4_HOME, timeout=10)
    ed.idle(r.uniform(5, 8))
    ed.dev.dark_mode(True)                           # config change: saved Bundle rewritten with the new instance state
    ed.idle(3)
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.kill_bg()                                     # saved task kept, process gone
    ed.dev.slow_phone(30)                            # low-end launch timing, set right before the trigger
    try:
        _f7a4eff3_loop(ed, r, kill=False)            # first launch restores the task (no force-stop)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-10-26 11:59 level 4 attempt 1
_F7A4_PROC = r'Start proc \d+:com\.myzesty/'
_F7A4_CREATE = r'wm_on_create_called: \[\d+,com\.myzesty[./]'   # this phone prints the class with a dot


def _f7a4eff3_shipped(ed):
    """Checkpoint 1: the Play-installed 1.25.2 (800054890) on Android 11, not the CPP-1.25.2 developer APK."""
    ed.dev.restore_env()
    pk = ' '.join(ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName"').split())
    sdk = ed.dev.getprop('ro.build.version.sdk').strip()
    if 'versionCode=800054890' not in pk or 'com.android.vending' not in pk or sdk != '30':
        raise UIError(f'SETUP: field needs Play-installed 1.25.2 (800054890) on Android 11 (sdk 30); phone has '
                      f'[{pk[:120]}] sdk={sdk}. Install it from the Play internal-test track over older data')


def _f7a4eff3_cold(ed, why, kill=True):
    """Checkpoint 3: new process + performLaunchActivity of the launcher activity (death allowed: that IS the crash)."""
    ed.mon.allow_death = True
    if kill:
        ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.sh('monkey -p com.myzesty -c android.intent.category.LAUNCHER 1')
    ed.require_log(_F7A4_PROC, 10, since=mark, why='a NEW process must start: ' + why)
    ed.require_log(_F7A4_CREATE, 10, since=mark, why='performLaunchActivity must run: ' + why)
    ed.mon.allow_death = False
    return mark


def _f7a4eff3_session(ed, r, settle=(8, 12)):
    """Checkpoint 2: an earlier session on the shipped home stores prefs/Realm data that survive a restart."""
    _f7a4eff3_cold(ed, 'earlier session')
    if not ed.ui.wait('id:home_cta_image', timeout=25):
        raise UIError('shipped home screen (home_cta_image) never showed: not the Play build home')
    ed.idle(r.uniform(*settle))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_1_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5), crash-loop storm: stored session, then 6 cold launches 4-6 s apart."""
    _f7a4eff3_shipped(ed)
    _f7a4eff3_session(ed, r)
    for k in range(6):                               # field gaps: 08:08:12 -> 08:08:16, 07:17:33 -> 07:17:37
        ed.step(f'cold launch {k + 1}/6 from stored state')
        _f7a4eff3_cold(ed, f'storm launch {k + 1}')
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_1_b(ed, r):
    """All 20, torn-write path: slow phone, process killed 0.8-3 s into startup (prefs/Realm write window), relaunched at once."""
    _f7a4eff3_shipped(ed)
    _f7a4eff3_session(ed, r, settle=(4, 6))
    try:
        for k in range(5):
            ed.step(f'kill inside startup write window {k + 1}/5')
            ed.dev.slow_phone(r.randint(30, 45))     # OnePlus8Pro/HRY-LX1T-class launch timing
            _f7a4eff3_cold(ed, f'interrupted startup {k + 1}')
            ed.idle(r.uniform(0.8, 3.0))
            ed.dev.slow_phone(0)
            _f7a4eff3_cold(ed, f'relaunch on half-written state {k + 1}')   # force-stop then relaunch < 0.5 s
            ed.idle(r.uniform(4, 6))
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_1_c(ed, r):
    """All 20, restored-task path: Image Editor on top, system reclaims the process, task restored 4x at 4-6 s gaps."""
    _f7a4eff3_shipped(ed)
    _f7a4eff3_session(ed, r, settle=(4, 6))
    mark = ed.log_mark()
    ed.ui.tap('id:home_cta_image', timeout=10)
    ed.require_log(r'wm_on_create_called: \[\d+,com\.(?!myzesty\.MainActivity)', 20, since=mark,
                   why='a second screen must be on top so the relaunch restores it from its saved Bundle')
    ed.idle(r.uniform(3, 6))
    for k in range(4):
        ed.step(f'reclaim + restore launch {k + 1}/4 (no force-stop)')
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.kill_bg()                                 # saved instance state kept, process gone
        ed.idle(r.uniform(0.5, 2))
        _f7a4eff3_cold(ed, f'task restore {k + 1}', kill=False)
        ed.idle(r.uniform(4, 6))


# 2026-10-26 12:05 level 4 attempt 2
_F7A4_PROC = r'Start proc \d+:com\.myzesty/'
_F7A4_SUB = r'START u0 .*cmp=com\.myzesty/(?!\.MainActivity\b)'
_F7A4_RESTORED = r'Start proc \d+:com\.myzesty/\S+ for (pre-)?top-activity \{com\.myzesty/(?!com\.myzesty\.MainActivity\b|\.MainActivity\b)'
_F7A4_END = r'Displayed com\.myzesty/|Process com\.myzesty \(pid \d+\) has died|FATAL EXCEPTION'


def _f7a4eff3_home(ed):
    """Checkpoints 1-2: the Play 1.25.2 home (home_cta_image) in a new process. Its session writes Realm/prefs."""
    ed.dev.restore_env()
    ed.mon.allow_death = True
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(_F7A4_PROC, 15, since=mark, why='a new process must start')
    ed.mon.allow_death = False
    if not ed.ui.wait('id:home_cta_image', timeout=25):
        raise UIError('shipped home (home_cta_image "Image Editor") never showed: not the Play 1.25.2 build')
    ed.idle(r_idle := 6)


def _f7a4eff3_image_editor(ed, r, pick=True):
    """Home -> Image Editor -> (pick the newest image): the Realm-backed photo screens open on top of MainActivity."""
    mark = ed.log_mark()
    ed.ui.tap('id:home_cta_image', timeout=10)
    ed.require_log(_F7A4_SUB, 15, since=mark, why='Image Editor must start a screen above the home')
    ed.idle(r.uniform(2, 4))
    if pick:
        ed.ui.tap('id:image_tab', timeout=5)
        w, h = ed._screen_size()
        mark = ed.log_mark()
        ed.dev.tap(int(w * 0.17), int(h * 0.33))     # first (newest) image in the grid
        ed.wait_log(_F7A4_SUB, 10, since=mark)
        ed.idle(r.uniform(4, 7))                     # editor resources read from Realm


def _f7a4eff3_reclaim_loop(ed, r, n):
    """Checkpoints 3-5: the process is reclaimed with the task kept; the launcher tap restores the photo screen in a new
    process (performLaunchActivity, no prior home), then relaunches follow 4-6 s apart like OnePlus8Pro 08:08:12 -> :16."""
    ed.kill_bg()
    ed.idle(r.uniform(0.5, 2))
    for k in range(n):
        ed.step(f'restore launch {k + 1}/{n} (task kept, new process)')
        ed.mon.allow_death = True
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(_F7A4_PROC, 15, since=mark, why='launch must start a NEW process')
        if k == 0:
            ed.require_log(_F7A4_RESTORED, 5, since=mark,
                           why='the restored top activity must be the photo screen, not the home MainActivity')
        ed.require_log(_F7A4_END, 15, since=mark, why='the launch must finish (Displayed) or die')
        ed.mon.allow_death = False
        ed.idle(r.uniform(4, 6))
        ed.kill_bg()
        ed.idle(r.uniform(0.3, 1.5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_2_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5): photo editor open on an image, process reclaimed, 4 task restores 4-6 s apart."""
    _f7a4eff3_home(ed)
    _f7a4eff3_image_editor(ed, r, pick=True)
    _f7a4eff3_reclaim_loop(ed, r, 4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_2_b(ed, r):
    """All 20: Image Editor picker (before an image is chosen) reclaimed, then restored at once on a slow phone, 4x."""
    _f7a4eff3_home(ed)
    _f7a4eff3_image_editor(ed, r, pick=False)
    ed.dev.slow_phone(r.randint(30, 45))             # OnePlus8Pro/HRY-LX1T-class launch timing
    try:
        _f7a4eff3_reclaim_loop(ed, r, 4)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_2_c(ed, r):
    """All 20: photo editor rotated (saved-state round trip), critical trim, reclaimed within 1 s, restored 4x."""
    _f7a4eff3_home(ed)
    _f7a4eff3_image_editor(ed, r, pick=True)
    ed.dev.rotate(True)
    ed.idle(r.uniform(1, 2))
    ed.dev.rotate(False)
    ed.idle(r.uniform(0.5, 1.5))
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    try:
        _f7a4eff3_reclaim_loop(ed, r, 4)
    finally:
        ed.dev.restore_env()


# 2026-10-26 12:08 level 4 attempt 3
_F7A4_PROC = r'Start proc \d+:com\.myzesty/'
_F7A4_END = r'Displayed com\.myzesty/|Process com\.myzesty \(pid \d+\) has died|FATAL EXCEPTION'


def _f7a4eff3_gate(ed):
    """Checkpoint 1, checked before any app step: the launcher must be the shipped launch Activity of 1.25.2 on Android 11."""
    ed.dev.restore_env()
    comp = ed.dev.sh('cmd package resolve-activity --brief -a android.intent.action.MAIN '
                     '-c android.intent.category.LAUNCHER com.myzesty').split()
    comp = comp[-1] if comp else ''
    pk = ' '.join(ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName"').split())
    sdk = ed.dev.getprop('ro.build.version.sdk').strip()
    if comp.endswith('/.MainActivity') or comp.endswith('/com.myzesty.MainActivity') or 'versionCode=800054890' not in pk \
            or sdk != '30':
        raise UIError(f'SETUP (not a repro attempt): launcher={comp} [{pk[:100]}] sdk={sdk}. Needs the Play 1.25.2 '
                      f'(800054890) install upgraded in place over older-build data on an Android 11 phone; the '
                      f'CPP-1.25.2 developer MainActivity never reaches RealmWrapper')
    return comp


def _f7a4eff3_launch(ed, why, kill=True):
    """Checkpoints 3-5: a new process runs performLaunchActivity; it either shows a screen or dies (the field crash)."""
    ed.mon.allow_death = True
    if kill:
        ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(_F7A4_PROC, 15, since=mark, why='a NEW process must start: ' + why)
    ed.require_log(_F7A4_END, 15, since=mark, why='the launch must finish or die: ' + why)
    ed.mon.allow_death = False


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_3_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5), crash-loop path: launch on stored state, then 6 relaunches 4-6 s apart."""
    _f7a4eff3_gate(ed)
    _f7a4eff3_launch(ed, 'first launch on upgraded data')
    ed.idle(r.uniform(6, 10))                         # let a surviving session write prefs/Realm
    for k in range(6):                                # field gaps: 08:08:12 -> :16, 07:17:33 -> :37
        ed.step(f'relaunch {k + 1}/6')
        _f7a4eff3_launch(ed, f'relaunch {k + 1}')
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_3_b(ed, r):
    """All 20, saved-task path: Image Editor on top, process reclaimed, task restored on a slow phone 4x at 4-6 s gaps."""
    _f7a4eff3_gate(ed)
    _f7a4eff3_launch(ed, 'home session')
    if not ed.ui.wait('id:home_cta_image', timeout=25):
        raise UIError('shipped home (home_cta_image) never showed')
    ed.ui.tap('id:home_cta_image', timeout=10)
    ed.idle(r.uniform(3, 5))
    try:
        for k in range(4):
            ed.step(f'reclaim + restore {k + 1}/4')
            ed.kill_bg()                              # saved instance state kept, process gone
            ed.dev.slow_phone(r.randint(30, 45))      # low-end launch timing
            _f7a4eff3_launch(ed, f'task restore {k + 1}', kill=False)
            ed.dev.slow_phone(0)
            ed.idle(r.uniform(4, 6))
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l4_3_c(ed, r):
    """All 20, push cold-start path: app reclaimed, pushes with empty/missing category fields, then launcher taps."""
    _f7a4eff3_gate(ed)
    _f7a4eff3_launch(ed, 'home session')
    ed.idle(r.uniform(5, 8))
    for k, data in enumerate([{'type': 'stickers'}, {'type': 'template', 'category': ''}, {}]):
        ed.step(f'push cold start {k + 1}/3 data={data}')
        ed.kill_bg()
        ed.mon.allow_death = True
        mark = ed.log_mark()
        ed.dev.fcm_push('MyZesty', 'New stickers are here', data, foreground=False, wait=3)
        ed.wait_log(_F7A4_PROC, 10, since=mark)       # the receiver may or may not start the process
        ed.mon.allow_death = False
        _f7a4eff3_launch(ed, f'launch after push {k + 1}', kill=False)
        ed.idle(r.uniform(4, 6))


# 2026-10-26 12:12 level 5 attempt 1
_F7A4_PROC = r'Start proc \d+:com\.myzesty/'
_F7A4_HOOK = r'ZHOOK.*null_table: launch passes table=null'


def _f7a4eff3_prep(ed):
    """Field phones are Android 11; the earlier runs left the notification shade over the app, so close it first."""
    ed.dev.restore_env()
    ed.dev.sh('cmd statusbar collapse')
    sdk = ed.dev.getprop('ro.build.version.sdk').strip()
    if sdk != '30':
        raise UIError(f'SETUP: the field crash is Android 11 only (sdk 30); this phone has sdk={sdk}')


def _f7a4eff3_launch(ed, why, kill=True):
    """Checkpoints 3-4: a new process, performLaunchActivity of the launcher, the hook passes table=null to RealmWrapper."""
    if kill:
        ed.mon.allow_death = True
        ed.dev.force_stop()
        ed.mon.allow_death = False
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(_F7A4_PROC, 15, since=mark, why='a NEW process must start: ' + why)
    ed.require_log(_F7A4_HOOK, 10, since=mark,
                   why='the launch must read the missing stored table (needs the build with debug.zesty.hook.null_table): ' + why)
    ed.idle(2)                                       # the NPE is thrown on the next line of onCreate


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l5_1_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5), cold-launch crash loop: stored table missing, launcher relaunched 4-6 s apart."""
    _f7a4eff3_prep(ed)
    ed.dev.setprop('debug.zesty.hook.null_table', '1')   # the persisted state: survives every relaunch until cleared
    try:
        for k in range(3):                           # field gaps: 08:08:12 -> :16, 07:17:33 -> :37, 09:51:23 -> :29
            ed.step(f'cold launch {k + 1}/3 on the stored state')
            _f7a4eff3_launch(ed, f'launch {k + 1}')
            ed.idle(r.uniform(4, 6))
    finally:
        ed.dev.setprop('debug.zesty.hook.null_table', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l5_1_b(ed, r):
    """All 20, restored-task path: a clean session, the system reclaims the app, then the relaunch restores the launch Activity on a slow phone."""
    _f7a4eff3_prep(ed)
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    ed.dev.launch()                                  # earlier session, hook off: launches normally
    ed.require_log(r'Displayed com\.myzesty/', 15, why='the earlier session must reach a screen')
    ed.idle(r.uniform(4, 8))
    ed.kill_bg()                                     # process gone, task and saved state kept
    ed.dev.setprop('debug.zesty.hook.null_table', '1')
    try:
        ed.dev.slow_phone(r.randint(30, 45))         # HRY-LX1T-class launch timing
        ed.step('relaunch restores the task in a new process')
        _f7a4eff3_launch(ed, 'task restore', kill=False)
        ed.dev.slow_phone(0)
        ed.idle(r.uniform(4, 6))
        _f7a4eff3_launch(ed, 'relaunch after the crash')
    finally:
        ed.dev.slow_phone(0)
        ed.dev.setprop('debug.zesty.hook.null_table', '0')


# 2026-10-26 12:17 level 5 attempt 3
_F7A4_PROC = r'Start proc \d+:com\.myzesty/'


def _f7a4eff3_gate(ed):
    """Checkpoint 1: Play 1.25.2 (800054890) on Android 11; it also launches through .MainActivity (lab fact)."""
    ed.dev.restore_env()
    ed.dev.sh('cmd statusbar collapse')
    pk = ' '.join(ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName"').split())
    sdk = ed.dev.getprop('ro.build.version.sdk').strip()
    if 'versionCode=800054890' not in pk or 'com.android.vending' not in pk or sdk != '30':
        raise UIError(f'SETUP: needs Play 1.25.2 (800054890) on Android 11; got [{pk[:100]}] sdk={sdk}')


def _f7a4eff3_launch(ed, why, kill=True):
    """Checkpoints 3-4: a NEW process runs performLaunchActivity (task restore or launcher)."""
    ed.mon.allow_death = True
    if kill:
        ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(_F7A4_PROC, 15, since=mark, why='a NEW process must start: ' + why)
    ed.mon.allow_death = False
    ed.idle(2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l5_3_a(ed, r):
    """All 20 (OnePlus8Pro x15, HRY-LX1T x5), notification path: tap a stale push with no table/category, cold, 3x 4-6 s apart."""
    _f7a4eff3_gate(ed)
    for k, data in enumerate([{'type': 'stickers'}, {'type': 'template', 'category': ''}, {'deeplink': 'myzesty://stickers'}]):
        ed.step(f'push cold start {k + 1}/3 data={data}')
        ed.kill_bg()
        title = f'NS table {k}'
        ed.dev.fcm_push(title, 'New stickers are here', data, foreground=False, wait=3)
        ed.dev.sh('cmd statusbar expand-notifications')
        ed.idle(1)
        ed.mon.allow_death = True
        mark = ed.log_mark()
        ed.ui.tap(f'textc:{title}', timeout=8)      # the trigger: Android starts the push Activity in a new process
        ed.require_log(_F7A4_PROC, 15, since=mark, why='the notification tap must cold-start the app')
        ed.mon.allow_death = False
        ed.idle(r.uniform(4, 6))                    # field relaunch gap 4-6 s


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l5_3_b(ed, r):
    """All 20, restored-task path: Image Editor (Realm-backed resources) on top, process reclaimed, launcher restores it 3x."""
    _f7a4eff3_gate(ed)
    _f7a4eff3_launch(ed, 'home session')
    ed.ui.tap('id:home_cta_image', timeout=20)      # Image Editor: reads DynamicResource tables from Realm
    ed.idle(r.uniform(3, 5))
    ed.ui.tap('id:stickerTv', timeout=5)            # decorative: let it store a sticker table/category
    ed.idle(r.uniform(2, 4))
    for k in range(3):
        ed.step(f'reclaim + restore {k + 1}/3')
        ed.kill_bg()                                # saved instance state kept, process gone
        _f7a4eff3_launch(ed, f'task restore {k + 1}', kill=False)
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l5_3_c(ed, r):
    """All 20, stored-prefs crash loop: hook forces the null table on launch (debug builds), then 3 cold launches 4-6 s apart."""
    _f7a4eff3_gate(ed)
    ed.dev.setprop('debug.zesty.hook.null_table', '1')   # absent from the Play build: there it is a plain launch loop
    try:
        for k in range(3):                          # field gaps 08:08:12 -> :16, 07:17:33 -> :37
            ed.step(f'cold launch {k + 1}/3')
            _f7a4eff3_launch(ed, f'launch {k + 1}')
            ed.idle(r.uniform(4, 6))
    finally:
        ed.dev.setprop('debug.zesty.hook.null_table', '0')
