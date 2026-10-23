"""Optional model step. Deterministic data goes in, narrative comes out; numbers are never changed by the model.

provider 'claude-cli' runs the company-account `claude -p` (already on the Mac) with the skill text as the system
prompt. provider 'none' only writes the prompt pack to out/, for a human to paste. No API keys live here.
"""
import os
import shutil
import subprocess

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def skill_text(name: str) -> str:
    p = os.path.join(HERE, 'skills', name, 'SKILL.md')
    return open(p, encoding='utf-8').read() if os.path.exists(p) else ''


import threading
SANDBOX = os.path.expanduser('~/.nightshift_blind/repo')
_SB_LOCK = threading.Lock()
_SRC_EXT = ('.kt', '.java', '.cpp', '.cc', '.c', '.h', '.hpp', '.inl', '.xml', '.gradle', '.kts', '.pro', '.cmake', '.properties',
            '.aidl', '.glsl', '.vert', '.frag', '.json')
_SKIP_DIRS = {'.git', 'build', '.cxx', '.gradle', 'assets', 'jniLibs', '.idea', 'node_modules', 'generated', 'intermediates'}


def blind_sandbox():
    """Blind tests: a copy of the repo holding ONLY module sources (src/ trees, Gradle/CMake files) and the lab harness
    API (zesty.py with crash ids redacted, screen map). No .git, no Night Shift notes/results, no hand-written repros,
    no reports, no stray temp copies (only known source extensions are copied), no .claude settings. Synced
    incrementally before every blind model call; the model runs there."""
    import re as _re
    from . import config
    repo = getattr(config, 'LAB', config.REPO).rstrip('/')   # module sources: the lab folder during a job
    want = {}
    for top in ('build.gradle', 'build.gradle.kts', 'settings.gradle', 'settings.gradle.kts', 'gradle.properties'):
        if os.path.isfile(os.path.join(repo, top)):
            want[top] = os.path.join(repo, top)
    for mod in sorted(os.listdir(repo)):
        md = os.path.join(repo, mod)
        if mod.startswith('.') or not os.path.isdir(os.path.join(md, 'src')):
            continue
        for fn in ('build.gradle', 'build.gradle.kts', 'CMakeLists.txt', 'proguard-rules.pro'):
            if os.path.isfile(os.path.join(md, fn)):
                want[f'{mod}/{fn}'] = os.path.join(md, fn)
        for root, dirs, files in os.walk(os.path.join(md, 'src')):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith('.')]
            for fn in files:
                if fn.startswith('.') or not (fn.endswith(_SRC_EXT) or fn == 'CMakeLists.txt'):
                    continue
                full = os.path.join(root, fn)
                want[os.path.relpath(full, repo)] = full
    for fn in ('zesty.py', 'screen_map.json'):          # lab harness API only: no scenarios, no hand-written repros
        if os.path.isfile(os.path.join(config.REPO, 'tools/stress', fn)):
            want[f'tools/stress/{fn}'] = os.path.join(config.REPO, 'tools/stress', fn)
    have = set()
    for root, dirs, files in os.walk(SANDBOX):
        for fn in files:
            have.add(os.path.relpath(os.path.join(root, fn), SANDBOX))
    for rel in have - set(want):
        try:
            os.remove(os.path.join(SANDBOX, rel))
        except OSError:
            pass
    for rel, src in want.items():
        dst = os.path.join(SANDBOX, rel)
        st = os.stat(src)
        try:
            dt = os.stat(dst)
            if dt.st_size == st.st_size and int(dt.st_mtime) == int(st.st_mtime) and rel != 'tools/stress/zesty.py':
                continue
        except OSError:
            pass
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        data = open(src, 'rb').read()
        if rel == 'tools/stress/zesty.py':
            data = _re.sub(rb'\b[0-9a-f]{32}\b|\b(Crashlytics|crash|issue) [0-9a-f]{8}\b', b'<crash id>', data)
        open(dst, 'wb').write(data)
        os.utime(dst, (st.st_atime, st.st_mtime))
    return SANDBOX


