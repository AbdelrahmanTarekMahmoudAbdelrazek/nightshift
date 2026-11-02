# Night Shift tap repros for f7a4eff327f9009210c5164e8a1148d0 (from the engine repro + full field log)


# 2026-10-28 22:12 attempt 1
# Night Shift tap-flow repro: Crashlytics "com.common.myzesty.realm.RealmWrapper.d"
# (NPE 'Parameter specified as non-null is null: method y4.d.d, parameter table' in performLaunchActivity).
# Code path: ResourceActivity.onCreate:42 -> ResourcePresenter.setData(getStringExtra(Type)) ->
# RealmWrapper.getAllImageEditorResources(table=null, ...) (RealmWrapper.kt:102). Only opener: TextFragment 'more'.

PHOTO_RE = r'wm_(on_create_called|restart_activity).*com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'
RES_RE = r'wm_(on_create_called|restart_activity).*com\.photo\.myzesty\.ui\.activity\.resource\.ResourceActivity'


def _open_font_list(ed, why):
    """Photo editor -> Text tool -> 'more' arrow (TextFragment.kt:217): starts ResourceActivity."""
    ed.step('photo editor: Text tool')
    t = ed.log_mark()
    ed.ui.tap(('textc:text',), timeout=15)
    ed.require_log(r'TextFragment|LOG_IE_TEXT|ie_text', timeout=10, since=t, why='text panel opened')
    ed.step('text panel: more fonts (ResourceActivity)')
    t = ed.log_mark()
    ed.ui.tap(('id:more',), timeout=15)                     # the real trigger tap
    ed.require_log(RES_RE, timeout=10, since=t, why=why)


def _relaunch_burst(ed, r):
    """Field bursts: same device crashes again 4-6 s later -> relaunch the restored task twice."""
    for k in range(2):
        ed.step(f'relaunch from recents #{k + 1}: ResourceActivity restored on top')
        t = ed.log_mark()
        ed.dev.launch()
        ed.require_log(RES_RE, timeout=15, since=t, why=f'ResourceActivity relaunched #{k + 1}')
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_a(ed, r):
    """FULL: RealmWrapper.d null table - Image Editor -> Text -> more fonts, then background reclaim and relaunch."""
    ed.dev.restore_env()
    ed.open_fixture('9eb49083')
    ed.leave_editor()
    ed.main_nav()
    ed.step('home: Image Editor')
    t = ed.log_mark()
    ed.ui.tap(('id:home_cta_image',), timeout=20)
    ed.require_log(PHOTO_RE, timeout=20, since=t, why='photo editor (PhotoActivity) opened')
    ed.idle(3)
    _open_font_list(ed, 'more -> ResourceActivity created')
    ed.idle(r.uniform(1, 3))
    ed.step('home + system reclaims the process (task kept)')
    ed.kill_bg()                                             # keeps the task: next launch restores ResourceActivity
    _relaunch_burst(ed, r)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_b(ed, r):
    """HYBRID: RealmWrapper.d null table - photo editor via lab shortcut, real 'more' tap, then restore relaunch."""
    ed.dev.restore_env()
    ed.open_fixture('9eb49083')
    ed.leave_editor()
    t = ed.log_mark()
    ed.lab('photo_editor_sample', timeout=30)                # HYBRID: no picker-free tap path to PhotoActivity
    ed.require_log(PHOTO_RE, timeout=20, since=t, why='photo editor opened (lab)')  # HYBRID
    ed.idle(3)
    _open_font_list(ed, 'more -> ResourceActivity created')
    for k in range(r.randint(2, 3)):                         # user retries the same entry, as in the field bursts
        ed.step(f'close font list and reopen #{k + 1}')
        ed.dev.key('KEYCODE_BACK')
        ed.idle(r.uniform(0.5, 1.5))
        t = ed.log_mark()
        ed.ui.tap(('id:more',), timeout=15)
        ed.require_log(RES_RE, timeout=10, since=t, why=f'more reopened #{k + 1}')
    ed.kill_bg()
    _relaunch_burst(ed, r)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_c(ed, r):
    """HYBRID: RealmWrapper.d null table - slow phone + Don't keep activities: ResourceActivity recreated on return."""
    ed.dev.restore_env()
    ed.open_fixture('9eb49083')
    ed.leave_editor()
    t = ed.log_mark()
    ed.lab('photo_editor_sample', timeout=30)                # HYBRID: no picker-free tap path to PhotoActivity
    ed.require_log(PHOTO_RE, timeout=20, since=t, why='photo editor opened (lab)')  # HYBRID
    ed.idle(3)
    ed.dev.slow_phone(r.randint(30, 45))                     # low-end field phones (HRY-LX1T)
    ed.dont_keep_activities(True)
    try:
        _open_font_list(ed, 'more -> ResourceActivity created (slow phone)')
        for k in range(2):
            ed.step(f'home and back #{k + 1}: activity destroyed, recreated from saved state')
            ed.dev.key('KEYCODE_HOME')
            ed.idle(r.uniform(1, 3))
            t = ed.log_mark()
            ed.dev.launch()
            ed.require_log(RES_RE, timeout=20, since=t, why=f'ResourceActivity recreated #{k + 1}')
            ed.idle(r.uniform(3, 5))
    finally:
        ed.dont_keep_activities(False)
        ed.dev.slow_phone(0)


