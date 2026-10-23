"""Parallel lab lanes: Android emulators next to the physical phone, so repro runs go side by side instead of one
after another. Tested 2026-10-12: the AVD (arm64, -gpu host) reproduces the native crash 2bc43cd6 with the exact field
frames (VisualTimeLine::get_media_starting_time <- MsgLooper::ProcessMessages) in ~2 min, first try.

The worker pins its own adb to the phone (ANDROID_SERIAL); every lane command names its emulator. Results of a lane go
to stress_results/lanes/<serial>/<time>/ so parallel runs never share a folder."""
import os
import subprocess
import threading
import time

SDK = os.path.expanduser(os.environ.get('ANDROID_HOME') or '~/Library/Android/sdk')
EMU = os.path.join(SDK, 'emulator', 'emulator')
AVD = os.environ.get('NS_LANE_AVD', 'Medium_Phone_API_36')


def _adb(serial, *a, t=120):
    try:
        r = subprocess.run(['adb', '-s', serial, *a], capture_output=True, text=True, timeout=t)
        out = (r.stdout + r.stderr).strip()
        return out if out or not r.returncode else f'(no output, adb exit {r.returncode})'
    except subprocess.TimeoutExpired:
        return 'TIMEOUT'
    except Exception as e:                             # adb missing / killed: say so instead of an empty reason
        return f'(adb failed: {e})'


def available():
    return os.path.exists(EMU)


HEALTH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'lanes_health.json')
GIVE_UP_AFTER = 3          # this many jobs in a row with a lane that could not be healed: stop booting it (saves time)
RETRY_AFTER_H = 6          # ...but try again after this many hours (an update or a reboot may have fixed it)


def _health_state():
    try:
        import json
        return json.load(open(HEALTH))
    except Exception:
        return {}


def _save_health(st):
    import json
    try:
        os.makedirs(os.path.dirname(HEALTH), exist_ok=True)
        json.dump(st, open(HEALTH + '.tmp', 'w'), indent=1)
        os.replace(HEALTH + '.tmp', HEALTH)
    except Exception:
        pass


