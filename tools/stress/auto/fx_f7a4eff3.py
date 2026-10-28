# Night Shift lab fixture builder for f7a4eff3 (try 3)

def _fx_f7a4eff3_proof(ed, mark):
    """The editor is up: screen ids first, then any com.myzesty activity line since mark."""
    if ed.in_editor(ed.screen()):
        ed.require_log(r'wm_on_(create|resume)_called.*com\.myzesty|Displayed com\.myzesty/|ActivityTaskManager.*com\.myzesty',
                       30, since=mark, why='the test draft is open in the editor (project state on the phone)')
        return
    ed.require_log(r'wm_on_resume_called.*com\.myzesty[./]\S*(Player|Editor|Base)|Displayed com\.myzesty/\S*(Player|Editor)',
                   60, since=mark, why='the test draft is open in the editor (project state on the phone)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_f7a4eff3_fx(ed, r):
    """Crashlytics RealmWrapper.d NPE 'parameter table' at launch (1.25.2/800054890, Android 11): fixture = unchanged test draft."""
    ed.fixture_begin()
    # The field crash happens at cold launch, before any project is opened: no clips, overlays or edits are needed.
    # The fixture is just the plain lab test draft, opened once and saved, so recipes start from known project state.
    ed.step('open the lab test draft')
    mark = ed.log_mark()
    ed.open_draft()
    ed.idle(2)
    _fx_f7a4eff3_proof(ed, mark)
    ed.save_fixture('f7a4eff3', 'unchanged lab test draft; the RealmWrapper NPE is a launch-path crash from stored app state and needs no project edits')
