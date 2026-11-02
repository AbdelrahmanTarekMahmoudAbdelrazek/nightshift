# Night Shift lab fixture builder for f7a4eff3 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_fx(ed, r):
    """Fixture for Crashlytics RealmWrapper.d (NPE 'parameter table'): app up in foreground with Realm initialised, unchanged test draft."""
    ed.fixture_begin()
    # Checkpoint 1: a cold start we observe ourselves. Mark BEFORE the launch so the
    # Displayed / wm_on_* lines are inside the window (last try marked after launch).
    ed.step('fixture: cold launch, app in foreground')
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Displayed com\.myzesty[./]|wm_on_(create|resume)_called.*com\.myzesty[./]'
                   r'|START u0 .*cmp=com\.myzesty/',
                   timeout=45, since=mark,
                   why='checkpoint 1: com.myzesty launched and its home activity shown')
    ed.idle(3)
    if not ed.dev.pid():
        raise AssertionError('com.myzesty is not running 3 s after launch (PairIP kill or sideloaded build?)')
    # The field crash needs no video project. Keep the lab test draft unchanged,
    # just open it so save_fixture has a project to record.
    ed.step('fixture: open lab test draft (unchanged)')
    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r'wm_on_resume_called.*com\.myzesty[./]|Displayed com\.myzesty[./]',
                   timeout=30, since=mark,
                   why='editor resumed in the same process: app foreground, Realm up')
    if not ed.dev.pid():
        raise AssertionError('com.myzesty died while opening the test draft')
    ed.save_fixture('f7a4eff3', 'unchanged lab test draft; crash is a direct ResourceActivity launch with no Type extra, needs only the app running in the foreground')
