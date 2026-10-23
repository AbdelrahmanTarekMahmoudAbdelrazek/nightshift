# Night Shift live-agent recipes for b0624779 (turbo)

# 2026-10-14 19:34

@scenario('nightshift', 'auto', 'nodraft')
def ns_b0624779_live1(ed, r):
    """Reproduce the null-looper crash (MsgLooper::Set -> MsgLooper::QueueMessage, fault addr 0x30) the natural field way. On a low-RAM phone, opening the Co (live agent run, replayed)"""
    live_replay(ed, [{'args': {}, 'do': 'open_draft', 'result': 'editor open (test project)', 't': 9.7},
     {'args': {'on': True},
      'do': 'reclaim_activities',
      'result': 'activities destroyed when they leave the screen',
      't': 26.4},
     {'args': {'pattern': 'MsgLooper::~MsgLooper ended', 'then': 'none', 'timeout': 15},
      'do': 'arm',
      'result': 'armed: MsgLooper::~MsgLooper ended -> none',
      't': 52.6},
     {'args': {'target': 'id:cover_thumbnail'}, 'do': 'tap', 'result': 'tapped', 't': 57.3},
     {'args': {'pattern': 'MsgLooper::~MsgLooper ended', 'then': 'none', 'timeout': 15},
      'do': 'when_log',
      'result': 'log line never came | ARMED WATCH FIRED: saw  11893 13118 I MsgLooper.cpp: '
                'MsgLooper::~MsgLooper ended -> none',
      't': 63.5},
     {'args': {'x': 451, 'y': 1480}, 'do': 'tap_xy', 'result': 'tapped', 't': 84.6}])