# 2026-10-28 22:18 attempt 2
# Night Shift tap-flow repro: Crashlytics "com.common.myzesty.realm.RealmWrapper.d"
# NPE 'Parameter specified as non-null is null: method y4.d.d, parameter table' in performLaunchActivity.
# ResourceActivity.java:42 / StickerResourcesActivity.java:86 -> ResourcePresenter.setData/setDataCategory(intent Type)
# -> RealmWrapper.getAllImageEditorResources(table=null) (ResourcePresenter.java:84/125). Both in-app openers
# (TextFragment.kt:217 'more', StickersFragment.kt:120) always put Type, so null needs a launch without extras.

PHOTO_RE = r'wm_(on_create_called|restart_activity).*com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'
RES_RE = r'wm_(on_create_called|restart_activity).*com\.photo\.myzesty\.ui\.activity\.resource\.ResourceActivity'
STK_RE = r'wm_(on_create_called|restart_activity).*com\.photo\.myzesty\.ui\.activity\.resource\.StickerResourcesActivity'
RES_CMP = 'com.myzesty/com.photo.myzesty.ui.activity.resource.'


def _home(ed):
    """Last runs stopped on the React Native redbox over MainActivity: dismiss it, no project fixture."""
    ed.dev.restore_env()
    for _ in range(10):
        s = ed.screen()
        if s is not None and s.has(('id:rn_redbox_dismiss_button',)):
            ed.dev.tap(*s.find(('id:rn_redbox_dismiss_button',)).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(('id:home_cta_image',)):
            return
        time.sleep(1.5)


def _photo_editor_lab(ed):
    _home(ed)
    t = ed.log_mark()
    ed.lab('photo_editor_sample', timeout=30)                       # HYBRID: no picker-free tap path to PhotoActivity
    ed.require_log(PHOTO_RE, timeout=20, since=t, why='photo editor opened (lab)')   # HYBRID
    ed.idle(3)


def _tap_open(ed, sel, pattern, why):
    ed.step(why)
    t = ed.log_mark()
    ed.ui.tap(sel, timeout=15)
    ed.require_log(pattern, timeout=15, since=t, why=why)


def _reclaim_relaunch(ed, r, pattern, n=2):
    """Field bursts (same model 4-6 s apart): background reclaim keeps the task, launch restores the top activity."""
    for k in range(n):
        ed.kill_bg()
        ed.step(f'relaunch #{k + 1}: restored resource screen')
        t = ed.log_mark()
        ed.dev.launch()
        ed.require_log(pattern, timeout=20, since=t, why=f'resource screen restored #{k + 1}')
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_2_a(ed, r):
    """FULL: RealmWrapper.d null table - Home Image Editor -> Text -> more fonts, then reclaim + relaunch burst."""
    _home(ed)
    _tap_open(ed, ('id:home_cta_image',), PHOTO_RE, 'home: Image Editor -> PhotoActivity')
    ed.idle(3)
    _tap_open(ed, ('textc:text',), r'TextFragment|wm_on_resume_called.*PhotoActivity', 'photo editor: Text tool')
    _tap_open(ed, ('id:more',), RES_RE, 'text: more fonts -> ResourceActivity')
    ed.idle(r.uniform(1, 3))
    _reclaim_relaunch(ed, r, RES_RE)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_2_b(ed, r):
    """HYBRID: RealmWrapper.d null table - lab photo editor, real Stickers and Text 'more' taps, restore relaunch."""
    _photo_editor_lab(ed)
    _tap_open(ed, ('textc:sticker',), STK_RE, 'photo editor: Stickers -> StickerResourcesActivity')
    ed.idle(r.uniform(1, 2))
    ed.dev.key('KEYCODE_BACK')
    ed.idle(1.5)
    _tap_open(ed, ('textc:text',), r'TextFragment|wm_on_resume_called.*PhotoActivity', 'photo editor: Text tool')
    _tap_open(ed, ('id:more',), RES_RE, 'text: more fonts -> ResourceActivity')
    _reclaim_relaunch(ed, r, RES_RE, n=r.randint(2, 3))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_2_c(ed, r):
    """HYBRID: RealmWrapper.d null table - slow phone, resource screens launched with NO extras (test-farm burst)."""
    _photo_editor_lab(ed)
    ed.dev.slow_phone(r.randint(30, 45))                            # low-end HRY-LX1T
    try:
        _tap_open(ed, ('textc:text',), r'TextFragment|wm_on_resume_called.*PhotoActivity', 'photo editor: Text tool')
        _tap_open(ed, ('id:more',), RES_RE, 'text: more fonts (with Type) -> ResourceActivity')
        ed.dev.key('KEYCODE_BACK')
        ed.idle(1.5)
        for k, (cls, pat) in enumerate([('ResourceActivity', RES_RE), ('StickerResourcesActivity', STK_RE)]):
            ed.step(f'launch {cls} without Type extra (robo/test-farm entry) #{k + 1}')
            t = ed.log_mark()
            ed.dev.sh(f'am start -n {RES_CMP}{cls}', timeout=15)     # trigger: no Type -> table=null
            ed.require_log(pat, timeout=15, since=t, why=f'{cls} created without extras')
            ed.idle(r.uniform(4, 6))
    finally:
        ed.dev.slow_phone(0)


# 2026-10-28 22:24 attempt 3
# Night Shift tap-flow repro: Crashlytics "com.common.myzesty.realm.RealmWrapper.d"
# NPE 'Parameter specified as non-null is null: method y4.d.d, parameter table' inside performLaunchActivity.
# ResourceActivity.java:42 / StickerResourcesActivity.java:86 pass getIntent().getStringExtra(Type) to
# ResourcePresenter.setData/setDataCategory -> RealmWrapper.getAllImageEditorResources(table=null) (ResourcePresenter:84/125).
# In-app openers (TextFragment.kt:217, StickersFragment.kt:120) always put Type and a restore keeps extras,
# so at launch the null only comes from an intent with no extras (robo / test-farm entry).

PKG_CMP = 'com.myzesty/com.photo.myzesty.ui.activity.resource.'
# system lines are logged BEFORE onCreate runs (wm_on_create_called only after it returns -> never on this crash)
LAUNCH_RE = r'(wm_create_activity|wm_restart_activity|START u0).*com\.photo\.myzesty\.ui\.activity\.resource\.%s'
ANY_PHOTO_RE = r'(wm_create_activity|START u0).*com\.(photo\.)?myzesty[./].*(Photo|Gallery|Picker|Image)\w*Activity'


def _wait_home(ed, limit=120):
    """Get past the splash ('Create, Edit & Share', last runs) and the RN redbox to the home screen."""
    ed.dev.restore_env()
    ed.step('wait for home (splash / redbox)')
    t0, relaunched = time.time(), False
    while time.time() - t0 < limit:
        s = ed.screen()
        if s is not None and (s.has(('id:home_cta_image',)) or s.has(('textc:image editor',))):
            return s
        if s is not None and s.has(('id:rn_redbox_dismiss_button',)):
            ed.dev.tap(*s.find(('id:rn_redbox_dismiss_button',)).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif not relaunched and time.time() - t0 > 45:
            ed.step('splash stuck: launcher start again')
            ed.dev.launch()
            relaunched = True
        time.sleep(2)
    raise UIError('home screen (home_cta_image) never showed: app stuck on splash/redbox')


def _launch_no_extras(ed, cls, why):
    ed.step(why)
    t = ed.log_mark()
    out = ed.dev.sh(f'am start -W -n {PKG_CMP}{cls}', timeout=20)        # HYBRID: empty intent, Type == null
    ed.log(f'    am start {cls}: {out.strip()[-160:]}')
    ed.require_log(LAUNCH_RE % cls, timeout=15, since=t, why=f'{cls} launched with no extras')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_a(ed, r):
    """FULL: RealmWrapper.d null table - home Image Editor tap, then reclaim + relaunch bursts (restore path)."""
    s = _wait_home(ed)
    ed.step('home: Image Editor')
    t = ed.log_mark()
    sel = ('id:home_cta_image',) if s.has(('id:home_cta_image',)) else ('textc:image editor',)
    ed.ui.tap(sel, timeout=15)
    ed.require_log(ANY_PHOTO_RE, timeout=20, since=t, why='Image Editor opened its next screen')
    ed.idle(r.uniform(2, 4))
    for k in range(2):                                    # field: same model crashes again 4-6 s later
        ed.kill_bg()                                      # keeps the task: relaunch restores the top activity
        ed.step(f'relaunch from recents #{k + 1}')
        t = ed.log_mark()
        ed.dev.launch()
        ed.require_log(r'(wm_restart_activity|START u0).*com\.myzesty', timeout=20, since=t,
                       why=f'task restored #{k + 1}')
        ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_b(ed, r):
    """HYBRID: RealmWrapper.d null table - app at home, resource screens launched with no Type extra."""
    _wait_home(ed)
    ed.idle(r.uniform(1, 3))
    _launch_no_extras(ed, 'ResourceActivity', 'ResourceActivity without extras -> setData(null)')
    ed.idle(r.uniform(4, 6))
    ed.dev.launch()                                       # back to the app like the field retry
    ed.idle(2)
    _launch_no_extras(ed, 'StickerResourcesActivity', 'StickerResourcesActivity without extras -> setDataCategory(null)')
    ed.idle(r.uniform(4, 6))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_c(ed, r):
    """HYBRID: RealmWrapper.d null table - slow phone, cold-process launches with no extras, 4-6 s bursts."""
    _wait_home(ed)
    ed.dev.slow_phone(r.randint(30, 45))                  # low-end HRY-LX1T
    try:
        for k in range(r.randint(2, 3)):
            ed.kill_bg()                                  # HYBRID: cold process, as a fresh robo launch
            cls = 'ResourceActivity' if k % 2 == 0 else 'StickerResourcesActivity'
            _launch_no_extras(ed, cls, f'burst #{k + 1}: cold {cls} without extras')
            ed.idle(r.uniform(4, 6))                      # field bursts: 4-6 s apart on one model
    finally:
        ed.dev.slow_phone(0)


# 2026-10-29 12:27 attempt 1
"""Night Shift tap-flow for Crashlytics com.common.myzesty.realm.RealmWrapper.d (NPE: null 'table' during launch)."""

PHOTO = r'wm_on_create_called.*com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'
RES = r'(wm_on_create_called|wm_restart_activity).*com\.photo\.myzesty\.ui\.activity\.resource\.(StickerResources|Resource)Activity'
RESTORE = r'(wm_restart_activity|wm_on_create_called).*com\.photo\.myzesty\.ui\.activity\.resource\.'


def _open_stickers(ed):
    """Stickers tool: StickersFragment.onCreate -> openResources(true) -> StickerResourcesActivity(Type=STICKER)."""
    t = ed.log_mark()
    ed.tap_tool('sticker')
    ed.require_log(RES, timeout=15, since=t, why='stickers tool opens StickerResourcesActivity (setDataCategory -> RealmWrapper)')


def _restore_burst(ed, r, n):
    """Field bursts a few seconds apart: bring the resource screen back from a reclaimed process, n times."""
    for i in range(n):
        ed.step(f'restore resource screen {i + 1}/{n}')
        t = ed.log_mark()
        ed.kill_bg()                                     # HOME + system reclaim: task and Bundle kept (not force-stop)
        ed.idle(r.uniform(1.0, 3.0))
        ed.dev.launch()                                  # cold launcher start restores the top activity
        ed.require_log(RESTORE, timeout=20, since=t, why='relaunch restores the resource activity')
        ed.idle(r.uniform(2.0, 4.0))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_a(ed, r):
    """FULL: first-session sample image -> photo editor -> Stickers -> resource list -> app reclaimed and restored (RealmWrapper.d null table)."""
    ed.dev.restore_env()
    ed.step('onboarding: try sample image (first session only)')
    t = ed.log_mark()
    ed.ui.tap(('textc:sample',), timeout=20)
    ed.require_log(PHOTO, timeout=25, since=t, why='sample image opens PhotoActivity (needs a first session)')
    ed.idle(2)
    _open_stickers(ed)
    ed.idle(3)
    _restore_burst(ed, r, 3)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_b(ed, r):
    """HYBRID: photo editor opened by lab control, then real Stickers tap and restores of StickerResourcesActivity (RealmWrapper.d null table)."""
    ed.dev.restore_env()
    t = ed.log_mark()
    ed.lab('open_photo_sample', timeout=30)                                         # HYBRID
    ed.require_log(PHOTO, timeout=25, since=t, why='lab opens PhotoActivity')       # HYBRID
    ed.idle(2)
    _open_stickers(ed)                                   # TRIGGER: real tap
    ed.idle(3)
    for i in range(2):                                   # leave and re-enter the resource list like a retrying user
        ed.step(f'back and re-open stickers {i + 1}/2')
        ed.dev.key('KEYCODE_BACK')
        ed.idle(1.5)
        _open_stickers(ed)
        ed.idle(2)
    _restore_burst(ed, r, 3)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_c(ed, r):
    """HYBRID: like b on a slow phone with Don't keep activities and rotations, so the resource screen is recreated mid-launch (RealmWrapper.d null table)."""
    ed.dev.restore_env()
    t = ed.log_mark()
    ed.lab('open_photo_sample', timeout=30)                                         # HYBRID
    ed.require_log(PHOTO, timeout=25, since=t, why='lab opens PhotoActivity')       # HYBRID
    ed.idle(2)
    try:
        ed.dev.network(True)                             # setDataCategory reaches Realm only when the network is up
        ed.dev.slow_network(r.choice([64, 128]))
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dont_keep_activities(True)
        for i in range(3):
            ed.step(f'stickers under pressure {i + 1}/3')
            t = ed.log_mark()
            ed.tap_tool('sticker')                       # TRIGGER: real tap
            ed.rotate_when(RES, timeout=15, since=t, back_after=1)   # config change the moment the activity is created
            ed.require_log(RESTORE, timeout=20, since=t, why='resource activity created/recreated')
            ed.background(r.uniform(2, 5), pressure=True)
            ed.idle(r.uniform(1, 3))
            ed.dev.key('KEYCODE_BACK')
            ed.idle(1.5)
        _restore_burst(ed, r, 2)
    finally:
        ed.dont_keep_activities(False)
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-10-29 12:38 attempt 2
"""Night Shift tap-flow for Crashlytics com.common.myzesty.realm.RealmWrapper.d (NPE: null 'table' in performLaunchActivity)."""

PHOTO = r'wm_on_create_called.*com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'
STICK = r'(wm_on_create_called|wm_restart_activity).*com\.photo\.myzesty\.ui\.activity\.resource\.StickerResourcesActivity'
FONTS = r'(wm_on_create_called|wm_restart_activity).*com\.photo\.myzesty\.ui\.activity\.resource\.ResourceActivity'
RES = r'(wm_on_create_called|wm_restart_activity).*com\.photo\.myzesty\.ui\.activity\.resource\.'


def _photo_editor(ed):
    """Shipped home -> Image Editor -> first photo -> PhotoActivity (no sample-image onboarding on this install)."""
    ed.dev.restore_env()
    ed.dev.network(True)                             # setDataCategory reaches Realm only with network
    ed.step('home: Image Editor')
    t = ed.log_mark()
    ed.ui.tap(('id:home_cta_image', 'text:Image Editor'), timeout=25)
    ed.idle(3)
    ed.ui.tap(('id:imageView', 'id:img', 'id:thumbnail', 'id:ic_preview'), timeout=20)   # first photo
    ed.idle(1.5)
    s = ed.screen()
    if s is not None and s.has(('textc:done', 'textc:next')):
        ed.dev.tap(*s.find(('textc:done', 'textc:next')).center)
    ed.require_log(PHOTO, timeout=25, since=t, why='photo pick opens PhotoActivity')
    ed.idle(2)


def _stickers(ed):
    """Sticker tool: StickersFragment.onViewCreated -> openResources(true) -> StickerResourcesActivity(Type=STICKER)."""
    t = ed.log_mark()
    ed.ui.tap(('textc:sticker',), timeout=15)
    ed.require_log(STICK, timeout=15, since=t, why='Sticker tool opens StickerResourcesActivity -> RealmWrapper')


def _restore_burst(ed, r, n, act=RES):
    """Field bursts seconds apart: system reclaims the HOMEd app (task + intent kept), launcher restores the top activity."""
    for i in range(n):
        ed.step(f'reclaim + restore resource screen {i + 1}/{n}')
        t = ed.log_mark()
        ed.kill_bg()
        ed.idle(r.uniform(1.0, 3.0))
        ed.dev.launch()
        ed.require_log(act, timeout=20, since=t, why='relaunch restores the resource activity (performLaunchActivity)')
        ed.idle(r.uniform(3.0, 5.0))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_2_a(ed, r):
    """FULL: Image Editor -> photo -> Sticker -> StickerResourcesActivity, then reclaimed and restored in bursts (RealmWrapper.d null table)."""
    _photo_editor(ed)
    _stickers(ed)
    ed.idle(3)
    _restore_burst(ed, r, 3, STICK)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_2_b(ed, r):
    """HYBRID: photo editor reached by picking a photo, then real taps into both Realm screens (stickers, Text -> fonts) and restore bursts (RealmWrapper.d null table)."""
    _photo_editor(ed)                                # HYBRID: the photo pick is setup only, not the trigger
    _stickers(ed)                                    # TRIGGER: real tap
    ed.idle(2)
    ed.dev.key('KEYCODE_BACK')
    ed.idle(1.5)
    ed.step('Text tool -> font list (ResourceActivity, Type=FONT)')
    ed.ui.tap(('textc:text',), timeout=15)
    ed.idle(1.5)
    t = ed.log_mark()
    ed.ui.tap(('textc:font',), timeout=15)           # TRIGGER: real tap
    ed.require_log(FONTS, timeout=15, since=t, why='font button opens ResourceActivity -> setData(type)')
    ed.idle(2)
    _restore_burst(ed, r, 3, FONTS)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_2_c(ed, r):
    """HYBRID: like a on a slow phone with Don't keep activities and a rotation the moment the resource screen is created (RealmWrapper.d null table)."""
    _photo_editor(ed)                                # HYBRID: the photo pick is setup only, not the trigger
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dont_keep_activities(True)
        for i in range(3):
            ed.step(f'stickers under pressure {i + 1}/3')
            t = ed.log_mark()
            ed.ui.tap(('textc:sticker',), timeout=20)    # TRIGGER: real tap
            ed.rotate_when(STICK, timeout=15, since=t, back_after=1)
            ed.require_log(STICK, timeout=20, since=t, why='StickerResourcesActivity created/recreated')
            ed.background(r.uniform(2, 5), pressure=True)
            ed.idle(r.uniform(1, 3))
            ed.dev.key('KEYCODE_BACK')
            ed.idle(1.5)
        _restore_burst(ed, r, 2)
    finally:
        ed.dont_keep_activities(False)
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-10-29 12:42 attempt 3
"""Night Shift tap-flow for Crashlytics com.common.myzesty.realm.RealmWrapper.d (NPE: null 'table' in performLaunchActivity)."""

PE = r'test_home_pe_tap|START u0 .*com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'
STICK = r'START u0 .*com\.photo\.myzesty\.ui\.activity\.resource\.StickerResourcesActivity|wm_restart_activity.*StickerResourcesActivity'
FONTS = r'START u0 .*com\.photo\.myzesty\.ui\.activity\.resource\.ResourceActivity|wm_restart_activity.*resource\.ResourceActivity'
RES = r'(wm_restart_activity|wm_on_create_called|START u0 ).*com\.photo\.myzesty\.ui\.activity\.resource\.'
PKG_RES = 'com.myzesty/com.photo.myzesty.ui.activity.resource.'


def _photo_editor(ed):
    """Home 'Image Editor' opens PhotoActivity straight on the uCrop screen; Done (id done) enters the editor."""
    ed.dev.restore_env()
    ed.dev.network(True)                                   # setDataCategory reaches Realm only with network
    ed.step('home: Image Editor')
    t = ed.log_mark()
    ed.ui.tap(('id:home_cta_image',), timeout=25)
    ed.require_log(PE, timeout=20, since=t, why='Image Editor tap starts PhotoActivity')
    ed.idle(3)
    ed.step('crop screen: Done')
    t = ed.log_mark()
    ed.ui.tap(('id:done', 'desc:Done'), timeout=20)
    ed.require_log(r'test_pe_start|wm_on_resume_called.*PhotoActivity|AnalyticsManager: Event: test_pe_', timeout=20, since=t,
                   why='crop Done enters the photo editor')
    ed.idle(2)


def _tool(ed, label, pattern, why):
    t = ed.log_mark()
    ed.ui.tap((f'textc:{label}',), timeout=20)
    ed.require_log(pattern, timeout=15, since=t, why=why)


def _restore_burst(ed, r, n, act):
    """HOME + system reclaim keeps the task and its intent; the launcher restores the resource screen (performLaunchActivity)."""
    for i in range(n):
        ed.step(f'reclaim + restore {i + 1}/{n}')
        t = ed.log_mark()
        ed.kill_bg()
        ed.idle(r.uniform(1.0, 3.0))
        ed.dev.launch()
        ed.require_log(act, timeout=20, since=t, why='relaunch restores the resource activity')
        ed.idle(r.uniform(3.0, 5.0))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_a(ed, r):
    """FULL: Image Editor -> crop Done -> Sticker -> StickerResourcesActivity, then reclaim/restore bursts (RealmWrapper.d null table)."""
    _photo_editor(ed)
    _tool(ed, 'sticker', STICK, 'Sticker tool opens StickerResourcesActivity -> setDataCategory -> RealmWrapper')
    ed.idle(3)
    _restore_burst(ed, r, 3, RES)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_b(ed, r):
    """HYBRID: Image Editor -> Text -> more fonts (ResourceActivity.setData -> RealmWrapper), then reclaim/restore bursts (RealmWrapper.d null table)."""
    _photo_editor(ed)
    _tool(ed, 'text', r'PhotoActivity|TextFragment|AnalyticsManager', 'Text tool opens the text panel')
    ed.idle(1.5)
    t = ed.log_mark()
    ed.ui.tap(('id:more', 'textc:more'), timeout=15)   # TRIGGER: real tap (TextFragment binding.more)
    ed.require_log(FONTS, timeout=15, since=t, why='More fonts opens ResourceActivity(Type=FONT)')
    ed.idle(3)
    _restore_burst(ed, r, 3, RES)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_c(ed, r):
    """HYBRID: photo editor by real taps, then a test-robot-style launch of each resource screen with NO extras, in field-like bursts on a slow phone (RealmWrapper.d null table)."""
    _photo_editor(ed)
    try:
        ed.dev.slow_phone(r.randint(20, 35))
        for i in range(3):
            for act in ('ResourceActivity', 'StickerResourcesActivity'):
                ed.step(f'empty-intent launch {act} {i + 1}/3')
                t = ed.log_mark()
                ed.dev.sh(f'am start -n {PKG_RES}{act}', timeout=15)   # HYBRID: robot launch, no Type extra
                ed.require_log(rf'START u0 .*resource\.{act}|Permission Denial.*{act}', timeout=15, since=t,
                               why=f'{act} started with an empty intent')
                ed.idle(r.uniform(3.0, 6.0))                # field bursts ~4-6 s apart
                ed.dev.key('KEYCODE_BACK')
                ed.idle(1.0)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-10-29 13:57 attempt 1
# Night Shift tapflow: Crashlytics "com.common.myzesty.realm.RealmWrapper.d" (NPE, parameter table, performLaunchActivity)
# Field path (inferred from code, 0 breadcrumbs): a launch WITHOUT the Type extra of the photo module's resource screens:
#   ResourceActivity.onCreate:42 -> ResourcePresenter.setData(null) -> RealmWrapper.getAllImageEditorResources(null, ..)
#   StickerResourcesActivity.onCreate:86 -> setDataCategory(null, null) -> RealmWrapper.getAllImageEditorResources (:125)

RES_ACT = 'com.photo.myzesty.ui.activity.resource.ResourceActivity'
STK_ACT = 'com.photo.myzesty.ui.activity.resource.StickerResourcesActivity'
LAUNCHED = r'(START u0 .*|am_create_activity.*|wm_on_create_called.*)ui\.activity\.resource\.{}'


def _app_up(ed):
    ed.dev.restore_env()                             # network ON: setDataCategory only reaches Realm when online
    ed.dev.launch()
    ed.require_log(r'Displayed com\.myzesty[./]', timeout=20, why='app in front (lab door needs a foreground app)')
    ed.idle(2)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_a(ed, r):
    """FULL: DIRECT LAUNCH (field path): ResourceActivity with NO extras -> setData(null) -> RealmWrapper NPE in onCreate."""
    _app_up(ed)
    t0 = ed.log_mark()
    ed.start_activity(RES_ACT, extras='')
    ed.require_log(LAUNCHED.format('ResourceActivity'), timeout=15, since=t0,
                   why='ResourceActivity start reached the system with no Type extra')
    ed.settle(4)
    # field bursts: the same phone launched again seconds later
    t1 = ed.log_mark()
    ed.start_activity(RES_ACT, extras='')
    ed.require_log(LAUNCHED.format('ResourceActivity'), timeout=15, since=t1, why='second launch of the burst')
    ed.settle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_b(ed, r):
    """HYBRID: DIRECT LAUNCH: ResourceActivity with an empty Type (control, should NOT crash), then StickerResourcesActivity with NO extras."""
    _app_up(ed)
    t0 = ed.log_mark()
    ed.start_activity(RES_ACT, extras='--es Type ""')   # HYBRID control: empty (not null) Type -> no Kotlin null check
    ed.require_log(LAUNCHED.format('ResourceActivity'), timeout=15, since=t0, why='lab door opens ResourceActivity')
    ed.idle(3)
    ed.dev.key('KEYCODE_BACK')
    ed.idle(1.5)
    t1 = ed.log_mark()
    ed.start_activity(STK_ACT, extras='')               # trigger: Type and Category both null
    ed.require_log(LAUNCHED.format('StickerResourcesActivity'), timeout=15, since=t1,
                   why='StickerResourcesActivity start with no Type/Category extras')
    ed.settle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_1_c(ed, r):
    """FULL: Don't keep activities: start StickerResourcesActivity with NO extras, leave and come back (re-create), DKA off in finally."""
    _app_up(ed)
    ed.dont_keep_activities(True)
    try:
        t0 = ed.log_mark()
        ed.start_activity(STK_ACT, extras='')
        ed.require_log(LAUNCHED.format('StickerResourcesActivity'), timeout=15, since=t0,
                       why='StickerResourcesActivity start with no extras')
        ed.idle(2)
        t1 = ed.log_mark()
        ed.dev.key('KEYCODE_HOME')
        ed.wait_log(r'wm_on_destroy_called: \[\d+,com\.(photo\.)?myzesty', 8, since=t1)  # DKA may not take effect
        ed.idle(r.uniform(1.5, 4))
        t2 = ed.log_mark()
        ed.dev.launch()                                  # come back: the screen is created again from its (empty) intent
        ed.require_log(r'(START u0 |wm_restart_activity|wm_on_create_called).*com\.(photo\.)?myzesty', timeout=15,
                       since=t2, why='return to the app re-creates the top screen')
        ed.settle(4)
        t3 = ed.log_mark()
        ed.start_activity(RES_ACT, extras='')            # same burst on the other screen
        ed.require_log(LAUNCHED.format('ResourceActivity'), timeout=15, since=t3, why='ResourceActivity, no extras')
        ed.settle(4)
    finally:
        ed.dont_keep_activities(False)


# 2026-10-29 14:03 attempt 2
# Night Shift tapflow: Crashlytics "com.common.myzesty.realm.RealmWrapper.d" (NPE 'parameter table', performLaunchActivity)
# Field path: a launch with no Type extra (0 breadcrumbs, bursts seconds apart). onCreate ->
#   ResourcePresenter.setData(null) / setDataCategory(null, cat) -> RealmWrapper.getAllImageEditorResources(table=null) -> NPE.
# Attempt 1 left Category/Title out: Type="" threw on 'category', and a missing Title can crash on the next line instead.
# Here Title and Category are set, so 'table' is the ONLY null, as in the field message.

RES_ACT = 'com.photo.myzesty.ui.activity.resource.ResourceActivity'
STK_ACT = 'com.photo.myzesty.ui.activity.resource.StickerResourcesActivity'
LAUNCHED = r'(START u0 |wm_create_activity|wm_on_create_called).*ui\.activity\.resource\.{}'
RES_EXTRAS = '--es Title Fonts --es Category Handwriting'      # Type deliberately absent (null)
STK_EXTRAS = '--es Category Trending'                           # Type absent; Title not read by this screen


def _ready(ed):
    ed.dev.restore_env()                    # network ON: setDataCategory reaches Realm only when online
    ed.idle(2)                              # the runner's fresh-process step already brought MainActivity up


def _launch(ed, act, extras, why):
    t0 = ed.log_mark()
    ed.start_activity(act, extras=extras)
    ed.require_log(LAUNCHED.format(act.rsplit('.', 1)[1]), timeout=15, since=t0, why=why)


@scenario('nightshift', 'auto', 'tapflow')
def tf_f7a4eff3_2_a(ed, r):
    """FULL: DIRECT LAUNCH of ResourceActivity with Title+Category but NO Type -> setData(null) -> RealmWrapper NPE 'table'."""
    _ready(ed)
    ed.leave_editor()                       # field: the app is in front on its start screen, no project open
    ed.idle(1.5)
    _launch(ed, RES_ACT, RES_EXTRAS, 'ResourceActivity started with Title/Category and a null Type')
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow')
def tf_f7a4eff3_2_b(ed, r):
    """HYBRID: DIRECT LAUNCH of StickerResourcesActivity, online, Category set, NO Type -> setDataCategory(null, cat) -> RealmWrapper NPE."""
    _ready(ed)
    ed.leave_editor()
    ed.idle(1.5)
    ed.dev.network(True)                    # HYBRID: make sure the isNetworkAvailable branch (Realm read) is taken
    ed.idle(2)
    _launch(ed, STK_ACT, STK_EXTRAS, 'StickerResourcesActivity started with Category and a null Type')
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow')
def tf_f7a4eff3_2_c(ed, r):
    """FULL: field burst on a slow phone: null-Type launches of both resource screens, about 4 s apart (OnePlus8Pro / HRY-LX1T pattern)."""
    _ready(ed)
    ed.leave_editor()
    ed.idle(1.5)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        _launch(ed, RES_ACT, RES_EXTRAS, 'burst 1: ResourceActivity, null Type, slow phone')
        ed.settle(4)                        # field: the same phone launched again ~4 s later
        if ed.dev.pid() == '':
            ed.dev.launch()
            ed.idle(3)
        _launch(ed, STK_ACT, STK_EXTRAS, 'burst 2: StickerResourcesActivity, null Type, slow phone')
        ed.settle(4)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-29 14:16 attempt 3
# Night Shift tapflow: Crashlytics "com.common.myzesty.realm.RealmWrapper.d" (NPE 'parameter table' in performLaunchActivity)
# Path: a launch with no Type extra (0 breadcrumbs, bursts seconds apart).
#   ResourceActivity.onCreate:42 -> ResourcePresenter.setData(null) -> RealmWrapper.getAllImageEditorResources(table=null) (RealmWrapper.kt:102)
#   StickerResourcesActivity.onCreate:86 -> setDataCategory(null, cat) -> same function (ResourcePresenter.java:125, online only)
# Attempt 1 sent no extras at all (category null too, and a null Title can throw at line 43), so its crash was ambiguous.
# Attempt 2 had no 'nodraft' and got stuck opening a draft. Here: nodraft, Title+Category set, Type absent -> only 'table' is null.

RES_ACT = 'com.photo.myzesty.ui.activity.resource.ResourceActivity'
STK_ACT = 'com.photo.myzesty.ui.activity.resource.StickerResourcesActivity'
LAUNCHED = r'(START u0 |wm_create_activity|wm_on_create_called).*ui\.activity\.resource\.{}'
RES_EXTRAS = '--es Title Fonts --es Category Handwriting'      # Constants.Title / Constants.Category; Type left out (null)
STK_EXTRAS = '--es Title Stickers --es Category Trending'       # Type left out (null)


def _ready(ed):
    ed.dev.restore_env()                     # network ON: setDataCategory reads Realm only when online
    ed.idle(2)                               # the runner's fresh-process step already has MainActivity in front


def _launch(ed, act, extras, why):
    t0 = ed.log_mark()
    ed.start_activity(act, extras=extras)
    ed.require_log(LAUNCHED.format(act.rsplit('.', 1)[1]), timeout=15, since=t0, why=why)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_a(ed, r):
    """FULL: DIRECT LAUNCH of ResourceActivity with Title+Category but NO Type -> setData(null) -> RealmWrapper NPE 'table'."""
    _ready(ed)
    _launch(ed, RES_ACT, RES_EXTRAS, 'ResourceActivity started with Title/Category and a null Type')
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_b(ed, r):
    """HYBRID: DIRECT LAUNCH of StickerResourcesActivity, online, Category set, NO Type -> setDataCategory(null, cat) -> RealmWrapper NPE."""
    _ready(ed)
    ed.dev.network(True)                     # HYBRID: make sure the isNetworkAvailable branch (the Realm read) runs
    ed.idle(2)
    _launch(ed, STK_ACT, STK_EXTRAS, 'StickerResourcesActivity started with Category and a null Type')
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_f7a4eff3_3_c(ed, r):
    """FULL: field burst on a slow phone (OnePlus8Pro / HRY-LX1T pattern): null-Type launches of the resource screens ~4 s apart."""
    _ready(ed)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        _launch(ed, RES_ACT, RES_EXTRAS, 'burst 1: ResourceActivity, null Type, slow phone')
        ed.settle(4)                         # field: the same phone launched again ~4 s later
        if ed.dev.pid() == '':
            t0 = ed.log_mark()
            ed.dev.launch()
            ed.require_log(r'Displayed com\.myzesty[./]', timeout=25, since=t0, why='app back up for burst 2')
            ed.idle(2)
        _launch(ed, STK_ACT, STK_EXTRAS, 'burst 2: StickerResourcesActivity, null Type, slow phone')
        ed.settle(4)
    finally:
        ed.dev.slow_phone(0)
