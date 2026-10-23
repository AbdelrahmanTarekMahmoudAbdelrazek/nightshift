# Night Shift live-agent recipes for 2bc43cd6 (turbo)

# 2026-10-14 14:17

@scenario('nightshift', 'auto', 'nodraft')
def ns_2bc43cd6_live1(ed, r):
    """Reproduce the SIGSEGV in VisualTimeLine::get_media_starting_time on the MsgLooper thread through real use. Rotating QuickCutActivity with 2 or more cl (live agent run, replayed)"""
    live_replay(ed, [{'args': {'n': 3}, 'do': 'open_slideshow', 'result': 'slideshow open', 't': 4.7},
     {'args': {'pattern': 'MsgCreatePlayer', 'then': 'none', 'timeout': 15},
      'do': 'arm',
      'result': 'armed: MsgCreatePlayer -> none',
      't': 21.0},
     {'args': {'seconds': 3}, 'do': 'idle', 'result': 'ok', 't': 25.1},
     {'args': {'landscape': True}, 'do': 'rotate', 'result': 'ok', 't': 33.5}])
