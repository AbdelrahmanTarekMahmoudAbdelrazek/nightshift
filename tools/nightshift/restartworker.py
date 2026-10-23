"""Restart the Night Shift worker so it runs the CURRENT worker.py (the long-running worker never reloads its own module).
Run as an analyse task when the queue is idle: it returns at once; 25 s later the worker is stopped and launchd
(KeepAlive) starts it again within ~30 s with the current code."""
import subprocess
subprocess.Popen(['/bin/sh', '-c', 'sleep 25; pkill -f "stress_results/lanes/"; pkill -f "sentinel.py worker"'], start_new_session=True,
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print('worker restart scheduled in 25 s; launchd brings it back with the current code')
