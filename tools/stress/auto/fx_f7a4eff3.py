# Night Shift lab fixture builder for f7a4eff3 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_fx(ed, r):
    """Fixture for Crashlytics RealmWrapper.d (NPE 'parameter table' at launch): unchanged lab test draft, no edits."""
    ed.fixture_begin()
    # The field crash is a cold-launch crash driven by on-device state, not by project content.
    # The only project state the recipes need is a valid draft that opens in the editor.
    # The last attempt's process died right after app-up, before any editor step (the known lab
    # MainActivity.onCreate crash on alternate cold launches). Start one clean cold launch and
    # wait until the launcher is really displayed before touching anything.
    ed.step('clean cold launch')
    ed.dev.force_stop()
    time.sleep(2.0)
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Displayed com\.myzesty/', 20, since=mark,
                   why='the app process survives its cold launch and shows its first activity')
    ed.idle(3)

    ed.step('open the lab test draft')
    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r'MsgAddVideo', 40, since=mark,
                   why='the test draft loaded its clips into the engine (editor is up with a real project)')
    ed.idle(2)

    ed.save_fixture('f7a4eff3', 'unchanged lab test draft; crash is a launch-time Realm NPE that needs stored app data, not project content')
