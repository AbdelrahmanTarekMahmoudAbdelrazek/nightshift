# Night Shift auto repros for 744dc8addd74ad4d9b332d1229adb623


# 2026-10-10 23:26 level 2 attempt 1
def _744dc8ad_cold_start(ed, background=False):
    """One cold process start: the field crash fires in Application.onCreate before any screen or app log."""
    ed.dev.force_stop()
    time.sleep(1.5)
    if background:
        # system-style start, no activity: the job scheduler runs the app's own jobs, a boot-time broadcast for this package
        ed.dev.sh(f'cmd jobscheduler run -f {PKG} 0 >/dev/null 2>&1; '
                  f'am broadcast -a android.intent.action.LOCKED_BOOT_COMPLETED -p {PKG} >/dev/null 2>&1')
    else:
        ed.dev.launch()


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_1_a(ed, r):
    """Instances vivo V2217 x13 + vivo V2044 x5 (FOREGROUND): user relaunches the app again and again, seconds apart."""
    ed.dev.restore_env()
    for i in range(r.randint(8, 13)):            # V2217: 13 starts in ~4 min, V2044: 5 in 37 s
        ed.step(f'cold launch #{i + 1} from the launcher')
        _744dc8ad_cold_start(ed)
        ed.idle(r.uniform(3, 8))                  # Application.onCreate -> System.loadLibrary("ImageFilter")
        if r.random() < 0.4:
            ed.dev.key('KEYCODE_HOME')            # user gives up, taps the icon again
            ed.idle(r.uniform(1, 3))


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_1_b(ed, r):
    """Instances QEMU 8.1 x2 + V2217 BACKGROUND events: process started by the system (no activity), then by the user."""
    ed.dev.restore_env()
    for i in range(r.randint(3, 5)):
        ed.step(f'background process start #{i + 1}')
        _744dc8ad_cold_start(ed, background=True)
        ed.idle(r.uniform(3, 5))                  # QEMU: two BACKGROUND crashes 3 s apart
        ed.step(f'foreground launch #{i + 1} right after')
        ed.dev.launch()                           # V2217 mixed FOREGROUND/BACKGROUND in the same burst
        ed.idle(r.uniform(3, 6))
        ed.dev.key('KEYCODE_HOME')
        ed.idle(r.uniform(1, 2))


# 2026-10-10 23:36 level 2 attempt 2
_744dc8ad_BG = ('am broadcast -f 0x20 -n {pkg}/androidx.profileinstaller.ProfileInstallReceiver '
                '-a androidx.profileinstaller.action.SAVE_PROFILE')
_744dc8ad_COPY = '/data/local/tmp/ns_744dc8ad_base.apk'


def _744dc8ad_install_state(ed, tag):
    """Checkpoint 1 evidence: which APK and ABI are installed, and whether the APK contains libImageFilter.so."""
    apk = ed.dev.sh(f'pm path {PKG}').strip().replace('package:', '').splitlines()[0]
    abi = ed.dev.sh(f'dumpsys package {PKG} | grep primaryCpuAbi').strip()
    lib = ed.dev.sh(f"unzip -l '{apk}' 'lib/*' | grep -c libImageFilter").strip()
    ed.dev.marker(f'744dc8ad {tag}: apk={apk} {abi} libImageFilter_entries={lib}')
    ed.log(f'    {tag}: {abi}, libImageFilter.so entries in APK = {lib}')
    return apk


