# Night Shift auto repros for f7a4eff327f9009210c5164e8a1148d0


# 2026-10-29 13:09 level 2 attempt 1
_F7A4_RES = 'com.myzesty/com.photo.myzesty.ui.activity.resource.ResourceActivity'
_F7A4_RES_RE = r'com\.myzesty[./].*ResourceActivity'


def _f7a4eff3_home(ed):
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Displayed com\.myzesty/', 20, since=mark, why='app in foreground with Realm up (20/20 field events)')
    ed.idle(3)


def _f7a4eff3_more_then_restore(ed, r, tool):
    """Open a photo tool (frames/poster), tap its 'more' button -> ResourceActivity, then process death + restore."""
    _f7a4eff3_home(ed)
    ed.ui.tap('textc:all tools', timeout=5)          # decorative: the tool may already sit on the home grid
    ed.idle(1.5)
    ed.ui.tap(f'textc:{tool}', timeout=10)           # trigger path: raises UIError if the tile is missing
    ed.idle(r.uniform(2, 4))
    mark = ed.log_mark()
    ed.ui.tap('id:more', timeout=10)
    ed.require_log(_F7A4_RES_RE, 15, since=mark, why='ResourceActivity opened from the real more button')
    ed.ui.wait('id:resource_list', timeout=10)
    ed.idle(r.uniform(2, 5))
    ed.kill_bg()                                     # system reclaims the cached app, task + Bundle kept
    ed.idle(r.uniform(3, 6))
    mark = ed.log_mark()
    ed.restore_from_recents(wait=6)                  # performLaunchActivity of ResourceActivity in a new process
    ed.require_log(r'wm_restart_activity|wm_on_create_called.*ResourceActivity', 15, since=mark,
                   why='ResourceActivity relaunched after process death')
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_a(ed, r):
    """Instances: all 20 (OnePlus8Pro x15, HRY-LX1T x5): ResourceActivity launched with an empty intent, retried ~4 s later."""
    _f7a4eff3_home(ed)
    for _ in range(2):                               # field: same model crashes twice 4-6 s apart
        mark = ed.log_mark()
        ed.step('launch ResourceActivity with no Type/Title/Category extras')
        ed.start_activity(_F7A4_RES, extras=None, expect_crash=True)
        ed.require_log(r'START u0 .*ResourceActivity', 10, since=mark, why='field: crash under performLaunchActivity')
        ed.idle(3)
        _f7a4eff3_home(ed)
        ed.idle(r.uniform(0.5, 1.5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_b(ed, r):
    """Instances: OnePlus8Pro group (x15): Frames -> more -> ResourceActivity, reclaimed in background, restored from recents."""
    _f7a4eff3_more_then_restore(ed, r, 'frame')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_1_c(ed, r):
    """Instances: HRY-LX1T group (x5): Poster -> more -> ResourceActivity, reclaimed in background, restored from recents."""
    _f7a4eff3_more_then_restore(ed, r, 'poster')


# 2026-10-29 13:14 level 2 attempt 2
_F7A4_RES = 'com.myzesty/com.photo.myzesty.ui.activity.resource.ResourceActivity'
_F7A4_START_NO_EXTRAS = r'START u0 \{[^}]*com\.photo\.myzesty\.ui\.activity\.resource\.ResourceActivity\}'
_F7A4_MAIN_RESUMED = r'wm_on_resume_called: \[\d+,com\.myzesty[./]MainActivity'


def _f7a4eff3_foreground(ed):
    """Checkpoint 1: app in front with Realm up (the Displayed line was already logged in the fresh-start step)."""
    mark = ed.log_mark()
    ed.dev.launch()                                  # brings the live task back -> a new resume line we can wait on
    ed.require_log(_F7A4_MAIN_RESUMED, 15, since=mark, why='app in FOREGROUND, 20/20 field events')
    ed.idle(2)


def _f7a4eff3_empty_launch(ed, why):
    """Checkpoints 2-4: ResourceActivity started with no Type/Title extra -> setData(null) -> NPE on 'table'."""
    mark = ed.log_mark()
    ed.step('start ResourceActivity with an empty intent (no Type extra)')
    ed.start_activity(_F7A4_RES, extras=None, expect_crash=True)
    ed.require_log(_F7A4_START_NO_EXTRAS, 10, since=mark, why=why)   # no '(has extras)', no Permission Denial
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_a(ed, r):
    """Instances: OnePlus8Pro pairs (07:17:33/37, 08:08:12/16, 09:51:23/29): empty-intent launch from home, retried ~4-6 s later."""
    _f7a4eff3_foreground(ed)
    for _ in range(2):
        _f7a4eff3_empty_launch(ed, 'field: launch with no Type extra under performLaunchActivity')
        ed.idle(r.uniform(0.5, 2))
        _f7a4eff3_foreground(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_b(ed, r):
    """Instances: HRY-LX1T x5 + OnePlus8Pro singles: empty-intent launch while a photo tool (Poster) is open on top."""
    _f7a4eff3_foreground(ed)
    ed.ui.tap('textc:all tools', timeout=5)          # decorative: Poster may already be on the home grid
    ed.idle(1.5)
    ed.ui.tap('textc:poster', timeout=5)             # decorative: the crash does not need this screen
    ed.idle(r.uniform(2, 4))
    _f7a4eff3_empty_launch(ed, 'field: empty launch on top of an open photo screen')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_2_c(ed, r):
    """Instances: first event of each burst (07:03:27, 07:12:50, 07:14:06, 08:05:15): empty-intent launch into a cold process."""
    _f7a4eff3_foreground(ed)
    ed.kill_bg()                                     # cached app reclaimed: the launch starts the process + Realm init
    ed.idle(r.uniform(3, 5))
    _f7a4eff3_empty_launch(ed, 'field: ResourceActivity is the first activity of a new process')


# 2026-10-29 13:19 level 2 attempt 3
_F7A4_CMP = 'com.myzesty/com.photo.myzesty.ui.activity.resource.ResourceActivity'
_F7A4_START = r'START u0 \{[^}]*cmp=com\.myzesty/com\.photo\.myzesty\.ui\.activity\.resource\.ResourceActivity\}'
_F7A4_NPE = r'Parameter specified as non-null is null.*parameter table|FATAL EXCEPTION: main'


def _f7a4eff3_root_launch(ed):
    """Checkpoints 2-4: start the non-exported ResourceActivity with an EMPTY intent from uid 0 (shell gets Permission Denial)."""
    if 'uid=0' not in (ed.dev.sh("su -c id", timeout=10) or '') + (ed.dev.sh("su 0 id", timeout=10) or ''):
        raise UIError('lab phone has no root: a no-extras launch of the non-exported ResourceActivity is impossible')
    su = "su -c" if 'uid=0' in (ed.dev.sh("su -c id", timeout=10) or '') else "su 0"
    mark = ed.log_mark()
    ed.step('root: am start ResourceActivity with no Type/Title extra')
    out = ed.dev.sh(f"{su} 'am start -n {_F7A4_CMP}'" if su == "su -c" else f"{su} am start -n {_F7A4_CMP}", timeout=15) or ''
    if 'Permission Denial' in out or 'Error' in out:
        raise UIError(f'empty-intent launch refused: {out.strip()[:160]}')
    ed.require_log(_F7A4_START, 10, since=mark, why='field: fresh launch of ResourceActivity with no extras (performLaunchActivity)')
    ed.require_log(_F7A4_NPE, 15, since=mark, why='field: NPE on table from RealmWrapper.d during onCreate')
    ed.idle(3)                                       # the monitor turns the death into AppFailure + dumps


def _f7a4eff3_app_alive(ed):
    """Checkpoint 1: the fresh-start step already showed Displayed + resume; only check the process is still up."""
    if ed.dev.pid() == '':
        raise UIError('app process not running after the fresh start (field: app in FOREGROUND)')
    ed.idle(2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_a(ed, r):
    """Instances: 2nd event of each OnePlus8Pro pair + mid-burst singles: empty-intent launch while the app is warm on its home screen."""
    _f7a4eff3_app_alive(ed)
    ed.idle(r.uniform(1, 4))
    _f7a4eff3_root_launch(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_b(ed, r):
    """Instances: first event of each burst (07:03:27, 07:12:50, 07:14:06, 08:05:15): empty-intent launch after the cached app was reclaimed."""
    _f7a4eff3_app_alive(ed)
    ed.kill_bg()                                     # Home + system reclaims the cached process (task kept)
    for _ in range(10):
        if ed.dev.pid() == '':
            break
        ed.idle(1)
    ed.mon.allow_death = False                       # from here a death is the field crash, not the reclaim
    ed.idle(r.uniform(2, 4))
    _f7a4eff3_root_launch(ed)                        # new process: Application + Realm init, then ResourceActivity.onCreate


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l2_3_c(ed, r):
    """Instances: HRY-LX1T x5 (crash 4-6 s apart on retry): empty-intent launch on top of an open Frames screen, the app's own caller."""
    _f7a4eff3_app_alive(ed)
    ed.ui.tap('textc:all tools', timeout=5)          # decorative: Frames may already sit on the home grid
    ed.idle(1.5)
    ed.ui.tap('textc:frame', timeout=5)              # decorative: FramesActivity is the real in-app caller of ResourceActivity
    ed.idle(r.uniform(2, 4))
    _f7a4eff3_root_launch(ed)


# 2026-10-29 13:22 level 3 attempt 1
_F7A4_RES = 'com.myzesty/com.photo.myzesty.ui.activity.resource.ResourceActivity'
# no '(has extras)' before the closing brace = empty intent, the field condition
_F7A4_START_EMPTY = r'START u0 \{[^}]*cmp=com\.myzesty/com\.photo\.myzesty\.ui\.activity\.resource\.ResourceActivity\}'


def _f7a4eff3_need_root(ed):
    """ResourceActivity is not exported: only a privileged caller can start it with an empty intent."""
    out = ed.dev.sh("su -c id", timeout=10) or ''
    if 'uid=0' not in out:
        raise UIError('lab phone has no root: a no-extras launch of the non-exported ResourceActivity is impossible')


def _f7a4eff3_empty_launch(ed, why):
    """Checkpoints 2-4: privileged am start with no Type/Title -> onCreate -> setData(null) -> NPE on 'table'."""
    mark = ed.log_mark()
    ed.step('su am start ResourceActivity with an empty intent (no Type extra)')
    ed.mon.allow_death = False                       # the crash must be recorded, not excused
    ed.dev.sh(f"su -c 'am start -n {_F7A4_RES}'", timeout=15)
    ed.require_log(_F7A4_START_EMPTY, 10, since=mark, why=why)
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_a(ed, r):
    """Instances: OnePlus8Pro pairs (07:17:33/37, 08:08:12/16, 09:51:23/29): empty-intent launch on top of the live app, retried 4-6 s later."""
    _f7a4eff3_need_root(ed)
    if not ed.dev.pid():
        raise UIError('app not running in the foreground (field: foreground 20/20)')
    ed.idle(2)
    for _ in range(2):
        _f7a4eff3_empty_launch(ed, 'field: performLaunchActivity of ResourceActivity without Type')
        ed.idle(r.uniform(0.5, 2))
        ed.dev.launch()
        ed.idle(r.uniform(2, 4))


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_l3_1_b(ed, r):
    """Instances: first event of each burst (07:03:27, 07:12:50, 07:14:06 HRY-LX1T, 08:05:15 HRY-LX1T): empty-intent launch into a reclaimed, cold process under memory pressure."""
    _f7a4eff3_need_root(ed)
    ed.idle(2)
    ed.kill_bg()                                     # system reclaims the cached app: the launch starts process + Realm
    ed.idle(r.uniform(3, 5))
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW >/dev/null 2>&1')
    _f7a4eff3_empty_launch(ed, 'field: ResourceActivity is the first activity of a new process')
