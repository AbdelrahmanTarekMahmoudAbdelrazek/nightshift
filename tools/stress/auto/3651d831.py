# Night Shift auto repros for 3651d831831e05d51ad101212797a634


# 2026-10-10 13:27 level 2 attempt 1
_3651d831_PKG = 'com.myzesty'
_3651d831_RECEIVERS = (   # exported, callable by the shell (DUMP permission), merged into the app by androidx
    'androidx.profileinstaller.ProfileInstallReceiver -a androidx.profileinstaller.action.BENCHMARK_OPERATION',
    'androidx.work.impl.diagnostics.DiagnosticsReceiver -a androidx.work.diagnostics.REQUEST_DIAGNOSTICS',
)


def _3651d831_kill_in_background(ed, camera=True):
    """User leaves MyZesty (Home, opens the camera); Android then reclaims the cached process (not force-stopped)."""
    ed.mon.allow_death = True                         # the kill is ours; an ANR is still recorded
    ed.dev.key('KEYCODE_HOME')
    if camera:
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
    ed.idle(3)
    for _ in range(5):
        ed.dev.sh(f'am kill {_3651d831_PKG}')
        ed.idle(1)
        if ed.dev.pid() == '':
            return
    ed.log('    process still alive after am kill; starting it anyway')


def _3651d831_broadcast(ed):
    """Foreground broadcast (10 s timeout) to a cold process: 'Start proc ... for broadcast'."""
    for rc in _3651d831_RECEIVERS:
        out = ed.dev.sh(f'am broadcast -f 0x10000000 -n {_3651d831_PKG}/{rc}')
        if 'result=' in out or 'Broadcast completed' in out or ed.dev.pid() != '':
            return
    ed.log('    no receiver accepted the broadcast')


def _3651d831_jobs(ed):
    """The app's own scheduled jobs (WorkManager / Firebase): 'Start proc ... for job'."""
    ids = []
    for line in ed.dev.sh('dumpsys jobscheduler').splitlines():
        if 'JOB #' in line and _3651d831_PKG + '/' in line:
            ids.append(line.split('/', 1)[1].split(':', 1)[0].strip())
    for jid in dict.fromkeys(ids):
        ed.dev.sh(f'cmd jobscheduler run -f {_3651d831_PKG} {jid}')
    return len(ids)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l2_1_a(ed, r):
    """realme Note 80 / RMX5313 (Play+Crashlytics, 1.25.1 800054867): killed in background, cold-started for a broadcast."""
    ed.dev.launch(); ed.idle(8)                       # a normal session first, so the SDKs have their state
    for i in range(4):
        _3651d831_kill_in_background(ed)
        ed.step(f'cold start {i + 1}: foreground broadcast to the dead process')
        _3651d831_broadcast(ed)
        ed.idle(15)                                   # foreground broadcast timeout is 10 s
    ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l2_1_b(ed, r):
    """Other events in the group (WorkDatabase$Companion.create path): killed in background, cold-started for a job."""
    ed.dev.launch(); ed.idle(8)
    for i in range(4):
        _3651d831_kill_in_background(ed)
        ed.step(f'cold start {i + 1}: run the app jobs')
        if _3651d831_jobs(ed) == 0:
            ed.log('    no scheduled jobs for the app; using a broadcast instead')
            _3651d831_broadcast(ed)
        ed.idle(25)
    ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l2_1_c(ed, r):
    """realme Note 80 (process_state BACKGROUND): phone back online wakes the dead app (FCM/WorkManager) plus a broadcast."""
    ed.dev.launch(); ed.idle(8)
    try:
        for i in range(3):
            ed.dev.network(False)
            _3651d831_kill_in_background(ed)
            ed.idle(r.uniform(5, 15))
            ed.step(f'cold start {i + 1}: network back, jobs + broadcast at once')
            ed.dev.network(True)
            ed.idle(r.uniform(0.5, 2))
            _3651d831_jobs(ed)
            _3651d831_broadcast(ed)
            ed.idle(20)
    finally:
        ed.dev.restore_env()