def _744dc8ad_cold(ed, background):
    ed.dev.force_stop()                              # same install, brand-new process each time (field bursts)
    time.sleep(1.5)
    if background:                                   # a real system start: explicit broadcast, stopped app included
        ed.dev.sh(_744dc8ad_BG.format(pkg=PKG))
    else:
        ed.dev.launch()


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_2_a(ed, r):
    """vivo V2217 x13 / V2044 x5 FOREGROUND: launcher relaunches seconds apart on the lab install, which has no libImageFilter.so."""
    ed.dev.restore_env()
    _744dc8ad_install_state(ed, 'stock install')
    for i in range(r.randint(4, 6)):
        ed.step(f'cold launch #{i + 1}')
        _744dc8ad_cold(ed, background=False)
        ed.idle(r.uniform(3, 6))                     # Application.onCreate -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_2_b(ed, r):
    """QEMU 8.1 x2 + V2217 BACKGROUND: the process is started by a broadcast (no activity), then by the user."""
    ed.dev.restore_env()
    _744dc8ad_install_state(ed, 'stock install')
    for i in range(r.randint(3, 4)):
        ed.step(f'background process start #{i + 1} (broadcast)')
        _744dc8ad_cold(ed, background=True)
        ed.idle(r.uniform(3, 4))
        ed.log(f'    pid after broadcast: {ed.dev.pid() or "none"}')
        ed.step(f'foreground launch #{i + 1}')
        ed.dev.launch()
        ed.idle(r.uniform(3, 5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_2_c(ed, r):
    """V2044 (Android 11 vivo, maybe a 32-bit process): the same APK reinstalled as armeabi-v7a, then cold starts."""
    ed.dev.restore_env()
    apk = _744dc8ad_install_state(ed, 'before abi switch')
    ed.step('reinstall the same APK as a 32-bit process (armeabi-v7a)')
    ed.dev.sh(f"cp '{apk}' {_744dc8ad_COPY}", timeout=300)
    ed.log('    ' + ed.dev.sh(f'pm install -r --abi armeabi-v7a {_744dc8ad_COPY}', timeout=400).strip()[-120:])
    try:
        ed.grant_permissions()
        _744dc8ad_install_state(ed, 'after abi switch')
        for i in range(3):
            ed.step(f'cold start #{i + 1} as armeabi-v7a ({"background" if i == 1 else "launcher"})')
            _744dc8ad_cold(ed, background=(i == 1))
            ed.idle(r.uniform(3, 5))
    finally:
        ed.dev.force_stop()
        ed.dev.sh(f'pm install -r --abi arm64-v8a {_744dc8ad_COPY}', timeout=400)
        ed.grant_permissions()


# 2026-10-10 23:42 level 2 attempt 3
_744dc8ad_DIR = '/data/local/tmp/ns_744dc8ad'      # lab puts the field 800054867 APKs here, re-signed with the lab key
_744dc8ad_BG = ('am broadcast -f 0x20 -n {pkg}/androidx.profileinstaller.ProfileInstallReceiver '
                '-a androidx.profileinstaller.action.SAVE_PROFILE')


def _744dc8ad_install(ed, paths):
    """Install one or more APKs as one package (base + splits) in a single session, the way Play or bundletool does."""
    sid = ed.dev.sh('pm install-create -r -d').split('[')[-1].split(']')[0]
    for i, p in enumerate(paths):
        ed.dev.sh(f'pm install-write {sid} part{i} {p}', timeout=300)
    out = ed.dev.sh(f'pm install-commit {sid}', timeout=400).strip()
    ed.log(f'    install {[p.split("/")[-1] for p in paths]}: {out[-100:]}')
    return 'Success' in out


def _744dc8ad_field_install(ed, splits):
    """Checkpoint 1: save the lab build, then install the field build 800054867 with the chosen splits only."""
    have = ed.dev.sh(f'ls {_744dc8ad_DIR}')
    if 'base.apk' not in have:
        raise UIError(f'setup: push the field 1.25.1 (800054867) base.apk + split_config.*.apk, re-signed with the lab key, to {_744dc8ad_DIR}')
    ed.dev.sh(f'mkdir -p {_744dc8ad_DIR}/lab')
    lab = [l.replace('package:', '').strip() for l in ed.dev.sh(f'pm path {PKG}').splitlines() if l.strip()]
    for i, p in enumerate(lab):
        ed.dev.sh(f"cp '{p}' {_744dc8ad_DIR}/lab/{i}.apk", timeout=300)
    ed.dev.force_stop()
    want = ['base.apk'] + [s for s in splits if s in have]
    if not _744dc8ad_install(ed, [f'{_744dc8ad_DIR}/{f}' for f in want]):
        raise UIError('setup: field build did not install (signature/versionCode); re-sign with the lab key')
    vc = ed.dev.sh(f'dumpsys package {PKG} | grep -m1 versionCode').strip()
    paths = ' '.join(l.replace('package:', '').strip() for l in ed.dev.sh(f'pm path {PKG}').splitlines() if l.strip())
    libs = ed.dev.sh(f"for a in {paths}; do unzip -l $a 'lib/*' 2>/dev/null; done | grep -c libImageFilter; "
                     f"ls -R $(dumpsys package {PKG} | grep -m1 legacyNativeLibraryDir | cut -d= -f2) 2>/dev/null | grep -c libImageFilter").split()
    dex = ed.dev.sh(f"unzip -p {paths.split()[0]} 'classes*.dex' | grep -ac 'ImageFilter'").strip()
    ed.dev.marker(f'744dc8ad field install: {vc} splits={want} libImageFilter apk/libdir={libs} dex_refs={dex}')
    if '800054867' not in vc:
        raise UIError(f'setup: installed {vc}, the field crash needs 800054867')
    return len(lab)


def _744dc8ad_restore(ed, n):
    ed.dev.force_stop()
    _744dc8ad_install(ed, [f'{_744dc8ad_DIR}/lab/{i}.apk' for i in range(n)])


def _744dc8ad_burst(ed, r, n, background_every=0):
    """Checkpoints 2-5: same install, new cold process each time, seconds apart (V2217 13 in 4 min, V2044 5 in 37 s)."""
    for i in range(n):
        bg = background_every and i % background_every == 0
        ed.step(f'cold {"background broadcast" if bg else "launcher"} start #{i + 1}')
        ed.dev.force_stop()
        time.sleep(1.5)
        ed.dev.sh(_744dc8ad_BG.format(pkg=PKG)) if bg else ed.dev.launch()
        ed.idle(r.uniform(3, 6))                    # MainApplication.onCreate:143 -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_3_a(ed, r):
    """vivo V2217 x13 + V2044 x5 FOREGROUND: field 800054867 sideloaded as base.apk with no ABI split, launcher relaunches."""
    ed.dev.restore_env()
    n = _744dc8ad_field_install(ed, splits=[])
    try:
        _744dc8ad_burst(ed, r, r.randint(5, 8))
    finally:
        _744dc8ad_restore(ed, n)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_3_b(ed, r):
    """QEMU 8.1 x2 + V2217 BACKGROUND events: field base-only install, the process is started by a broadcast first."""
    ed.dev.restore_env()
    n = _744dc8ad_field_install(ed, splits=[])
    try:
        _744dc8ad_burst(ed, r, r.randint(4, 6), background_every=2)
    finally:
        _744dc8ad_restore(ed, n)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l2_3_c(ed, r):
    """All 20 instances, hypothesis 2: the complete Play set for 800054867 (base + ABI/density/lang splits); tests a packaging gap."""
    ed.dev.restore_env()
    n = _744dc8ad_field_install(ed, splits=['split_config.arm64_v8a.apk', 'split_config.xxhdpi.apk',
                                            'split_config.en.apk', 'split_config.armeabi_v7a.apk'])
    try:
        _744dc8ad_burst(ed, r, r.randint(3, 5), background_every=3)
    finally:
        _744dc8ad_restore(ed, n)


# 2026-10-10 23:47 level 3 attempt 1
_744dc8ad_TMP = '/data/local/tmp/ns_744dc8ad_lab'
_744dc8ad_BG = ('am broadcast -f 0x20 -n {pkg}/androidx.profileinstaller.ProfileInstallReceiver '
                '-a androidx.profileinstaller.action.SAVE_PROFILE')
_744dc8ad_ABI_SPLIT = ('arm64_v8a', 'armeabi_v7a', 'x86')


def _744dc8ad_paths(ed):
    return [l.replace('package:', '').strip() for l in ed.dev.sh(f'pm path {PKG}').splitlines() if l.strip().startswith('package:')]


def _744dc8ad_libs(ed, tag):
    """Checkpoint 1 evidence: every installed APK (base + splits), its libImageFilter entries, and the ABI."""
    out = []
    for p in _744dc8ad_paths(ed):
        hits = ed.dev.sh(f"unzip -l '{p}' 2>&1 | grep -E 'libImageFilter|not found' | tr -s ' ' | cut -d' ' -f5-").split()
        out.append(f"{p.split('/')[-1]}:{hits or '-'}")
    abi = ed.dev.sh(f'dumpsys package {PKG} | grep -m1 primaryCpuAbi').strip()
    ed.dev.marker(f'744dc8ad {tag}: {abi} {out}')
    ed.log(f'    {tag}: {abi} {out}')
    return out


def _744dc8ad_session(ed, apks, extra=''):
    """Full (non-inherit) install session with exactly these APKs; -r keeps the app's data and permissions."""
    sid = ed.dev.sh(f'pm install-create -r {extra}').split('[')[-1].split(']')[0]
    for i, a in enumerate(apks):
        ed.dev.sh(f'pm install-write {sid} p{i}_{a.split("/")[-1]} {a}', timeout=300)
    res = ed.dev.sh(f'pm install-commit {sid}', timeout=400).strip()
    ed.log(f'    install {[a.split("/")[-1] for a in apks]} {extra}: {res[-120:]}')
    return 'Success' in res


def _744dc8ad_break_install(ed, base_only):
    """Checkpoint 1 FIRST, before any cold start: same lab build, reinstalled with no libImageFilter.so for the phone's ABI."""
    ed.step('checkpoint 1: reinstall the lab build without the ABI native libs')
    ed.mon.allow_death = True                        # the installer kills the running process: not the crash
    ed.dev.force_stop()
    orig = _744dc8ad_paths(ed)
    _744dc8ad_libs(ed, 'lab install')
    ed.dev.sh(f'rm -rf {_744dc8ad_TMP}; mkdir -p {_744dc8ad_TMP}')
    saved = []
    for i, p in enumerate(orig):
        dst = f'{_744dc8ad_TMP}/{i}_{p.split("/")[-1]}'
        ed.dev.sh(f"cp '{p}' {dst}", timeout=300)
        saved.append(dst)
    ok = False
    if len(saved) > 1:                               # bundle install: drop the ABI split(s), like a base-only sideload
        keep = [s for s in saved if 'base.apk' in s] if base_only else \
               [s for s in saved if not any(a in s for a in _744dc8ad_ABI_SPLIT)]
        ok = _744dc8ad_session(ed, keep)
    else:                                            # universal APK: choose a supported ABI whose lib/ has no ImageFilter
        listing = ed.dev.sh(f"unzip -l {saved[0]} 'lib/*' 2>&1")
        for abi in ed.dev.getprop('ro.product.cpu.abilist').split(','):
            if abi and f'lib/{abi}/' in listing and f'lib/{abi}/libImageFilter.so' not in listing:
                ok = _744dc8ad_session(ed, saved, extra=f'--abi {abi}')
                break
    _744dc8ad_libs(ed, 'after reinstall')
    ed.mon.allow_death = False
    if not ok:
        raise UIError(f'setup: could not make an ABI-less install on-device (paths={[s.split("/")[-1] for s in saved]}); '
                      'lab install is a universal APK with libImageFilter for every ABI; a host-side zip -d + re-sign is needed')
    return saved


def _744dc8ad_restore(ed, saved):
    ed.mon.allow_death = True
    ed.dev.force_stop()
    _744dc8ad_session(ed, saved)
    ed.dev.sh(f'rm -rf {_744dc8ad_TMP}')


def _744dc8ad_burst(ed, r, n, bg_every=0):
    """Checkpoints 2-5: install unchanged, a new cold process every few seconds (V2217 13 in 4 min, V2044 5 in 37 s)."""
    for i in range(n):
        bg = bg_every and i % bg_every == 0
        ed.step(f'cold {"background broadcast" if bg else "launcher"} start #{i + 1}')
        ed.dev.sh(_744dc8ad_BG.format(pkg=PKG)) if bg else ed.dev.launch()
        ed.idle(r.uniform(3, 6))                     # MainApplication.onCreate:143 -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_1_a(ed, r):
    """vivo V2217 x13 + V2044 x5 FOREGROUND: install without the ABI split (no libImageFilter.so), launcher relaunches."""
    saved = _744dc8ad_break_install(ed, base_only=False)
    try:
        _744dc8ad_burst(ed, r, r.randint(4, 6))
    finally:
        _744dc8ad_restore(ed, saved)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_1_b(ed, r):
    """QEMU 8.1 x2 + V2217 BACKGROUND: same ABI-less install, the process is first started by a broadcast, not the user."""
    saved = _744dc8ad_break_install(ed, base_only=False)
    try:
        _744dc8ad_burst(ed, r, r.randint(4, 6), bg_every=2)
    finally:
        _744dc8ad_restore(ed, saved)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_1_c(ed, r):
    """All 3 phones, sideload hypothesis: only base.apk installed (no config splits at all), mixed user/system starts."""
    saved = _744dc8ad_break_install(ed, base_only=True)
    try:
        _744dc8ad_burst(ed, r, r.randint(3, 5), bg_every=3)
    finally:
        _744dc8ad_restore(ed, saved)


# 2026-10-10 23:53 level 3 attempt 2
_744dc8ad_APK = os.path.join(os.path.dirname(LONG_AUDIO_CLIP), 'ns_744dc8ad_noimagefilter.apk')
_744dc8ad_TMP = '/data/local/tmp/ns_744dc8ad_lab'
_744dc8ad_BG = ('am broadcast -f 0x20 -n {pkg}/androidx.profileinstaller.ProfileInstallReceiver '
                '-a androidx.profileinstaller.action.SAVE_PROFILE')
_744dc8ad_PREP = ("host setup: cp app/build/outputs/apk/productionInternal/debug/app-productionInternal-debug.apk s.apk && "
                  "zip -d s.apk 'lib/*/libImageFilter.so' && zipalign -f -p 4 s.apk a.apk && apksigner sign --ks "
                  "~/.android/debug.keystore --ks-pass pass:android --out repro_assets/ns_744dc8ad_noimagefilter.apk a.apk")


def _744dc8ad_state(ed, tag):
    """Checkpoint 1 evidence: installed APKs, libImageFilter entries in them, ABI (written to a file: no broken pipe)."""
    paths = [l.split(':', 1)[1].strip() for l in ed.dev.sh(f'pm path {PKG}').splitlines() if l.startswith('package:')]
    n = ed.dev.sh(f"for a in {' '.join(paths)}; do unzip -l $a; done > {_744dc8ad_TMP}/ls.txt 2>&1; "
                  f"grep -c libImageFilter {_744dc8ad_TMP}/ls.txt").strip()
    abi = ed.dev.sh(f'dumpsys package {PKG} > {_744dc8ad_TMP}/pkg.txt; grep primaryCpuAbi {_744dc8ad_TMP}/pkg.txt').strip()
    ed.dev.marker(f'744dc8ad {tag}: {abi} apks={[p.split("/")[-1] for p in paths]} libImageFilter={n}')
    ed.log(f'    {tag}: {abi} libImageFilter entries={n}')
    return paths, n


def _744dc8ad_restore(ed, saved):
    ed.mon.allow_death = True
    ed.dev.force_stop()
    sid = ed.dev.sh('pm install-create -r -d').split('[')[-1].split(']')[0]
    for i, s in enumerate(saved):
        ed.dev.sh(f'pm install-write {sid} p{i} {s}', timeout=300)
    ed.log('    restore lab install: ' + ed.dev.sh(f'pm install-commit {sid}', timeout=400).strip()[-80:])


def _744dc8ad_break_install(ed, abi=None):
    """Checkpoint 1 BEFORE any start: the app with libImageFilter.so stripped from every ABI, verified on the phone."""
    ed.step(f'checkpoint 1: install the app without libImageFilter.so{" as " + abi if abi else ""}')
    ed.dev.sh(f'rm -rf {_744dc8ad_TMP}; mkdir -p {_744dc8ad_TMP}')
    paths, _ = _744dc8ad_state(ed, 'lab install')
    saved = []
    for i, p in enumerate(paths):
        saved.append(f'{_744dc8ad_TMP}/{i}.apk')
        ed.dev.sh(f"cp '{p}' {saved[-1]}", timeout=300)
    ed.mon.allow_death = True                        # the installer kills the running process: not the crash
    ed.dev.force_stop()
    out = ed.dev.adb('install', '-r', '-d', *(['--abi', abi] if abi else []), _744dc8ad_APK, timeout=400)
    ed.log('    install stripped apk: ' + out.strip()[-120:])
    _, n = _744dc8ad_state(ed, 'after install')
    if 'Success' not in out or n != '0':
        _744dc8ad_restore(ed, saved)
        raise UIError(f'setup: install still has libImageFilter.so ({n}) or failed; {_744dc8ad_PREP}')
    ed.mon.allow_death = False
    return saved


def _744dc8ad_burst(ed, r, starts):
    """Checkpoints 2-5: install unchanged, a brand-new process each time, seconds apart."""
    for i, bg in enumerate(starts):
        ed.step(f'cold {"background broadcast" if bg else "launcher"} start #{i + 1}')
        ed.mon.allow_death = True
        ed.dev.force_stop()                          # no warm reuse: every start logs a fresh Start proc
        time.sleep(1.5)
        ed.mon.allow_death = False
        ed.dev.sh(_744dc8ad_BG.format(pkg=PKG)) if bg else ed.dev.launch()
        ed.idle(r.uniform(3, 6))                     # MainApplication.onCreate:143 -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_2_a(ed, r):
    """vivo V2217 x13 + V2044 x5 FOREGROUND: app installed without libImageFilter.so, launcher relaunches seconds apart."""
    ed.dev.restore_env()
    saved = _744dc8ad_break_install(ed)
    try:
        _744dc8ad_burst(ed, r, [False] * r.randint(3, 5))
    finally:
        _744dc8ad_restore(ed, saved)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_2_b(ed, r):
    """QEMU 8.1 x2 + V2217 BACKGROUND: same lib-less install, process started by a system broadcast, no activity."""
    ed.dev.restore_env()
    saved = _744dc8ad_break_install(ed)
    try:
        _744dc8ad_burst(ed, r, [True, True, False, True])
    finally:
        _744dc8ad_restore(ed, saved)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_2_c(ed, r):
    """vivo V2044 (Android 11, 32-bit process): lib-less install forced to armeabi-v7a, mixed launcher/broadcast starts."""
    ed.dev.restore_env()
    saved = _744dc8ad_break_install(ed, abi='armeabi-v7a')
    try:
        _744dc8ad_burst(ed, r, [False, True, False])
    finally:
        _744dc8ad_restore(ed, saved)


# 2026-10-10 23:59 level 3 attempt 3
_744dc8ad_TMP = '/data/local/tmp/ns_744dc8ad_lab'
_744dc8ad_SEARCH = '/data/local/tmp /sdcard/Download /sdcard/NightShift /sdcard/DCIM/NightShift'
_744dc8ad_BG = ('am broadcast -f 0x20 -n {pkg}/androidx.profileinstaller.ProfileInstallReceiver '
                '-a androidx.profileinstaller.action.SAVE_PROFILE')
_744dc8ad_NEED = ('setup: no APK with com/myzesty/MainApplication (field 1.25.1 / 800054867) on the phone. The lab build '
                  'uses com.myzesty.app.App and never loads ImageFilter. Download the 800054867 base + split APKs from the '
                  'Play App bundle explorer, re-sign them with the lab key, and adb push them to /data/local/tmp/ns_744dc8ad/')


def _744dc8ad_field_apks(ed):
    """Find the field build on the phone: the directory that holds an APK whose dex declares com.myzesty.MainApplication."""
    hits = ed.dev.sh(f"for a in $(find {_744dc8ad_SEARCH} -name '*.apk' 2>/dev/null); do "
                     f"unzip -p $a 'classes*.dex' 2>/dev/null | grep -qa 'Lcom/myzesty/MainApplication;' && echo $a; done",
                     timeout=300).split()
    if not hits:
        raise UIError(_744dc8ad_NEED)
    d = hits[0].rsplit('/', 1)[0]
    apks = ed.dev.sh(f"ls {d}/*.apk").split()
    ed.dev.marker(f'744dc8ad field apks in {d}: {[a.split("/")[-1] for a in apks]}')
    return hits[0], apks


def _744dc8ad_session(ed, apks):
    sid = ed.dev.sh('pm install-create -r -d').split('[')[-1].split(']')[0]
    for i, a in enumerate(apks):
        ed.dev.sh(f'pm install-write {sid} p{i} {a}', timeout=300)
    res = ed.dev.sh(f'pm install-commit {sid}', timeout=400).strip()
    ed.log(f'    install {[a.split("/")[-1] for a in apks]}: {res[-120:]}')
    return res


def _744dc8ad_setup(ed, keep):
    """Checkpoint 1: save the lab install, then install the FIELD build with only the APKs keep() allows (no ABI lib)."""
    ed.dev.restore_env()
    base, apks = _744dc8ad_field_apks(ed)
    ed.step('checkpoint 1: field 800054867 installed without libImageFilter.so for this ABI')
    ed.dev.sh(f'rm -rf {_744dc8ad_TMP}; mkdir -p {_744dc8ad_TMP}')
    lab = [l.split(':', 1)[1].strip() for l in ed.dev.sh(f'pm path {PKG}').splitlines() if l.startswith('package:')]
    saved = []
    for i, p in enumerate(lab):
        saved.append(f'{_744dc8ad_TMP}/{i}.apk')
        ed.dev.sh(f"cp '{p}' {saved[-1]}", timeout=300)
    ed.mon.allow_death = True                        # the installer kills the lab process: not the crash
    ed.dev.force_stop()
    res = _744dc8ad_session(ed, [base] + [a for a in apks if a != base and keep(a)])
    abi = ed.dev.getprop('ro.product.cpu.abi').replace('-', '_')
    paths = ' '.join(l.split(':', 1)[1].strip() for l in ed.dev.sh(f'pm path {PKG}').splitlines() if l.startswith('package:'))
    libs = ed.dev.sh(f"for a in {paths}; do unzip -l $a; done 2>/dev/null | grep -c 'lib/.*libImageFilter'").strip()
    ed.dev.marker(f'744dc8ad installed: {paths} abi={abi} libImageFilter={libs} result={res[-60:]}')
    if 'Success' not in res:
        _744dc8ad_restore(ed, saved)
        raise UIError(f'setup: field APK did not install ({res[-80:]}); re-sign the 800054867 APKs with the lab key')
    ed.mon.allow_death = False
    return saved


def _744dc8ad_restore(ed, saved):
    ed.mon.allow_death = True
    ed.dev.force_stop()
    _744dc8ad_session(ed, saved)


def _744dc8ad_burst(ed, r, starts):
    """Checkpoints 2-5: install unchanged, a new cold process each time, seconds apart (V2044: 5 in 37 s)."""
    for i, bg in enumerate(starts):
        ed.step(f'cold {"broadcast (BACKGROUND)" if bg else "launcher (FOREGROUND)"} start #{i + 1}')
        ed.dev.sh(_744dc8ad_BG.format(pkg=PKG)) if bg else ed.dev.launch()
        ed.idle(r.uniform(3, 7))                     # MainApplication.onCreate:143 -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_3_a(ed, r):
    """V2217 x13 + V2044 x5 FOREGROUND: field 800054867 installed as base.apk only (no ABI split), launcher relaunches."""
    saved = _744dc8ad_setup(ed, keep=lambda a: False)
    try:
        _744dc8ad_burst(ed, r, [False] * r.randint(4, 6))
    finally:
        _744dc8ad_restore(ed, saved)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_3_b(ed, r):
    """QEMU 8.1 x2 + V2217 BACKGROUND: field build without its ABI split (density/lang kept), first started by a broadcast."""
    saved = _744dc8ad_setup(ed, keep=lambda a: 'arm' not in a and 'x86' not in a)
    try:
        _744dc8ad_burst(ed, r, [True, True, False, True])
    finally:
        _744dc8ad_restore(ed, saved)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l3_3_c(ed, r):
    """All 20 instances, hypothesis 2: the COMPLETE 800054867 split set; crashes only if the build itself lacks the lib."""
    saved = _744dc8ad_setup(ed, keep=lambda a: True)
    try:
        _744dc8ad_burst(ed, r, [False, True, False])
    finally:
        _744dc8ad_restore(ed, saved)


# 2026-10-11 00:03 level 4 attempt 1
_744dc8ad_SRC = os.path.join(os.path.dirname(LONG_AUDIO_CLIP), 'ns_744dc8ad')   # host: field 800054867 base + splits
_744dc8ad_DEV = '/data/local/tmp/ns_744dc8ad'                                   # phone: same APKs (pushed here)
_744dc8ad_LAB = '/data/local/tmp/ns_744dc8ad_lab'
_744dc8ad_BG = f'am broadcast -f 0x20 -n {PKG}/androidx.profileinstaller.ProfileInstallReceiver -a androidx.profileinstaller.action.SAVE_PROFILE'
_744dc8ad_ABI = ('arm64_v8a', 'armeabi_v7a', 'x86', 'x86_64')


def _744dc8ad_apks(ed, d):
    return sorted(f'{d}/{f}' for f in ed.dev.sh(f'ls {d} 2>/dev/null').split() if f.endswith('.apk'))


def _744dc8ad_install(ed, apks):
    """One full install session; a signature clash with the other build means uninstall first."""
    for attempt in range(2):
        sid = ed.dev.sh('pm install-create -r -d').split('[')[-1].split(']')[0]
        for i, a in enumerate(apks):
            ed.dev.sh(f'pm install-write {sid} p{i}_{a.split("/")[-1]} {a}', timeout=300)
        res = ed.dev.sh(f'pm install-commit {sid}', timeout=400).strip()
        ed.log(f'    install {[a.split("/")[-1] for a in apks]}: {res[-100:]}')
        if 'Success' in res or 'UPDATE_INCOMPATIBLE' not in res or attempt:
            return 'Success' in res
        ed.dev.sh(f'pm uninstall {PKG}', timeout=120)


def _744dc8ad_field_install(ed):
    """Checkpoint 1: field build 800054867 installed WITHOUT split_config.<abi>.apk, verified on the phone."""
    ed.step('checkpoint 1: field 1.25.1 (800054867) base install, no ABI split')
    ed.dev.restore_env()
    ed.mon.allow_death = True                       # installer kills the process: not the crash
    ed.dev.force_stop()
    ed.dev.sh(f'rm -rf {_744dc8ad_LAB}; mkdir -p {_744dc8ad_LAB} {_744dc8ad_DEV}')
    lab = []
    for i, l in enumerate(ed.dev.sh(f'pm path {PKG}').split()):
        lab.append(f'{_744dc8ad_LAB}/{i}.apk')
        ed.dev.sh(f'cp {l.replace("package:", "")} {lab[-1]}', timeout=300)
    if os.path.isdir(_744dc8ad_SRC):
        for f in os.listdir(_744dc8ad_SRC):
            if f.endswith('.apk'):
                ed.dev.adb('push', os.path.join(_744dc8ad_SRC, f), f'{_744dc8ad_DEV}/{f}', timeout=300)
    field = [a for a in _744dc8ad_apks(ed, _744dc8ad_DEV) if not any(x in a for x in _744dc8ad_ABI)]
    base = [a for a in field if 'base' in a.split('/')[-1]] or field[:1]
    is_field = base and ed.dev.sh(f"unzip -p {base[0]} 'classes*.dex' | grep -c 'Lcom/myzesty/MainApplication;'").strip() not in ('', '0')
    if not is_field:
        raise UIError(f'setup: no field 800054867 APKs with com/myzesty/MainApplication in {_744dc8ad_SRC} or '
                      f'{_744dc8ad_DEV}; get base.apk + split_config.*.apk from Play Console App bundle explorer')
    ok = _744dc8ad_install(ed, field)
    libs = ed.dev.sh(f'for a in $(pm path {PKG} | cut -d: -f2); do unzip -l $a; done | grep -c libImageFilter').strip()
    ed.dev.marker(f'744dc8ad installed {ed.dev.sh(f"pm path {PKG}").split()} libImageFilter={libs}')
    ed.mon.allow_death = False
    if not ok or libs != '0':
        _744dc8ad_restore(ed, lab)
        raise UIError(f'setup: field install failed or still ships libImageFilter.so ({libs}); base.apk is universal?')
    return lab


def _744dc8ad_restore(ed, lab):
    ed.mon.allow_death = True
    ed.dev.force_stop()
    _744dc8ad_install(ed, lab)
    for p in ('READ_EXTERNAL_STORAGE', 'READ_MEDIA_VIDEO', 'READ_MEDIA_IMAGES', 'POST_NOTIFICATIONS'):
        ed.dev.sh(f'pm grant {PKG} android.permission.{p} 2>/dev/null')


def _744dc8ad_storm(ed, starts, gap):
    """Checkpoints 2-5: install unchanged, a new cold process every few seconds (launcher=FOREGROUND, broadcast=BACKGROUND)."""
    for i, bg in enumerate(starts):
        ed.step(f'cold {"broadcast (BACKGROUND)" if bg else "launcher (FOREGROUND)"} start #{i + 1}')
        ed.dev.sh(_744dc8ad_BG) if bg else ed.dev.launch()
        ed.idle(gap())                              # MainApplication.onCreate:143 -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_1_a(ed, r):
    """vivo V2217 x13: base-only field install, 13 mixed FOREGROUND/BACKGROUND restarts over ~4 min-style burst."""
    lab = _744dc8ad_field_install(ed)
    try:
        _744dc8ad_storm(ed, [r.random() < 0.4 for _ in range(8)], lambda: r.uniform(4, 15))
    finally:
        _744dc8ad_restore(ed, lab)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_1_b(ed, r):
    """vivo V2044 x5: base-only field install, 5 launcher relaunches packed into ~37 s (user retapping the icon)."""
    lab = _744dc8ad_field_install(ed)
    try:
        _744dc8ad_storm(ed, [False] * 5, lambda: r.uniform(2, 9))
    finally:
        _744dc8ad_restore(ed, lab)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_1_c(ed, r):
    """QEMU 8.1 x2: base-only field install, two system broadcasts 3 s apart start the process with no activity."""
    lab = _744dc8ad_field_install(ed)
    try:
        _744dc8ad_storm(ed, [True, True, True], lambda: 3)
    finally:
        _744dc8ad_restore(ed, lab)


# 2026-10-11 00:08 level 4 attempt 2
_744dc8ad_HOST = [os.path.join(os.path.dirname(LONG_AUDIO_CLIP), 'ns_744dc8ad'), os.path.expanduser('~/Downloads')]
_744dc8ad_DEV = '/data/local/tmp/ns_744dc8ad'
_744dc8ad_LAB = '/data/local/tmp/ns_744dc8ad_lab'
_744dc8ad_ABI = ('arm64_v8a', 'armeabi_v7a', 'x86', 'x86_64')
_744dc8ad_BG = f'am broadcast -f 0x20 -n {PKG}/androidx.profileinstaller.ProfileInstallReceiver -a androidx.profileinstaller.action.SAVE_PROFILE'


def _744dc8ad_install(ed, apks):
    for attempt in range(2):                         # field build is Play-signed: clashes with the lab key -> uninstall
        sid = ed.dev.sh('pm install-create -r -d').split('[')[-1].split(']')[0]
        for i, a in enumerate(apks):
            ed.dev.sh(f'pm install-write {sid} p{i}_{a.split("/")[-1]} {a}', timeout=300)
        res = ed.dev.sh(f'pm install-commit {sid}', timeout=400).strip()
        ed.log(f'    install {[a.split("/")[-1] for a in apks]}: {res[-100:]}')
        if 'Success' in res or 'UPDATE_INCOMPATIBLE' not in res or attempt:
            return 'Success' in res
        ed.dev.sh(f'pm uninstall {PKG}', timeout=120)


def _744dc8ad_restore(ed, lab):
    ed.mon.allow_death = True
    ed.dev.force_stop()
    _744dc8ad_install(ed, lab)
    for p in ('READ_EXTERNAL_STORAGE', 'READ_MEDIA_VIDEO', 'READ_MEDIA_IMAGES', 'POST_NOTIFICATIONS'):
        ed.dev.sh(f'pm grant {PKG} android.permission.{p} 2>/dev/null')


def _744dc8ad_field_install(ed, keep_nonabi_splits):
    """Checkpoint 1: Play 800054867 base (+ optional density/lang splits), NO split_config.<abi>.apk, verified."""
    ed.step('checkpoint 1: field 1.25.1 (800054867) installed without its ABI split')
    ed.dev.restore_env()
    ed.mon.allow_death = True                        # installer kills the process: not the crash
    ed.dev.force_stop()
    ed.dev.sh(f'rm -rf {_744dc8ad_LAB}; mkdir -p {_744dc8ad_LAB} {_744dc8ad_DEV}')
    lab = []
    for i, l in enumerate(ed.dev.sh(f'pm path {PKG}').split()):
        lab.append(f'{_744dc8ad_LAB}/{i}.apk')
        ed.dev.sh(f'cp {l.replace("package:", "")} {lab[-1]}', timeout=300)
    for d in _744dc8ad_HOST:                         # loose APKs or a bundletool .apks set
        for f in (os.listdir(d) if os.path.isdir(d) else []):
            if f.endswith('.apk') and ('800054867' in f or d.endswith('ns_744dc8ad')) or f.endswith('.apks') and '800054867' in f:
                ed.dev.adb('push', os.path.join(d, f), f'{_744dc8ad_DEV}/{f}', timeout=300)
    ed.dev.sh(f'cp /sdcard/Download/*800054867*.ap* {_744dc8ad_DEV}/ 2>/dev/null; cd {_744dc8ad_DEV} && '
              f'for s in *.apks; do [ -f "$s" ] && unzip -o -j "$s" "splits/*.apk" "standalones/*" -d . >/dev/null; done')
    all_apks = [f'{_744dc8ad_DEV}/{f}' for f in ed.dev.sh(f'ls {_744dc8ad_DEV}').split() if f.endswith('.apk')]
    base = [a for a in all_apks if 'base' in a.split('/')[-1] and not any(x in a for x in _744dc8ad_ABI)
            and 'standalone' not in a][:1]
    extra = [a for a in all_apks if keep_nonabi_splits and a not in base and 'base-' in a.split('/')[-1]
             and not any(x in a for x in _744dc8ad_ABI) and 'standalone' not in a and 'master' not in a]
    hit = base and ed.dev.sh(f"unzip -p {base[0]} 'classes*.dex' | grep -c 'Lcom/myzesty/MainApplication;'").strip()
    if not hit or hit == '0':
        raise UIError('setup: field 1.25.1 (800054867) base.apk with com/myzesty/MainApplication not found in '
                      f'{_744dc8ad_HOST} or /sdcard/Download; export base + split_config.*.apk (or .apks) from '
                      'Play Console App bundle explorer. The lab build has no ImageFilter load and cannot stand in')
    ok = _744dc8ad_install(ed, base + extra)
    paths = ed.dev.sh(f'pm path {PKG}')
    libs = ed.dev.sh(f'for a in $(pm path {PKG} | cut -d: -f2); do unzip -l $a; done | grep -c libImageFilter').strip()
    ver = ed.dev.sh(f'dumpsys package {PKG} | grep -m1 versionCode').strip()
    ed.dev.marker(f'744dc8ad installed {paths.split()} {ver} libImageFilter={libs}')
    ed.mon.allow_death = False
    if not ok or libs != '0' or '800054867' not in ver or any(x in paths for x in _744dc8ad_ABI):
        _744dc8ad_restore(ed, lab)
        raise UIError(f'setup: field state not reached (ok={ok} {ver} libImageFilter={libs}); base.apk universal?')
    return lab


def _744dc8ad_storm(ed, starts, gap):
    """Checkpoints 2-5: install unchanged, a new cold process each time (launcher=FOREGROUND, broadcast=BACKGROUND)."""
    for i, bg in enumerate(starts):
        ed.step(f'cold {"broadcast (BACKGROUND)" if bg else "launcher (FOREGROUND)"} start #{i + 1}')
        ed.dev.sh(_744dc8ad_BG) if bg else ed.dev.launch()
        ed.idle(gap())                               # MainApplication.onCreate:143 -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_2_a(ed, r):
    """vivo V2217 x13 + V2044 x5 FOREGROUND: base-only field install, launcher relaunches 2-9 s apart."""
    lab = _744dc8ad_field_install(ed, keep_nonabi_splits=False)
    try:
        _744dc8ad_storm(ed, [False] * 6, lambda: r.uniform(2, 9))
    finally:
        _744dc8ad_restore(ed, lab)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_2_b(ed, r):
    """QEMU 8.1 x2 BACKGROUND: base-only field install, system broadcasts ~3 s apart start the process, no activity."""
    lab = _744dc8ad_field_install(ed, keep_nonabi_splits=False)
    try:
        _744dc8ad_storm(ed, [True] * 4, lambda: r.uniform(2.5, 4))
    finally:
        _744dc8ad_restore(ed, lab)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_2_c(ed, r):
    """vivo V2217 mixed FG/BG: Play partial install (base + density/lang splits, native split missing), mixed restarts."""
    lab = _744dc8ad_field_install(ed, keep_nonabi_splits=True)
    try:
        _744dc8ad_storm(ed, [r.random() < 0.5 for _ in range(6)], lambda: r.uniform(3, 15))
    finally:
        _744dc8ad_restore(ed, lab)


# 2026-10-11 00:12 level 4 attempt 3
_744dc8ad_HOST = [os.path.join(os.path.dirname(LONG_AUDIO_CLIP), 'field_apks', '800054867'),          # repo, not ~/Downloads (TCC)
                  os.path.join(os.path.dirname(LONG_AUDIO_CLIP), '..', 'tools', 'stress', 'field_apks', '800054867')]
_744dc8ad_DEV, _744dc8ad_LAB = '/data/local/tmp/ns_744dc8ad', '/data/local/tmp/ns_744dc8ad_lab'
_744dc8ad_ABI = ('arm64_v8a', 'armeabi_v7a', 'x86_64', 'x86')
_744dc8ad_BG = f'am broadcast -f 0x20 -n {PKG}/androidx.profileinstaller.ProfileInstallReceiver -a androidx.profileinstaller.action.SAVE_PROFILE'


def _744dc8ad_install(ed, apks, opts=''):
    sid = ed.dev.sh(f'pm install-create -r -d {opts}').split('[')[-1].split(']')[0]
    for i, a in enumerate(apks):
        ed.dev.sh(f'pm install-write {sid} p{i}_{a.split("/")[-1]} {a}', timeout=300)
    res = ed.dev.sh(f'pm install-commit {sid}', timeout=400).strip()
    ed.log(f'    install {opts} {[a.split("/")[-1] for a in apks]}: {res[-120:]}')
    return res


def _744dc8ad_field_install(ed, mode):
    """Checkpoint 1. mode 'base': base.apk only, no ABI split. mode 'wrongabi': base + the phone's 2nd-ABI split, forced to that ABI's sibling, so the primary ABI has no lib."""
    ed.step(f'checkpoint 1: field 1.25.1 (800054867) install, {mode}')
    ed.mon.allow_death = True                                   # installer/uninstall kills: not the crash
    ed.dev.force_stop()
    ed.dev.sh(f'rm -rf {_744dc8ad_LAB}; mkdir -p {_744dc8ad_LAB} {_744dc8ad_DEV}')
    lab = []
    for i, l in enumerate(ed.dev.sh(f'pm path {PKG}').split()):  # keep the lab build to put back
        lab.append(f'{_744dc8ad_LAB}/{i}.apk')
        ed.dev.sh(f'cp {l.replace("package:", "")} {lab[-1]}', timeout=300)
    for d in _744dc8ad_HOST:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for f in names:
            if f.endswith(('.apk', '.apks')):
                ed.dev.adb('push', os.path.join(d, f), f'{_744dc8ad_DEV}/{f}', timeout=300)
    ed.dev.sh(f'cp /sdcard/Download/*800054867*.ap* {_744dc8ad_DEV}/ 2>/dev/null; cd {_744dc8ad_DEV} && '
              f'for s in *.apks; do [ -f "$s" ] && unzip -o -j "$s" "splits/*.apk" -d . >/dev/null; done')
    apks = [f'{_744dc8ad_DEV}/{f}' for f in ed.dev.sh(f'ls {_744dc8ad_DEV}').split() if f.endswith('.apk')]
    base = [a for a in apks if a.split('/')[-1] in ('base.apk', 'base-master.apk')] or \
           [a for a in apks if 'base' in a and not any(x in a for x in _744dc8ad_ABI)][:1]
    hit = base and ed.dev.sh(f"unzip -p {base[0]} 'classes*.dex' | grep -c 'Lcom/myzesty/MainApplication;'").strip()
    if not hit or hit == '0':
        raise UIError('setup: field 1.25.1 (800054867) base.apk not found. Put base.apk + split_config.*.apk (or the .apks) '
                      'from Play Console App bundle explorer in repro_assets/field_apks/800054867/ or /sdcard/Download/')
    abis = ed.dev.getprop('ro.product.cpu.abilist').replace('-', '_').split(',')
    opts, field = '', base
    if mode == 'wrongabi':                                       # complete set (satisfies isSplitRequired) but lib for the 2nd ABI only
        alt = [a for a in apks if len(abis) > 1 and abis[1] in a.split('/')[-1]]
        opts, field = f'--abi {abis[0].replace("_", "-")}', base + alt[:1]
    ed.dev.sh(f'pm uninstall {PKG}', timeout=120)                # Play-signed vs lab key
    res = _744dc8ad_install(ed, field, opts)
    ver = ed.dev.sh(f'dumpsys package {PKG} | grep -m1 versionCode').strip()
    prim = ed.dev.sh(f'dumpsys package {PKG} | grep -m1 primaryCpuAbi').strip()
    libs = ed.dev.sh(f'for a in $(pm path {PKG} | cut -d: -f2); do unzip -l $a; done | grep libImageFilter').strip()
    ed.dev.marker(f'744dc8ad {mode} {res[-60:]} {ver} {prim} pm_path={ed.dev.sh(f"pm path {PKG}").split()} libs={libs!r}')
    pabi = prim.split('=')[-1].replace('-', '_').strip()
    if 'Success' not in res or '800054867' not in ver or (libs and pabi.replace('_', '-') in libs.replace('_', '-')):
        _744dc8ad_restore(ed, lab)
        raise UIError(f'setup: field state not reached ({res[-80:]} {ver} {prim}); MISSING_SPLIT means base requires its ABI split')
    ed.mon.allow_death = False                                   # from here a death IS the field crash
    return lab


def _744dc8ad_restore(ed, lab):
    ed.mon.allow_death = True
    ed.dev.sh(f'pm uninstall {PKG}', timeout=120)
    _744dc8ad_install(ed, lab)
    for p in ('READ_EXTERNAL_STORAGE', 'READ_MEDIA_VIDEO', 'READ_MEDIA_IMAGES', 'POST_NOTIFICATIONS'):
        ed.dev.sh(f'pm grant {PKG} android.permission.{p} 2>/dev/null')


def _744dc8ad_storm(ed, starts, gap):
    """Checkpoints 2-5: install unchanged, new cold process each time (launcher=FOREGROUND, broadcast=BACKGROUND)."""
    for i, bg in enumerate(starts):
        ed.step(f'cold {"broadcast (BACKGROUND)" if bg else "launcher (FOREGROUND)"} start #{i + 1}')
        ed.dev.sh(f'am force-stop {PKG}; ' + _744dc8ad_BG) if bg else ed.dev.sh(f'am start -W -n {PKG}/.MainActivity')
        ed.idle(gap())                                           # MainApplication.onCreate:143 -> System.loadLibrary("ImageFilter")


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_3_a(ed, r):
    """vivo V2044 x5 / V2217 FOREGROUND: base-only field install (no split_config.<abi>), launcher retaps 2-9 s apart."""
    lab = _744dc8ad_field_install(ed, 'base')
    try:
        _744dc8ad_storm(ed, [False] * 5, lambda: r.uniform(2, 9))
    finally:
        _744dc8ad_restore(ed, lab)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_3_b(ed, r):
    """vivo V2217 x13 mixed FG/BG: full field set but the phone's primary ABI has no libImageFilter.so, mixed restarts."""
    lab = _744dc8ad_field_install(ed, 'wrongabi')
    try:
        _744dc8ad_storm(ed, [r.random() < 0.4 for _ in range(6)], lambda: r.uniform(3, 12))
    finally:
        _744dc8ad_restore(ed, lab)


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l4_3_c(ed, r):
    """QEMU 8.1 x2 BACKGROUND: base-only field install, two system broadcasts 3 s apart start the process with no activity."""
    lab = _744dc8ad_field_install(ed, 'base')
    try:
        _744dc8ad_storm(ed, [True, True, True], lambda: 3)
    finally:
        _744dc8ad_restore(ed, lab)


# 2026-10-11 00:18 level 5 attempt 2
_744dc8ad_HOOK = 'debug.zesty.hook.missing_imagefilter'
_744dc8ad_BG = (f'am broadcast -f 0x20 -n {PKG}/androidx.profileinstaller.ProfileInstallReceiver '
                '-a androidx.profileinstaller.action.SAVE_PROFILE')


def _744dc8ad_cold_starts(ed, r, starts, prelude=None):
    """Arm the 'install has no libImageFilter.so' hook, then cold-start the process (fg=launcher, bg=broadcast)."""
    ed.dev.restore_env()
    try:
        if prelude:
            prelude()
        ed.step('checkpoint 1: libImageFilter.so missing for this install (hook on, survives restarts)')
        ed.dev.setprop(_744dc8ad_HOOK, '1')
        for i, bg in enumerate(starts):
            ed.mon.allow_death = True                # our own stop is not the crash
            ed.dev.force_stop()
            ed.idle(1)
            ed.mon.allow_death = False
            ed.step(f'cold {"BACKGROUND broadcast" if bg else "FOREGROUND launcher"} start #{i + 1}: '
                    'Application.onCreate -> System.loadLibrary("ImageFilter")')
            ed.dev.sh(_744dc8ad_BG) if bg else ed.dev.launch()
            ed.idle(r.uniform(4, 9))                 # field bursts: restarts 2-15 s apart
    finally:
        ed.dev.setprop(_744dc8ad_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l5_2_a(ed, r):
    """vivo V2217 x13 / V2044 x5 FOREGROUND: Crashlytics MainApplication.onCreate UnsatisfiedLinkError on a launcher cold start."""
    _744dc8ad_cold_starts(ed, r, [False, False, False])


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l5_2_b(ed, r):
    """QEMU 8.1 x2 + vivo BACKGROUND: Crashlytics MainApplication.onCreate UnsatisfiedLinkError when a broadcast cold-starts the process."""
    _744dc8ad_cold_starts(ed, r, [True, True, False])


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l5_2_c(ed, r):
    """vivo V2217 relaunch burst: Crashlytics MainApplication.onCreate UnsatisfiedLinkError after a live app is killed in the background and reopened."""
    def prelude():
        ed.step('app alive in background, then killed by the system (process dies, task kept)')
        ed.dev.launch()
        ed.idle(4)
        ed.dev.key('KEYCODE_HOME')
        ed.idle(2)
    _744dc8ad_cold_starts(ed, r, [False, True, False], prelude=prelude)


# 2026-10-11 00:20 level 5 attempt 3
_744dc8ad_HOOK = 'debug.zesty.hook.load_image_filter'


def _744dc8ad_cold_start(ed, starts, label):
    """Force-stop, arm the hook, then cold-start the process with each `starts` command until it crashes."""
    ed.step(f'cold start with libImageFilter missing ({label})')
    ed.mon.allow_death = True                        # our own force-stop is not the crash
    ed.dev.force_stop()
    time.sleep(1.5)
    ed.mon.allow_death = False
    ed.dev.setprop(_744dc8ad_HOOK, '1')
    try:
        for cmd in starts:                           # field: same install, restarted again a few seconds later
            ed.dev.marker(f'744dc8ad start: {label}')
            ed.dev.sh(cmd) if cmd else ed.dev.launch()
            ed.idle(5)                               # FATAL EXCEPTION main -> AppFailure is raised here
        if ed.dev.pid() == '':
            raise UIError(f'{label}: the process never started (start command reached nothing)')
        raise UIError(f'{label}: app started normally, hook {_744dc8ad_HOOK} not in this build')
    finally:
        ed.dev.setprop(_744dc8ad_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l5_3_a(ed, r):
    """vivo V2217 x13 + vivo V2044 x5 (FOREGROUND): user taps the launcher icon -> UnsatisfiedLinkError libImageFilter in MainApplication.onCreate."""
    _744dc8ad_cold_start(ed, [None, None, None], 'launcher, FOREGROUND')


@scenario('nightshift', 'auto', 'nodraft')
def ns_744dc8ad_l5_3_b(ed, r):
    """QEMU 8.1 x2 + vivo BACKGROUND events: a system broadcast cold-starts the process, no activity -> same loadLibrary crash."""
    # -f 32 = FLAG_INCLUDE_STOPPED_PACKAGES (we just force-stopped); both receivers are exported with DUMP, which shell has
    _744dc8ad_cold_start(ed, [
        'am broadcast -f 32 -a androidx.profileinstaller.action.SAVE_PROFILE '
        '-n com.myzesty/androidx.profileinstaller.ProfileInstallReceiver',
        'am broadcast -f 32 -a androidx.work.diagnostics.REQUEST_DIAGNOSTICS '
        '-n com.myzesty/androidx.work.impl.diagnostics.DiagnosticsReceiver',
    ], 'broadcast, BACKGROUND')
