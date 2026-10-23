"""Which device does Night Shift's adb / gradle install address? Prints ANDROID_SERIAL as the worker sees it and adb's view."""
import os, subprocess
print('ANDROID_SERIAL =', os.environ.get('ANDROID_SERIAL'))
print(subprocess.run(['adb', 'devices', '-l'], capture_output=True, text=True).stdout)
print('adb (no -s) talks to:', subprocess.run(['adb', 'shell', 'getprop', 'ro.product.model'], capture_output=True, text=True).stdout.strip() or '(error)')
