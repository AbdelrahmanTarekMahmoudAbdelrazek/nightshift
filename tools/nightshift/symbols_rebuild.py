#!/usr/bin/env python3
"""Full debug symbols (file:line) for a release build, without anyone sending the .aab.

Google Play and Crashlytics only take the release's debug symbols; nothing gives them back. So: check out the exact
commit the build was made from (ns/source.py matched it from the shipped .so), build the release native library on this
Mac (gradle mergeProductionReleaseNativeLibs, arm64 only; no APK, no signing, nothing installed or uploaded), and keep the
unstripped libMYJNILIB26.so as <store>/<versionCode>/libMYJNILIB26.so.dbg.

It is used ONLY when it provably is the shipped code: the same BuildId as the Google Play .so, or (when the BuildId
differs only because of build paths) a byte-identical .text section at the same address. Otherwise it is discarded and
the board keeps asking for the .aab. Builds sharing one BuildId (800054890 and 800054889) get the result together.
Never touches the working copy: the build runs in a worktree under ~/.nightshift_symbols/.

usage: symbols_rebuild.py --id <job id> --vc 800054890[,800054889]"""
import argparse, glob, hashlib, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ns import config, source, symbolize          # noqa: E402

REPO = config.REPO
WT_ROOT = os.path.expanduser('~/.nightshift_symbols')
LIB = 'libMYJNILIB26.so'
GRADLE = './gradlew :app:mergeProductionReleaseReleaseNativeLibs -Pandroid.injected.build.abi=arm64-v8a --console=plain'   # flavor productionRelease + build type release
STATE = os.path.join(HERE, 'out', 'releases_state.json')


def sh(cmd, cwd=REPO, timeout=600, check=True):
    print(f'$ {cmd}', flush=True)
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout, errors='replace')
    if check and r.returncode != 0:
        raise RuntimeError(f'{cmd[:80]} failed: {(r.stderr or r.stdout)[-600:]}')
    return r.stdout


def section(path, name):
    e = symbolize.Elf(path)
    for s in e.sections:
        if s['sname'] == name and s['type'] != 8:   # 8 = NOBITS
            return s['addr'], e.d[s['off']:s['off'] + s['size']]
    return None, b''


def tree(sha):
    """A worktree of the build's commit with the submodules that commit pins."""
    wt = os.path.join(WT_ROOT, sha[:12])
    if not os.path.isdir(os.path.join(wt, 'app')):
        os.makedirs(WT_ROOT, exist_ok=True)
        sh('git worktree prune', check=False)
        sh(f'git -c core.autocrlf=false worktree add --detach --force "{wt}" {sha}', timeout=900)
    for ln in sh(f'git ls-tree -r {sha}').splitlines():
        m = re.match(r'160000 commit ([0-9a-f]{40})\t(.+)$', ln)
        if not m:
            continue
        pin, sm = m.group(1), m.group(2)
        d, src = os.path.join(wt, sm), os.path.join(REPO, sm)
        if not os.path.isdir(src) or (os.path.isdir(d) and os.listdir(d)):
            continue
        if os.path.isdir(d):
            os.rmdir(d)
        have = subprocess.run(['git', '-C', src, 'cat-file', '-e', f'{pin}^{{commit}}'], capture_output=True).returncode == 0
        if have:
            sh(f'git -C "{src}" worktree prune', check=False)
            sh(f'git -C "{src}" -c core.autocrlf=false worktree add --detach --force "{d}" {pin}', timeout=900)
        else:                                      # the pinned commit is not here: use the lab's copy (the check below decides)
            print(f'  submodule {sm}: pinned {pin[:10]} not in the local clone; using the lab copy', flush=True)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            os.symlink(src, d)
    ex = os.path.join(REPO, 'extra')                 # untracked third-party native libraries the build needs
    for name in sorted(os.listdir(ex)) if os.path.isdir(ex) else []:
        s, d = os.path.join(ex, name), os.path.join(wt, 'extra', name)
        if os.path.isdir(s) and name != 'build' and not os.path.lexists(d):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            os.symlink(s, d)
    for f in ['local.properties', 'app/google-services.json', 'keystore.properties']:
        if os.path.exists(os.path.join(REPO, f)) and not os.path.exists(os.path.join(wt, f)):
            shutil.copy2(os.path.join(REPO, f), os.path.join(wt, f))
    return wt


