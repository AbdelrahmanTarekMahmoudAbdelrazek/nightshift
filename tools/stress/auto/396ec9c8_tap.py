# Night Shift tap repros for 396ec9c89dd7daa94df5060a72e329ce (from the engine repro + full field log)


# 2026-10-29 22:29 attempt 1
# Night Shift tapflow 396ec9c8: NPE String.equals in ResourcePresenter.mapToCategoryApi at launch.
# Path: StickerResourcesActivity.onCreate:86 -> setDataCategory(Type, getStringExtra("Category")) -> mapToCategoryApi(null).
# Only in-app caller (StickersFragment.openResources) always passes Type="STICKERS", Category="Trending".

STICKER_RES = 'com.photo.myzesty.ui.activity.resource.StickerResourcesActivity'
FIELD_EXTRAS = '--es Type "STICKERS" --es Category "Trending"'
CREATED = r'wm_on_create_called: \[\d+,com\.(photo\.)?myzesty[./].*StickerResourcesActivity'


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_396ec9c8_1_a(ed, r):
    """FULL: (LIFECYCLE control) Crashlytics mapToCategoryApi NPE: open the sticker screen with the app's own extras, then restore it after process death."""
    ed.dev.restore_env()
    ed.step('open StickerResourcesActivity exactly as StickersFragment.openResources does')
    t0 = ed.log_mark()
    ed.start_activity(STICKER_RES, extras=FIELD_EXTRAS, expect_crash=False)
    ed.require_log(CREATED, timeout=20, since=t0, why='sticker screen created with Type+Category')
    ed.idle(r.uniform(2, 4))                         # let setDataCategory load the Trending stickers
    ed.step('process death while the sticker screen is on top, then back from recents')
    t1 = ed.log_mark()
    ed.restore_from_recents()                        # HOME + am kill + relaunch: Android recreates the screen
    ed.require_log(CREATED, timeout=30, since=t1, why='sticker screen restored after process death')
    ed.idle(3)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_396ec9c8_1_b(ed, r):
    """HYBRID: (DIRECT LAUNCH) Crashlytics mapToCategoryApi NPE: start StickerResourcesActivity without the Category extra -> setDataCategory(null)."""
    ed.dev.restore_env()
    ed.dev.launch()                                  # app process up, as on the field phones (session_start at T-0)
    ed.idle(4)
    ed.step('direct launch with NO extras (crawler / automated launch)')
    t0 = ed.log_mark()
    ed.start_activity(STICKER_RES, extras='')        # Category null -> mapToCategoryApi(null).equals -> NPE
    ed.require_log(CREATED, timeout=20, since=t0, why='sticker screen created without extras')
    ed.idle(4)
    ed.step('direct launch with Type only (Category missing)')
    ed.dev.launch()
    ed.idle(3)
    t1 = ed.log_mark()
    ed.start_activity(STICKER_RES, extras='--es Type "STICKERS"')
    ed.require_log(CREATED, timeout=20, since=t1, why='sticker screen created with Type only')
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_396ec9c8_1_c(ed, r):
    """HYBRID: Crashlytics mapToCategoryApi NPE: Don't-keep-activities leave/return on the sticker screen, then a launch with Category missing."""
    ed.dev.restore_env()
    ed.dont_keep_activities(True)
    try:
        ed.step('sticker screen with field extras, leave and come back (activity destroyed in background)')
        t0 = ed.log_mark()
        ed.start_activity(STICKER_RES, extras=FIELD_EXTRAS, expect_crash=False)
        ed.require_log(CREATED, timeout=20, since=t0, why='sticker screen created with Type+Category')
        ed.idle(r.uniform(1, 3))
        t1 = ed.log_mark()
        ed.dev.key('KEYCODE_HOME')
        ed.wait_log(r'wm_on_destroy_called: .*StickerResourcesActivity', 8, since=t1)
        ed.idle(r.uniform(2, 5))
        t2 = ed.log_mark()
        ed.dev.launch()                              # recents/launcher return recreates the top activity
        ed.require_log(CREATED, timeout=20, since=t2, why='sticker screen recreated after DKA destroy')
        ed.idle(3)
        ed.step('slow phone + launch with Category missing (field: 2 test-like devices, no breadcrumbs)')
        ed.dev.slow_phone(r.randint(25, 40))
        t3 = ed.log_mark()
        ed.start_activity(STICKER_RES, extras='--es Type "STICKERS" --es Title "Stickers"')
        ed.require_log(CREATED, timeout=30, since=t3, why='sticker screen created without Category')
        ed.idle(4)
    finally:
        ed.dev.slow_phone(0)
        ed.dont_keep_activities(False)