def run(skill: str, user_prompt: str, cfg: dict, out_dir: str, tag: str, tools: str = '', cwd: str = None, timeout: int = 600,
        model: str = '', deny: list = None, block: list = None, usage: dict = None) -> str:
    """tools: e.g. 'Read,Grep,Glob' lets the model read the repo itself (read-only); cwd is where it runs.
    usage: pass a dict to get the call's real usage from the CLI (input/output/cache tokens, cost, turns) filled in."""
    os.makedirs(out_dir, exist_ok=True)
    pack = os.path.join(out_dir, f'{tag}.prompt.md')
    with open(pack, 'w', encoding='utf-8') as f:
        f.write(f'<!-- system / skill: {skill} -->\n{skill_text(skill)}\n\n<!-- user -->\n{user_prompt}\n')
    provider = (cfg.get('llm', {}) or {}).get('provider', 'none')
    if provider != 'claude-cli' or not shutil.which('claude'):
        return f'_(narrative not generated: llm.provider={provider}; prompt pack written to {pack})_'
    cmd = ['claude', '-p', '--append-system-prompt', skill_text(skill)]
    if deny:                                     # blind test: run in the source-only sandbox; the real repo is off limits
        from . import config
        with _SB_LOCK:                           # parallel fix candidates share one sandbox
            cwd = blind_sandbox()
        deny = list(deny) + [f'{t}(/{config.REPO.rstrip("/")}/**)' for t in ('Read', 'Grep', 'Glob')] + ['Bash', 'WebFetch', 'WebSearch']
        cmd += ['--strict-mcp-config']             # no connectors either (Drive, Slack, Jira...): no side channel to notes
    if tools:
        cmd += ['--allowedTools', tools]
        for d in (cfg.get('_add_dirs') or []):   # extra read-only folders (e.g. the app's Kotlin repos for a PR review)
            cmd += ['--add-dir', d]
    for d in (deny or []):                       # blind test: paths the model must not read (old lab results, notes)
        cmd += ['--disallowedTools', d]
    for d in (block or []):                      # extra read blocks without the blind sandbox (e.g. the working copy)
        cmd += ['--disallowedTools', d]
    model = model or (cfg.get('llm', {}) or {}).get('model')   # per-step override (e.g. 'sonnet'), else the default
    if model:
        cmd += ['--model', str(model)]
    if usage is not None:                        # JSON output carries the real token use of the whole call (all turns)
        cmd += ['--output-format', 'json']
    try:
        import time
        bad = ('Failed to authenticate', 'API Error', 'Invalid API key', 'Please run /login', 'OAuth access token')
        for attempt in range(3):              # the CLI sometimes dies at start (exit -5, empty output): retry
            res = subprocess.run(cmd, input=user_prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd)
            txt = res.stdout.strip()
            if usage is not None and txt.startswith('{'):
                txt = _unwrap(txt, usage)
            if res.returncode == 0 and txt and not any(b in txt[:300] for b in bad):
                break
            if attempt < 2:
                print(f'[llm] claude exit {res.returncode}, retrying in {20 * (attempt + 1)} s', flush=True)
                time.sleep(20 * (attempt + 1))
        if res.returncode != 0 or not txt or any(b in txt[:300] for b in bad):
            print(f'[llm] claude step failed (exit {res.returncode}): {(txt or res.stderr)[:200]}', flush=True)
            open(os.path.join(out_dir, f'{tag}.error.txt'), 'w').write(f'exit {res.returncode}\nstdout: {txt[:2000]}\nstderr: {res.stderr[:2000]}\n')
            return ''   # never store an error message as analysis
        try:                                     # keep every answer next to its prompt (why a step was rejected)
            open(os.path.join(out_dir, f'{tag}.answer.md'), 'w', encoding='utf-8').write(txt)
        except OSError:
            pass
        return txt
    except Exception as e:  # never let the model step break the deterministic output
        return f'_(narrative skipped: {e}; prompt pack at {pack})_'


def _unwrap(raw, usage):
    """`claude -p --output-format json` -> the answer text; usage gets the real numbers."""
    import json
    try:
        d = json.loads(raw)
    except ValueError:
        return raw
    u = d.get('usage') or {}
    for k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
        usage[k] = usage.get(k, 0) + int(u.get(k) or 0)
    usage['cost_usd'] = usage.get('cost_usd', 0.0) + float(d.get('total_cost_usd') or d.get('cost_usd') or 0)
    usage['turns'] = usage.get('turns', 0) + int(d.get('num_turns') or 0)
    usage['calls'] = usage.get('calls', 0) + 1
    if d.get('is_error'):
        return ''
    return str(d.get('result') or '').strip()


_OK = {}


def claude_ok(timeout=90):
    """Can the Claude CLI on this Mac run at all (login not expired)? One tiny call per process, cached."""
    if _OK.get('v'):                       # only a GOOD answer is cached: after a /login the next job sees it
        return True
    if not shutil.which('claude'):
        _OK['v'] = False
        return False
    try:
        r = subprocess.run(['claude', '-p', '--model', 'haiku', 'Reply with the single word OK.'], capture_output=True,
                           text=True, timeout=timeout)
        out = (r.stdout + r.stderr)
        _OK['v'] = r.returncode == 0 and 'OK' in r.stdout and not any(b in out for b in ('Failed to authenticate', 'Please run /login', 'OAuth'))
    except Exception:
        _OK['v'] = False
    return _OK['v']
