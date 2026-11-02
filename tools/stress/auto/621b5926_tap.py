# Night Shift tap repros for 621b5926412e07c4e8a50c9aaa51aaf0 (from the engine repro + full field log)


# 2026-10-29 18:46 attempt 1
VE_PLAY = r've_play_pause_btn|MsgResumePlaying|MsgPausePlaying'


def _tap_play(ed, why, pat=r'MsgResumePlaying|MsgPausePlaying'):
    t0 = ed.log_mark()
    ed.ui.tap(('id:play',), timeout=8)
    ed.require_log(pat, timeout=6, since=t0, why=why)


def _full_editor_then_back(ed):
    """we_full_editor_btn and 'back' logged 11 ms apart in the field: isWizardEditor=false, wizard strip still up."""
    s = ed.ui.wait(('id:full_editor',), timeout=10)
    if s is None:
        raise UIError('no Full Editor button (id full_editor) in the Wizard editor')
    t0 = ed.log_mark()
    ed.dev.tap(*s.find(('id:full_editor',)).center)
    ed.dev.key('KEYCODE_BACK')
    ed.require_log(r'MsgPausePlaying|MsgPreviewState|MsgUpdateVideoVolume', timeout=6, since=t0,
                   why='full editor tap (pausePlayer) then back')
    ed.idle(2)


def _drag(ed, i, j, why, sort=r'MsgSortMedia: media_layer 0'):
    t0 = ed.log_mark()
    ed.wizard_drag(i, j)
    ed.require_log(sort, timeout=8, since=t0, why=why + ': sortMedia from the strip list')
    ed.require_log(r'MsgSeekVideo: media_layer 0 media_id \d', timeout=6, since=t0,
                   why=why + ': onItemClicked -> seekVideoIndex')


def _delete(ed, why, pat=r'MsgDetachMedia: media_layer 0 media_id 0'):
    t0 = ed.log_mark()
    ed.wizard_delete()
    ed.require_log(pat, timeout=10, since=t0, why=why)


def _endgame(ed):
    """Field tail: plays end at once (empty timeline), thumb 0 -> seek 0 (harmless), thumb 1 -> seek 1 (crash)."""
    for k in range(3):
        _tap_play(ed, f'play on empty timeline {k + 1}/3', pat=r'MsgAtEnd')
        ed.idle(0.8)
    t0 = ed.log_mark()
    ed.wizard_select(0)
    ed.require_log(r'MsgSeekVideo: media_layer 0 media_id 0', timeout=6, since=t0, why='stale thumb 0 -> seek 0')
    ed.idle(1.5)
    t0 = ed.log_mark()
    ed.wizard_select(1)                                  # TRIGGER: seekVideoIndex(1) on an empty layer
    ed.require_log(r'MsgSeekVideo: media_layer 0 media_id 1', timeout=6, since=t0, why='stale thumb 1 -> seek 1')
    ed.idle(5)


def _drift_by_taps(ed):
    _tap_play(ed, 'we play', pat=r'MsgResumePlaying')
    ed.idle(3)
    _full_editor_then_back(ed)
    _tap_play(ed, 've play (isWizardEditor now false)', pat=r'MsgResumePlaying')
    ed.idle(2)
    _tap_play(ed, 've pause', pat=r'MsgPausePlaying')
    if ed.ui.wait(('id:thumbRecyclerView',), timeout=8) is None:
        raise UIError('wizard strip gone after Full Editor + back: the field strip stayed visible')
    _drag(ed, 0, 1, 'drag 1 (2 clips, in sync)')
    _delete(ed, 'we_delete_btn 1: engine detaches clip 0, strip not refreshed')
    _tap_play(ed, 've play after delete', pat=r'MsgResumePlaying')
    ed.idle(2)
    _tap_play(ed, 've pause', pat=r'MsgPausePlaying')
    _drag(ed, 0, 1, 'drag 2 (stale ids)', sort=r'sort_list size doesn.t match')
    _drag(ed, 1, 0, 'drag 3 (stale ids, copies 2-clip list into activity)', sort=r'sort_list size doesn.t match')
    _delete(ed, 'we_delete_btn 2: last engine clip detached', pat=r'media_id bigger than visual objects number')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_621b5926_1_a(ed, r):
    """FULL: Crashlytics VisualMedia::get_duration: Wizard 2 clips, Full Editor+back, drag, delete, stale drags, delete, play, thumb 0, thumb 1."""
    ed.open_wizard(2)
    if len(ed.wizard_thumbs()) < 2:
        raise UIError('wizard needs 2 clip thumbnails')
    _drift_by_taps(ed)
    _endgame(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_621b5926_1_b(ed, r):
    """HYBRID: Crashlytics VisualMedia::get_duration: engine emptied by direct detaches, strip keeps 2 thumbs, real thumb taps seek 0 then 1."""
    ed.open_wizard(2)
    if len(ed.wizard_thumbs()) < 2:
        raise UIError('wizard needs 2 clip thumbnails')
    _tap_play(ed, 'we play', pat=r'MsgResumePlaying')
    ed.idle(2)
    _tap_play(ed, 'we pause', pat=r'MsgPausePlaying')
    t0 = ed.log_mark()
    ed.jni("pausePlaying();detachMedia(0,0);sleep(300)", thread="bg")          # HYBRID: drift (delete 1)
    ed.require_log(r'MsgDetachMedia: media_layer 0 media_id 0', timeout=8, since=t0, why='hybrid detach 1')
    t0 = ed.log_mark()
    ed.jni("detachMedia(0,0);sleep(300)", thread="bg")                         # HYBRID: drift (delete 2)
    ed.require_log(r'MsgDetachMedia: media_layer 0 media_id 0', timeout=8, since=t0, why='hybrid detach 2')
    if len(ed.wizard_thumbs()) < 2:
        raise UIError('strip no longer shows 2 thumbnails')
    _endgame(ed)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_621b5926_1_c(ed, r):
    """FULL: Crashlytics VisualMedia::get_duration: path a on a slow phone (vivo V2029) so Full Editor and back land together."""
    ed.open_wizard(2)
    if len(ed.wizard_thumbs()) < 2:
        raise UIError('wizard needs 2 clip thumbnails')
    ed.dev.slow_phone(30)
    try:
        _drift_by_taps(ed)
    finally:
        ed.dev.slow_phone(0)
    _endgame(ed)
