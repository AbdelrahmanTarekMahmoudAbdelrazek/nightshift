# Night Shift lab fixture builder for 396ec9c8 (try 3)

def _fx_396ec9c8_new_project(ed):
    """Empty My Projects: dev start menu -> REVAMP UI -> (chooser) Full Editor or New Project tab -> newest video -> editor."""
    ed.step('fixture: no project yet, creating one via Full Editor')
    s = ed.screen()
    if s is not None and not s.has(('id:full_editor_btn', 'textc:new project')) and s.has(T.HOME_TO_PROJECTS):
        ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)          # launcher dev menu -> BaseVideoEditorActivity
        time.sleep(3)
    ed.ui.tap(('id:full_editor_btn', 'textc:new project'), timeout=20)   # chooser nav hides the tabs
    time.sleep(1.5)
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=30)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        time.sleep(1.5)
        s = ed.ui.wait('id:gridrl', timeout=15) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if tiles:
        ed.dev.tap(*tiles[0].center)
        time.sleep(1)
        ed._picker_confirm()
    end = time.time() + 150                                     # first import = real transcode (>20 s on the phone)
    while time.time() < end:
        sc = ed.screen()
        if ed.in_editor(sc) and not sc.has(T.LOADER):
            return
        if sc is not None and sc.has(T.DISMISS):
            ed.dev.tap(*sc.find(T.DISMISS).center)
        elif sc is not None and sc.has('id:full_editor'):       # wizard editor -> Full Editor
            ed.dev.tap(*sc.find('id:full_editor').center)
        time.sleep(2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_fx(ed, r):
    """Fixture for Crashlytics ResourcePresenter.mapToCategoryApi NPE (launch-time): one plain saved project, no editor activity needed."""
    ed.fixture_begin()
    ed.grant_permissions()
    mark = ed.log_mark()
    if ed.drafts():
        ed.open_draft()                                         # the recorded test draft
    else:
        _fx_396ec9c8_new_project(ed)
    ed.require_log(r'MsgCreatePlayer|MsgAddVideo|MsgTrimVideo', 60, since=mark,
                   why='a saved project with at least one clip is loaded by the engine')
    ed.idle(3)
    ed.save_fixture('396ec9c8', 'One saved project (>=1 video clip on layer 0), no edits; the crash is at cold launch so no editor state is required')
