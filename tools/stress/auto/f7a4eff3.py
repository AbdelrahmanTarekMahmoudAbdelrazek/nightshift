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
