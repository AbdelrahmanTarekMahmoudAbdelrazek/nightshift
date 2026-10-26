# Night Shift lab fixture builder for f7a4eff3 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_fx(ed, r):
    """Fixture for Crashlytics RealmWrapper.d NPE 'parameter table' (cold launch, Android 11): the plain lab test draft."""
    ed.fixture_begin()
    ed.grant_permissions()
    mark = ed.log_mark()
    ed.open_draft(timeout=240)                 # recorded test draft by id; it rebuilds a broken draft or creates one if none exist
    ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', 180, since=mark,
                   why='the engine loaded a saved project with at least one clip on layer 0')
    ed.settle(3)
    ed.save_fixture('f7a4eff3', 'Unchanged lab test draft (>=1 video on layer 0, no edits). The field crash is at cold launch '
                                '(performLaunchActivity, RealmWrapper table=null) and needs no editor state')