def health(serial):
    """What is wrong with this emulator, or '' when it is usable: adb link, boot, package service, launcher, storage."""
    st = _adb(serial, 'get-state', t=10)
    if 'device' not in st:
        return f'adb sees it as "{st or "nothing"}"'
    if _adb(serial, 'shell', 'getprop', 'sys.boot_completed', t=15) != '1':
        return 'not booted (sys.boot_completed != 1)'
    if 'package:' not in _adb(serial, 'shell', 'pm', 'path', 'android', t=20):
        return 'package service does not answer (pm path android)'
    r = _adb(serial, 'shell', 'am', 'start', '-W', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME', t=40)
    if 'Status: ok' not in r and 'Complete' not in r:
        return 'cannot start an activity (am start HOME): ' + ' '.join(r.split())[-100:]
    df = _adb(serial, 'shell', 'df', '/data', t=15).splitlines()
    try:
        free_kb = int(df[-1].split()[3])
        if free_kb < 1_000_000:
            return f'/data almost full ({free_kb // 1024} MB free)'
    except Exception:
        pass
    return ''


class Lanes:
    def __init__(self, n, log=print, on_ready=None):
        self.n, self.log, self.procs, self.serials = int(n), log, [], []
        self.on_ready = on_ready

    def up(self, timeout=360):
        """Boot n emulators headless (read-only instances of one AVD), ONE AFTER ANOTHER: two cold boots at once next to a
        Gradle build starved each other on the 8-core M1 (one never booted, 2026-10-13). Each lane is usable as soon as it
        is ready (self.serials grows), so the phone never waits for the lanes."""
        if not available() or self.n <= 0:
            return []
        hs = _health_state().get(AVD) or {}
        if hs.get('fails', 0) >= GIVE_UP_AFTER and time.time() - hs.get('last', 0) < RETRY_AFTER_H * 3600:
            self.log(f'lab lanes: OFF this job: the emulator ({AVD}) could not be healed in the last {hs["fails"]} jobs '
                     f'({hs.get("reason", "?")}). Next try after {RETRY_AFTER_H} h, or fix it: open Android Studio > Device '
                     f'Manager > {AVD} > Cold Boot Now (or Wipe Data), then delete out/lanes_health.json')
            return []
        t0 = time.time()
        self.serials = []
        for i in range(self.n):
            port = 5554 + 2 * i
            serial = f'emulator-{port}'
            if _adb(serial, 'shell', 'getprop', 'sys.boot_completed', t=10) == '1':
                if self._ours(port):
                    self.log(f'lab lanes: {serial} was still running from an earlier job; restarting it fresh')
                    self._kill(port)
                else:                                  # someone's own emulator (Android Studio, with a window): leave it
                    self.log(f'lab lanes: {serial} is an emulator Night Shift did not start (has a window); not touching it, lane skipped')
                    continue
            # boot -> health check -> if sick: one cold restart -> health check -> if still sick: lane off + remember it
            why = ''
            for attempt in (1, 2):
                if not self._boot(port, timeout, cold=attempt == 2):
                    why = f'did not boot in {timeout}s'
                else:
                    why = health(serial)
                if not why:
                    break
                self.log(f'lab lanes: {serial} is not healthy ({why})' + ('; restarting it with a cold boot' if attempt == 1 else ''))
                self._kill(port)
            st = _health_state()
            if why:
                h = st.get(AVD) or {}
                st[AVD] = {'fails': h.get('fails', 0) + 1, 'last': time.time(), 'reason': why}
                _save_health(st)
                self.log(f'lab lanes: {serial} still not healthy after a cold restart ({why}); lane OFF for this job, the phone '
                         f'carries on alone' + (f' (failed {st[AVD]["fails"]} jobs in a row: it will be skipped for '
                                                 f'{RETRY_AFTER_H} h)' if st[AVD]['fails'] >= GIVE_UP_AFTER else ''))
                continue
            if (st.get(AVD) or {}).get('fails'):
                self.log(f'lab lanes: {serial} is healthy again')
                st[AVD] = {'fails': 0, 'last': time.time(), 'reason': ''}
                _save_health(st)
            _adb(serial, 'shell', 'settings put global window_animation_scale 0; settings put global transition_animation_scale 0; '
                                 'settings put global animator_duration_scale 0; input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard')
            self.serials.append(serial)
            self.log(f'lab lanes: {serial} ready after {time.time() - t0:.0f}s')
            if self.on_ready:
                try:
                    self.on_ready(serial)
                except Exception as e:
                    self.log(f'lab lanes: {serial} setup failed: {str(e)[:160]}')
        return list(self.serials)

    def install(self, apk, only=None):
        """Same APK as the phone (with this job's hooks), on the given lanes (default: every ready lane), in parallel.
        Returns the lanes it installed on; never changes the list of booted lanes."""
        res = {}
        targets = list(only if only is not None else self.serials)
        def one(s):
            # A fresh boot reports boot_completed before the package service answers: an install sent at that moment
            # comes back empty or with "Can't find service: package". Wait for the package service, then retry.
            for k in range(4):
                for _ in range(30):
                    if 'package:' in _adb(s, 'shell', 'pm', 'path', 'android', t=15):
                        break
                    time.sleep(2)
                res[s] = _adb(s, 'install', '-r', '-t', '-g', apk, t=600)
                if 'Success' in res[s]:
                    return
                state = _adb(s, 'get-state', t=10)
                self.log(f'lab lanes: install on {s} try {k + 1} failed ({" ".join(res[s].split())[-140:] or "no output"}; '
                         f'device state: {state}); retrying')
                if 'device' not in state:              # offline/gone: reconnect before the next try
                    _adb(s, 'reconnect', t=20)
                if k == 1:                             # two failures: the emulator itself is suspect, restart it cold once
                    port = int(s.split('-')[-1])
                    self.log(f'lab lanes: restarting {s} (cold boot) before the next install try')
                    self._kill(port)
                    if not self._boot(port, 360, cold=True) or health(s):
                        self.log(f'lab lanes: {s} is not healthy after the restart ({health(s) or "did not boot"})')
                        return
                time.sleep(8)
        th = [threading.Thread(target=one, args=(s,)) for s in targets]
        [t.start() for t in th]
        [t.join() for t in th]
        ok = [s for s in targets if 'Success' in res.get(s, '')]
        bad = [s for s in targets if s not in ok]
        if bad:
            self.log('lab lanes: install failed on ' + '; '.join(f'{s}: {" ".join(res.get(s, "").split())[-160:]}' for s in bad)
                     + '; those lanes sit this job out')
            st = _health_state()                       # counts toward 'stop booting it' like a failed health check
            h = st.get(AVD) or {}
            st[AVD] = {'fails': h.get('fails', 0) + 1, 'last': time.time(),
                       'reason': 'app install fails: ' + ' '.join(res.get(bad[0], '').split())[-120:]}
            _save_health(st)
            for s in bad:                              # a lane we cannot install on is useless this job: stop it
                try:
                    self._kill(int(s.split('-')[-1]))
                except Exception:
                    pass
        return ok

    def _boot(self, port, timeout, cold=False):
        """Start the lane emulator on this port and wait for boot. cold=True also ignores any saved quick-boot state."""
        serial = f'emulator-{port}'
        args = [EMU, '-avd', AVD, '-port', str(port), '-read-only', '-no-window', '-no-audio', '-no-boot-anim', '-no-snapshot',
                '-gpu', 'host', '-memory', '3072' if self.n < 2 else '2048', '-cores', '3' if self.n < 2 else '2']
        if cold:
            args += ['-no-snapshot-load']
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        end = time.time() + timeout
        while time.time() < end and _adb(serial, 'shell', 'getprop', 'sys.boot_completed', t=10) != '1':
            if p.poll() is not None:               # the emulator process exited: no point waiting for it
                return False
            time.sleep(3)
        if _adb(serial, 'shell', 'getprop', 'sys.boot_completed', t=10) != '1':
            return False
        time.sleep(20)                             # a cold boot keeps System UI busy a while
        return True

    @staticmethod
    def _ours(port):
        """True when the emulator on this port is a Night Shift lane (started headless and read-only by up())."""
        r = subprocess.run(['pgrep', '-fl', f'qemu-system.*-port {port} '], capture_output=True, text=True)
        return '-read-only' in r.stdout and '-no-window' in r.stdout

    def _kill(self, port):
        if not self._ours(port):
            return                                     # never stop an emulator Night Shift did not start
        """Stop the emulator on this port for sure: console 'emu kill', then the qemu process itself if it is still there."""
        _adb(f'emulator-{port}', 'emu', 'kill', t=20)
        for _ in range(10):
            time.sleep(1)
            r = subprocess.run(['pgrep', '-f', f'qemu-system.*-port {port}'], capture_output=True, text=True)
            if not r.stdout.strip():
                return
        subprocess.run(['pkill', '-f', f'qemu-system.*-port {port}'], capture_output=True)
        time.sleep(2)
        subprocess.run(['pkill', '-9', '-f', f'qemu-system.*-port {port}'], capture_output=True)

    def down(self):
        for i in range(self.n):
            self._kill(5554 + 2 * i)
        time.sleep(1)
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        self.procs, self.serials = [], []
