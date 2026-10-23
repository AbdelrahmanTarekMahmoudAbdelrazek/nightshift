"""Copy the tail of the worker's stdout log (/tmp/nightshift-worker.log) to out/batch/workerlog.txt (tracebacks)."""
import os
src = '/tmp/nightshift-worker.log'
lines = open(src, errors='replace').read().splitlines()[-4000:] if os.path.exists(src) else ['no log']
keep = []
for i, l in enumerate(lines):
    if 'Traceback' in l or '_retry' in l:
        keep += lines[max(0, i - 3):i + 40] + ['-----']
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'batch', 'workerlog.txt'), 'w').write('\n'.join(keep[-400:]) + '\n')
print(len(keep))
