"""Step 8: propose a fix as a unified diff, then check it applies. Never commits, never pushes.

The model (company Claude via `claude -p`) gets the case: crashed frames, breadcrumbs, located code and callers,
and must answer with ONE unified diff. The diff is saved to out/patches/<issue>.patch and validated with
`git apply --check`. A patch only becomes a 'fix' after step 9 replays the same seed clean.
"""
import json
import os
import re
import subprocess

from . import llm, config

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(HERE, 'out')


def extract_diff(text):
    m = re.search(r'```(?:diff|patch)?\n(diff --git.*?|--- .*?)```', text, re.S)
    body = m.group(1) if m else text[text.find('diff --git'):] if 'diff --git' in text else text[text.find('--- '):] if '--- ' in text else ''
    return body.strip() + '\n' if body.strip() else ''


def match_line_endings(diff, repo):
    """Rewrite hunk lines to CRLF for target files that use CRLF, so `git apply` matches context exactly."""
    out, crlf = [], False
    for line in diff.splitlines():
        if line.startswith('diff --git') or line.startswith('--- ') or line.startswith('+++ '):
            if line.startswith('+++ b/'):
                path = os.path.join(repo, line[6:].strip())
                try:
                    crlf = b'\r\n' in open(path, 'rb').read(65536)
                except OSError:
                    crlf = False
            out.append(line + '\n')
        elif line.startswith('@@') or line.startswith('\\'):
            out.append(line + '\n')
        else:
            out.append(line.rstrip('\r') + ('\r\n' if crlf else '\n'))
    return ''.join(out)


def propose(rec, cfg):
    found = [c for c in rec.get('code', []) if c.get('found')]
    if not found:
        raise SystemExit('no located code for this case; run pull first')
    ctx = {k: rec.get(k) for k in ('id', 'title', 'subtitle', 'signal', 'frames', 'breadcrumbs', 'narrative')}
    ctx['code'] = [{k: c.get(k) for k in ('func', 'file', 'line', 'body', 'callers')} for c in found]
    files = {c['file']: open(config.repo_path(c['file']), encoding='utf-8', errors='replace').read()[:60000] for c in found[:2]}
    prompt = ('Propose the smallest safe fix for this crash. Answer with a short Cause paragraph, then ONE unified diff '
              '(git format, paths relative to repo root) in a ```diff block. Case:\n' + json.dumps(ctx, indent=1, default=str) +
              '\n\nFull files:\n' + '\n'.join(f'=== {p}\n{t}' for p, t in files.items()))
    answer = llm.run('fix-proposal', prompt, cfg, OUT, f"{rec['id']}.fix")
    os.makedirs(os.path.join(OUT, 'patches'), exist_ok=True)
    patch = os.path.join(OUT, 'patches', f"{rec['id']}.patch")
    diff = extract_diff(answer)
    if not diff:
        return None, answer, 'model returned no diff (or llm.provider is off); see the prompt pack in out/'
    diff = match_line_endings(diff, config.LAB)
    open(patch, 'w', newline='').write(diff)
    chk = subprocess.run(['git', 'apply', '--check', patch], cwd=config.LAB, capture_output=True, text=True)
    return patch, answer, ('applies cleanly' if chk.returncode == 0 else f'does NOT apply: {chk.stderr.strip()[:300]}')
