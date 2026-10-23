"""Install the Claude plugins Night Shift's PR review uses (Claude CLI on this Mac): Anthropic's pr-review-toolkit and
code-review, and our own nightshift-review plugin (local marketplace in tools/nightshift/claude-plugin)."""
import os, shutil, subprocess
here = os.path.dirname(os.path.abspath(__file__))
claude = shutil.which('claude') or 'claude'
local = os.path.join(here, 'claude-plugin')
steps = [
    ['plugin', 'validate', os.path.join(local, 'nightshift-review')],
    ['plugin', 'marketplace', 'add', 'anthropics/claude-code'],
    ['plugin', 'install', 'pr-review-toolkit@claude-code-plugins'],
    ['plugin', 'install', 'code-review@claude-code-plugins'],
    ['plugin', 'marketplace', 'add', local],
    ['plugin', 'install', 'nightshift-review@nightshift'],
    ['plugin', 'marketplace', 'update', 'nightshift'],
    ['plugin', 'list'],
]
log = open(os.path.join(here, 'out/batch/plugsetup.txt'), 'w')
for s in steps:
    r = subprocess.run([claude] + s, capture_output=True, text=True, timeout=300)
    out = (r.stdout + r.stderr).strip()
    line = f"$ claude {' '.join(s)}  -> rc {r.returncode}\n{out[-1500:]}\n"
    print(line, flush=True)
    log.write(line + '\n'); log.flush()