# 2026-10-10 13:38 level 2 attempt 2
_3651d831_PKG = 'com.myzesty'
_3651d831_DIAG = 'androidx.work.impl.diagnostics.DiagnosticsReceiver -a androidx.work.diagnostics.REQUEST_DIAGNOSTICS'
_3651d831_FCM = 'com.google.firebase.iid.FirebaseInstanceIdReceiver -a com.google.android.c2dm.intent.RECEIVE'
_3651d831_TAGS = 'superwall|referrer|WM-|nativeloader|linker|billing|FirebaseApp|FacebookSdk|Displayed'


def _3651d831_setup(ed):
    """Just-updated app: no AOT code (verify only), as after the Play update to 1.25.1. Returns (su, uid)."""
    su = next((p for p in ('su 0 sh -c', 'su -c') if 'uid=0' in ed.dev.sh(f"{p} 'id' 2>/dev/null")), '')
    uid = ed.dev.sh(f'pm list packages -U {_3651d831_PKG}').split('uid:')[-1].split(',')[0].strip()
    ed.mon.allow_death = True                          # our kills are not crashes; an ANR is still recorded
    ed.dev.force_stop()
    ed.dev.sh(f'cmd package compile --reset {_3651d831_PKG}', timeout=120)
    ed.log(f'    root={"yes" if su else "no"} uid={uid}')
    return su, uid


def _3651d831_go_cold(ed, su, camera=True):
    """User leaves the app (Home, camera); Android reclaims it; its pages fall out of the page cache."""
    ed.dev.key('KEYCODE_HOME')
    if camera:
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
    ed.idle(2)
    for _ in range(5):
        if ed.dev.pid() == '':
            break
        ed.dev.sh(f'am kill {_3651d831_PKG}'); ed.idle(1)
    if su:
        ed.dev.sh(f"{su} 'sync; echo 3 > /proc/sys/vm/drop_caches'")
    ed.idle(1)


def _3651d831_fire(ed, su, rc, root=False):
    """Foreground (10 s) broadcast, sent in the background so we can watch main while onCreate runs."""
    cmd = f'am broadcast -f 0x10000020 -n {_3651d831_PKG}/{rc}'
    ed.dev.sh(f"{su} 'nohup {cmd} >/dev/null 2>&1 &'" if root and su else f'nohup {cmd} >/dev/null 2>&1 &')


def _3651d831_watch(ed, su, uid):
    """Checkpoints 2-4: main-thread samples during onCreate, then the new pid's SDK log lines (by uid)."""
    pid = ''
    for _ in range(25):
        pid = ed.dev.pid()
        if pid:
            break
        time.sleep(0.2)
    ed.log(f'    new pid: {pid or "none (no Start proc)"}')
    last = 0
    for t in ((1.5, 4, 7) if pid and su else ()):
        time.sleep(t - last); last = t
        st = ed.dev.sh(f"{su} 'debuggerd -j {pid} 2>/dev/null' | grep -A7 '^\"main\"' | head -8")
        ed.log(f'    +{t}s main: ' + ' | '.join(l.strip()[:90] for l in st.splitlines()[1:7]))
    ed.idle(max(0, 12 - last))                        # past the 10 s foreground-broadcast timeout
    out = ed.dev.sh(f'logcat -d --uid={uid} -t 800 2>/dev/null | grep -iE "{_3651d831_TAGS}" | tail -25')
    for l in out.splitlines():
        ed.log('    app: ' + l[:170])
    return pid