def state(vc, result):
    try:
        st = json.load(open(STATE)) if os.path.exists(STATE) else {}
        st.setdefault('rebuild', {})[vc] = dict(result, at=time.strftime('%Y-%m-%d %H:%M'))
        json.dump(st, open(STATE, 'w'), indent=1)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', default='')
    ap.add_argument('--vc', required=True)
    a = ap.parse_args()
    cfg = config.load()
    codes = [c for c in re.split(r'[,; ]+', a.vc) if re.fullmatch(r'\d{6,12}', c)]
    if not codes:
        sys.exit('no version code')
    vc = codes[0]
    meta_p = os.path.join(symbolize.STORE, vc, 'meta.json')
    if not os.path.exists(meta_p):
        sys.exit(f'{vc}: no shipped .so in the symbol store yet (the sync downloads it from Google Play first)')
    meta = json.load(open(meta_p))
    shipped = symbolize.store_path(vc, LIB)
    bid = meta.get('build_id') or ''
    same = [c for c in sorted(set(codes) | {d for d in os.listdir(symbolize.STORE) if d.isdigit()})
            if os.path.exists(os.path.join(symbolize.STORE, c, 'meta.json'))
            and json.load(open(os.path.join(symbolize.STORE, c, 'meta.json'))).get('build_id') == bid]
    print(f'Rebuild symbols for {vc} ({meta.get("version_name")}), BuildId {bid[:16]}…; same binary: {", ".join(same)}', flush=True)
    src = source.ref_for(vc, meta.get('version_name'), cfg)
    if not src:
        state(vc, {'ok': False, 'why': 'the commit of this build is not known'})
        sys.exit(f'{vc}: the commit this build was made from is not known (ns/source.py found no match)')
    sha = src['sha']
    print(f'  commit: {src["ref"]} @ {sha[:10]}', flush=True)
    wt = tree(sha)
    a1, t1 = section(shipped, '.text')
    tried = []

    def build_at(commit):
        """Build the release native lib at one commit (incremental in the same worktree). -> (lib, how or None, note)"""
        if commit != sha or tried:
            sh(f'git -C "{wt}" checkout --detach --force {commit}', timeout=600)
        t0 = time.time()
        r = subprocess.run(GRADLE, shell=True, cwd=wt, capture_output=True, text=True, timeout=5400, errors='replace')
        log = (r.stdout or '') + (r.stderr or '')
        open(os.path.join(WT_ROOT, f'{vc}.build.log'), 'w').write(log)
        if r.returncode != 0:
            ww = re.search(r'What went wrong:\n(.*?)(?:\n\* Try:|\Z)', log, re.S)
            return None, None, 'build failed: ' + (ww.group(1).strip() if ww else log[-400:])[:400]
        built = sorted(glob.glob(os.path.join(wt, 'app/build/intermediates/merged_native_libs/productionReleaseRelease/**/arm64-v8a', LIB),
                              recursive=True), key=os.path.getmtime)
        if not built:
            return None, None, 'the build wrote no release library'
        lib_ = built[-1]
        rb_ = symbolize.Elf(lib_).build_id() or ''
        a2, t2 = section(lib_, '.text')
        note = f'{commit[:10]}: built in {int(time.time() - t0)} s, .text {len(t2)} vs {len(t1)} bytes'
        tried.append((commit, len(t2)))
        if rb_ and rb_ == bid:
            return lib_, 'same BuildId as the Google Play build', note
        if t1 and t1 == t2 and a1 == a2:
            return lib_, (f'.text identical to the Google Play build ({len(t1)} bytes, sha1 {hashlib.sha1(t1).hexdigest()[:12]}); '
                          'BuildId differs only by build paths'), note
        return lib_, None, note

    lib, how, note = build_at(sha)
    print('  ' + note, flush=True)
    if lib is None:
        state(vc, {'ok': False, 'why': note})
        sys.exit(note)
    if not how:                                    # not this commit: walk back the branches whose JNI matches the build
        jni = source._jni_in_so(vc)
        heads = []
        for r_ in source.candidates(wide=True):
            c_ = source._jni_in_ref(r_)
            if c_ and not (jni - c_):
                heads.append(r_)
        seen, queue = {sha}, []
        for h in heads[:4]:
            out = subprocess.run(['git', '--no-optional-locks', 'log', '--first-parent', '--format=%H', '-n', '25', h, '--',
                                  'app/src/main/cpp'], cwd=REPO, capture_output=True, text=True, timeout=120).stdout.split()
            queue.append(out)
        order = []
        for i in range(25):                        # round robin over the branches, newest native change first
            for q in queue:
                if i < len(q) and q[i] not in seen:
                    seen.add(q[i]); order.append(q[i])
        budget, t_all = int(os.environ.get('NS_SYMBOL_BUILDS', '12')), time.time()
        print(f'  not identical: searching up to {budget} earlier native commits on {", ".join(heads[:4])}', flush=True)
        for c in order:
            if len(tried) > budget or time.time() - t_all > 2.4 * 3600:
                break
            if jni - source._jni_in_ref(c):        # that commit lacks functions the build has: skip without building
                continue
            lib, how, note = build_at(c)
            print('  ' + note, flush=True)
            if how:
                sha, src = c, {'ref': c, 'sha': c}
                break
        if not how:
            closest = min(tried, key=lambda t: abs(t[1] - len(t1))) if tried else None
            why = (f'no commit built here is identical to the shipped code ({len(tried)} tried'
                   + (f'; closest {closest[0][:10]}: {closest[1]} vs {len(t1)} bytes' if closest else '') + ')')
            state(vc, {'ok': False, 'why': why, 'tried': [t[0][:10] for t in tried]})
            sys.exit(why + '. Discarded: put the .aab in Downloads for file:line.')
    if not symbolize.Elf(lib).symbols()[0]:
        state(vc, {'ok': False, 'why': 'the rebuilt library has no symbols'})
        sys.exit('the rebuilt library has no symbol table')
    for c in same:
        dst = symbolize.store_path(c, LIB) + '.dbg'
        shutil.copyfile(lib, dst)
        mp = os.path.join(symbolize.STORE, c, 'meta.json')
        m = json.load(open(mp))
        m.update({'debug_symbols': f'rebuilt on the lab Mac from {src["ref"]} @ {sha[:10]}', 'debug_verified': how,
                  'debug_build_id': symbolize.Elf(lib).build_id() or '', 'debug_functions': len(symbolize.Elf(lib).symbols()[0])})
        m.update({'source_ref': sha, 'source_pinned': f'exact: the release library rebuilt from {sha[:10]} is identical to the shipped one ({how})'})
        json.dump(m, open(mp, 'w'), indent=1)
        state(c, {'ok': True, 'how': how, 'commit': sha})
    print(f'OK: full symbols (file:line) for {", ".join(same)}: {how}', flush=True)


if __name__ == '__main__':
    main()
