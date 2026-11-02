"""The release recipe: build the lab app from the code the users actually ran (2 Nov).

Before: the lab used the CPP base branch + the 8 crash files at the field commit, and the Kotlin modules from the
developer's working copy. On 2 Nov the working copy was on a feature branch (bg-removal-code-clean) whose Player.kt no
longer had a JNI method the C++ looks up: every lab run aborted at app start and 20+ min of repro attempts were wasted.

Now, for a crash from build <vc>:
  engine (video_gles3jni): the commit the shipped libMYJNILIB26.so was built from (symbols/<vc>/meta.json source_ref,
      pinned by ns/source.py from the .so itself), the WHOLE tree, not only the crash files.
  Kotlin modules: the commits the real app (myzesty_mobile) pinned when it carried that exact library. The app repo
      commits the engine library; symbolize.import_from_app_repo already found the app commit whose library has the
      field build's BuildId (meta.json debug_symbols = 'myzesty_mobile@<sha>'). Its submodule pins = the shipped Kotlin.
  Fallbacks, said in the log: the app's release/<version> branch tip pins; else None (the old way).
Nothing is checked out in myzesty_mobile: only git ls-tree / rev-parse (read-only)."""
import json
import os
import re
import subprocess

from . import config


def _git(repo, *a, timeout=120):
    r = subprocess.run(['git', '--no-optional-locks', '-C', repo] + list(a), capture_output=True, text=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else ''


def _pins(repo, commit):
    """{module folder name: sha} for every submodule of the app at that commit (android/java-common -> java-common)."""
    out = {}
    for ln in _git(repo, 'ls-tree', '-r', commit).splitlines():
        p = ln.split(None, 3)
        if len(p) == 4 and p[0] == '160000':
            out[os.path.basename(p[3].strip())] = p[2]
    return out


def top_build(case):
    """(version code, version name) of the build with the most events in the case."""
    vers = case.get('versions') or {}
    if not vers:
        return None, None
    top = max(vers.items(), key=lambda kv: kv[1])[0]
    m = re.search(r'\((\d+)\)', top)
    return (m.group(1) if m else None), top.split(' ')[0]


def for_case(case, cfg, log=print):
    """-> {'vc', 'version', 'engine', 'pins', 'app_commit', 'why'} or None (then the lab builds the old way)."""
    vc, vname = top_build(case)
    if not vc:
        return None
    from . import source
    mp = os.path.join(source.SYMS, vc, 'meta.json')
    meta = json.load(open(mp)) if os.path.exists(mp) else {}
    engine = meta.get('source_ref') if re.fullmatch(r'[0-9a-f]{40}', str(meta.get('source_ref') or '')) else None
    if not engine:
        try:
            engine = (source.ref_for(vc, vname, cfg) or {}).get('sha')
        except Exception:
            engine = None
    if not engine:
        log(f'release recipe: the engine commit of build {vc} is unknown; the lab builds the usual way')
        return None
    pins, app_commit, why = {}, None, ''
    from . import fulllab
    app = fulllab.checkout(cfg)
    m = re.match(r'myzesty_mobile@([0-9a-f]{7,40})', str(meta.get('debug_symbols') or ''))
    if app and m and _git(app, 'rev-parse', '--verify', '--quiet', m.group(1) + '^{commit}').strip():
        app_commit = _git(app, 'rev-parse', m.group(1)).strip()
        pins = _pins(app, app_commit)
        why = f'myzesty_mobile {app_commit[:10]} carries the shipped engine library (same BuildId), its module pins'
    if app and not pins and vname:
        subprocess.run(['git', '-C', app, 'fetch', '-q', '--no-tags', 'origin',
                        f'+refs/heads/release/{vname}:refs/nightshift/app/release/{vname}'], capture_output=True, timeout=300)
        for r in (f'refs/nightshift/app/release/{vname}', f'origin/release/{vname}', f'release/{vname}'):
            c = _git(app, 'rev-parse', '--verify', '--quiet', r + '^{commit}').strip()
            if c:
                app_commit, pins = c, _pins(app, c)
                why = f'myzesty_mobile {r.split("refs/nightshift/app/")[-1]} tip {c[:10]} (the release branch), its module pins'
                break
    if not app:
        why = 'no myzesty_mobile folder on this computer: Kotlin modules from the newest sprint'
    elif not pins:
        why = f'myzesty_mobile has no commit with this exact library and no release/{vname} branch: Kotlin modules from the newest sprint'
    # 2 Nov: pin only the modules that talk to the engine (JNI declarations, engine calls). The others (gallerypicker,
    # overlay_collage, u2net) at their release commits did not configure with video_gles3jni's Gradle ('A problem
    # occurred configuring project :gallerypicker': no `namespace`, which myzesty_mobile's older Gradle did not need);
    # they never touch the engine, so the working copy's / newest sprint's copies are fine.
    pins = {k: v for k, v in pins.items() if k in ENGINE_SIDE}
    return {'vc': vc, 'version': vname, 'engine': engine, 'pins': pins, 'app_commit': app_commit, 'why': why}


ENGINE_SIDE = ('java-common', 'android-video-editor-module')