def _3651d831_restore(ed):
    ed.dev.sh(f'cmd package compile -m speed-profile -f {_3651d831_PKG}', timeout=240)
    ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l2_2_a(ed, r):
    """realme Note 80 / RMX5313 (Play+Crashlytics 800054867) + WorkDatabase.create event: uncompiled app, cold page cache, background WorkManager broadcast while the camera starts."""
    su, uid = _3651d831_setup(ed)
    try:
        for i in range(3):
            _3651d831_go_cold(ed, su, camera=False)
            ed.step(f'cold start {i + 1}: WorkManager broadcast to the dead app, camera opening at once')
            _3651d831_fire(ed, su, _3651d831_DIAG)
            ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
            _3651d831_watch(ed, su, uid)
    finally:
        _3651d831_restore(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l2_2_b(ed, r):
    """realme Note 80 event (process_state BACKGROUND, no breadcrumbs): FCM push wakes the killed, uncompiled app."""
    su, uid = _3651d831_setup(ed)
    try:
        for i in range(3):
            _3651d831_go_cold(ed, su, camera=True)
            ed.idle(r.uniform(3, 8))
            ed.step(f'cold start {i + 1}: FCM push to the dead app')
            _3651d831_fire(ed, su, _3651d831_FCM if su else _3651d831_DIAG, root=True)
            _3651d831_watch(ed, su, uid)
    finally:
        _3651d831_restore(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l2_2_c(ed, r):
    """WorkDatabase$Companion.create / Runtime.nativeLoad events: the app's own scheduled jobs cold-start it; FCM push if no job does."""
    su, uid = _3651d831_setup(ed)
    try:
        for i in range(3):
            _3651d831_go_cold(ed, su, camera=True)
            ed.step(f'cold start {i + 1}: run the app jobs (must show Start proc ... for job)')
            ids = [l.split('/', 1)[1].split(':', 1)[0].strip() for l in
                   ed.dev.sh(f'dumpsys jobscheduler {_3651d831_PKG}').splitlines()
                   if 'JOB #' in l and '/' in l]
            for jid in dict.fromkeys(ids):
                ed.dev.sh(f'nohup cmd jobscheduler run -f {_3651d831_PKG} {jid} >/dev/null 2>&1 &')
            ed.idle(1.5)
            if ed.dev.pid() == '':
                ed.log(f'    {len(ids)} jobs, none started the process; FCM push instead')
                _3651d831_fire(ed, su, _3651d831_FCM if su else _3651d831_DIAG, root=True)
            _3651d831_watch(ed, su, uid)
    finally:
        _3651d831_restore(ed)


# 2026-10-10 13:45 level 3 attempt 1
_3651d831_PKG = 'com.myzesty'
_3651d831_RC = 'androidx.profileinstaller.ProfileInstallReceiver -a androidx.profileinstaller.action.BENCHMARK_OPERATION'
_3651d831_DIAG = 'androidx.work.impl.diagnostics.DiagnosticsReceiver -a androidx.work.diagnostics.REQUEST_DIAGNOSTICS'
_3651d831_SPIN = "timeout 40 sh -c 'while :; do :; done' >/dev/null 2>&1 &"


def _3651d831_setup(ed):
    """Just-updated app on a slow phone: no AOT code, so every <clinit> / Superwall / billing class runs interpreted."""
    ed.mon.allow_death = True                          # our kills are not crashes; the ANR is still recorded
    ed.dev.force_stop()
    ed.dev.sh(f'cmd package compile -m verify -f {_3651d831_PKG}', timeout=180)
    su = next((p for p in ('su 0 sh -c', 'su -c') if 'uid=0' in ed.dev.sh(f"{p} 'id' 2>/dev/null")), '')
    return su, int((ed.dev.sh('nproc').strip() or '8'))


def _3651d831_cold_start(ed, su, spinners, io=False, rc=_3651d831_RC, extra=''):
    """Dead process + device under CPU/IO load -> foreground broadcast (10 s timeout) cold-starts it in the background."""
    ed.dev.sh(f'am kill {_3651d831_PKG}'); ed.idle(1)
    if ed.dev.pid():
        ed.dev.force_stop(); ed.idle(1)
    if io:
        ed.dev.sh("timeout 40 sh -c 'while :; do dd if=/dev/zero of=/sdcard/ns3651.bin bs=4m count=128 "
                  "oflag=direct 2>/dev/null; done' >/dev/null 2>&1 &")
        if su:
            ed.dev.sh(f"{su} 'timeout 40 sh -c \"while :; do echo 3 > /proc/sys/vm/drop_caches; sleep 0.7; done\" "
                      f">/dev/null 2>&1 &'")
    ed.dev.sh(f'for i in $(seq {spinners}); do {_3651d831_SPIN} done')
    if extra:
        ed.dev.sh(extra)
    ed.idle(1.5)                                       # load is running before handleBindApplication starts
    ed.dev.sh(f'nohup am broadcast -f 0x10000020 -n {_3651d831_PKG}/{rc} >/dev/null 2>&1 &')
    ed.idle(1)
    line = ed.dev.sh(f'logcat -d -b system -t 300 | grep "Start proc.*{_3651d831_PKG}" | tail -1').strip()
    ed.log(f'    {line[-150:]}')
    if 'for broadcast' not in line or 'DiagnosticsReceiver' in line and rc == _3651d831_RC:
        ed.log('    WARNING: not a foreground-broadcast cold start')
    pid = ed.dev.pid()
    for t in (2, 4, 6):                                # checkpoint 3: where main is during onCreate
        ed.idle(2)
        if su and pid:
            st = ed.dev.sh(f"{su} 'debuggerd -j {pid} 2>/dev/null' | grep -A6 '^\"main\"' | head -7")
            ed.log(f'    +{t}s main: ' + ' | '.join(l.strip()[:80] for l in st.splitlines()[1:6]))
    ed.idle(20)                                        # 10 s timeout + soft extension + ANR dump
    ed.dev.sh("pkill -f 'while :; do' 2>/dev/null")


def _3651d831_restore(ed):
    ed.dev.sh("pkill -f 'while :; do' 2>/dev/null")
    ed.dev.sh(f'cmd package compile -m speed-profile -f {_3651d831_PKG}', timeout=240)
    ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l3_1_a(ed, r):
    """realme Note 80 / RMX5313 (Play+Crashlytics 800054867): uncompiled app cold-started for a foreground broadcast under rising CPU load, main still in Superwall.configure."""
    su, cores = _3651d831_setup(ed)
    try:
        for i, k in enumerate((1, 1.5, 2, 2.5, 3, 4, 6)):  # first ANR lands near the end of onCreate, then earlier
            ed.step(f'cold start {i + 1}: foreground broadcast, {k}x CPU spinners per core')
            _3651d831_cold_start(ed, su, int(cores * k))
    finally:
        _3651d831_restore(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l3_1_b(ed, r):
    """Runtime.nativeLoad / WorkDatabase$Companion.create events of the same issue: IO-starved cold start (cold page cache, disk writes) + CPU load + memory pressure."""
    su, cores = _3651d831_setup(ed)
    try:
        for i, k in enumerate((0.5, 1, 1.5, 2, 3, 4)):
            ed.step(f'cold start {i + 1}: foreground broadcast, IO storm + {k}x CPU spinners')
            _3651d831_cold_start(ed, su, int(cores * k), io=True,
                                 extra=f'am send-trim-memory {_3651d831_PKG} RUNNING_CRITICAL >/dev/null 2>&1 &')
    finally:
        ed.dev.sh('dd if=/dev/zero of=/sdcard/ns3651.bin bs=1 count=0 2>/dev/null')   # shrink scratch file (no delete)
        _3651d831_restore(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3651d831_l3_1_c(ed, r):
    """realme Note 80 event (BACKGROUND, no breadcrumbs): two broadcasts (WorkManager + profile) cold-start the uncompiled app at once on a saturated CPU."""
    su, cores = _3651d831_setup(ed)
    try:
        for i, k in enumerate((3, 4, 5, 6, 8)):
            ed.step(f'cold start {i + 1}: profile + WorkManager foreground broadcasts, {k}x CPU spinners')
            _3651d831_cold_start(ed, su, int(cores * k), rc=_3651d831_RC,
                                 extra=f'nohup am broadcast -f 0x10000020 -n {_3651d831_PKG}/{_3651d831_DIAG} >/dev/null 2>&1 &')
    finally:
        _3651d831_restore(ed)
