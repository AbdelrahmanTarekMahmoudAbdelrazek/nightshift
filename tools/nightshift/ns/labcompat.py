"""Lab-only build compatibility for the RELEASE Kotlin modules (3 Nov).

The release recipe (ns/recipe.py) wants the Kotlin the users had: the module commits the shipped app (myzesty_mobile)
pinned. Two things stopped those commits from building inside video_gles3jni's lab app:
  1. java-common of a release depends on React Native (com.facebook.react:react-android, :react-native-screens), which
     only the full app builds. It uses only a handful of React Native classes, in two screens that are never part of
     an editor/engine crash (sign-up, AI container). The lab replaces the two dependencies with tiny stand-ins of those
     classes: the screens compile and show nothing.
  2. Older modules (e.g. gallerypicker at a release) have no `namespace` in build.gradle; the lab's newer Android Gradle
     plugin requires it. The lab adds it from the module's AndroidManifest package.
Everything here changes ONLY the lab folder's copy of a module (~/.nightshift_lab/...), never a working copy, never git
history. Each change is logged by the caller."""
import os
import re

STUB_DIR = os.path.join('src', 'main', 'java', 'nslab_rn_stubs')
MARK = '// nslab-compat:'

STUBS = {
    'com/facebook/react/NsLabReact.kt': '''package com.facebook.react

// Night Shift LAB ONLY: stand-ins for the few React Native classes java-common uses (sign-up / AI screens). The real
// app (myzesty_mobile) has React Native; the lab app does not. These screens show nothing in the lab.
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import com.facebook.react.bridge.ReactContext
import com.facebook.react.modules.core.DefaultHardwareBackBtnHandler

interface ReactApplication {
    val reactNativeHost: ReactNativeHost
}

open class ReactNativeHost {
    open val reactInstanceManager: ReactInstanceManager = ReactInstanceManager()
}

open class ReactInstanceManager {
    open val currentReactContext: ReactContext? get() = null
    open fun onHostResume(activity: Activity?) {}
    open fun onHostResume(activity: Activity?, defaultBackButtonImpl: DefaultHardwareBackBtnHandler) {}
    open fun onHostPause() {}
    open fun onHostPause(activity: Activity?) {}
    open fun onHostDestroy() {}
    open fun onHostDestroy(activity: Activity?) {}
    open fun onBackPressed() {}
    open fun onActivityResult(activity: Activity?, requestCode: Int, resultCode: Int, data: Intent?) {}
}

open class ReactRootView(context: Context) : FrameLayout(context) {
    open fun startReactApplication(reactInstanceManager: ReactInstanceManager?, moduleName: String?,
                                   initialProperties: Bundle? = null) {}
    open fun unmountReactApplication() {}
}

open class ReactActivity : AppCompatActivity(), DefaultHardwareBackBtnHandler {
    override fun invokeDefaultOnBackPressed() {
        onBackPressedDispatcher.onBackPressed()
    }
}
''',
    'com/facebook/react/bridge/NsLabReactContext.kt': '''package com.facebook.react.bridge

// Night Shift LAB ONLY (see com/facebook/react/NsLabReact.kt)
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper

open class ReactContext(base: Context) : ContextWrapper(base) {
    open val currentActivity: Activity? get() = null
    open fun <T> getJSModule(jsInterface: Class<T>): T =
        throw UnsupportedOperationException("React Native is not in the Night Shift lab app")
}
''',
    'com/facebook/react/modules/core/NsLabCore.kt': '''package com.facebook.react.modules.core

// Night Shift LAB ONLY (see com/facebook/react/NsLabReact.kt)
fun interface DefaultHardwareBackBtnHandler {
    fun invokeDefaultOnBackPressed()
}

class DeviceEventManagerModule {
    interface RCTDeviceEventEmitter {
        fun emit(eventName: String, data: Any?)
    }
}
''',
    'com/swmansion/rnscreens/fragment/restoration/NsLabScreens.kt': '''package com.swmansion.rnscreens.fragment.restoration

// Night Shift LAB ONLY (see com/facebook/react/NsLabReact.kt)
class RNScreensFragmentFactory : androidx.fragment.app.FragmentFactory()
''',
}

RN_DEP = re.compile(r'^(\s*)(implementation|api)\s*[\( ]\s*(project\(\s*[\'"]:react-native-[\w-]+[\'"]\s*\)|[\'"]com\.facebook\.react:[^\'"]+[\'"])\s*\)?\s*$',
                    re.M)


def _gradle(mod):
    for n in ('build.gradle', 'build.gradle.kts'):
        p = os.path.join(mod, n)
        if os.path.exists(p):
            return p
    return None


def apply(mod, name, log=print):
    """Make the lab copy of one Kotlin module build in video_gles3jni's lab app. Idempotent. -> list of changes."""
    gp = _gradle(mod)
    if not gp:
        return []
    g = open(gp, encoding='utf-8', errors='replace').read()
    changes = []
    if RN_DEP.search(g):
        g = RN_DEP.sub(lambda m: f'{m.group(1)}{MARK} {m.group(0).strip()}', g)
        uses = set()
        for root, _d, files in os.walk(os.path.join(mod, 'src')):
            if 'nslab_rn_stubs' in root:
                continue
            for f in files:
                if f.endswith(('.kt', '.java')):
                    t = open(os.path.join(root, f), encoding='utf-8', errors='replace').read()
                    uses |= set(re.findall(r'^import (com\.facebook\.react[\w.]*|com\.swmansion[\w.]*)', t, re.M))
        for rel, body in STUBS.items():
            p = os.path.join(mod, STUB_DIR, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'w', encoding='utf-8').write(body)
        known = {'com.facebook.react.ReactApplication', 'com.facebook.react.ReactInstanceManager',
                 'com.facebook.react.ReactRootView', 'com.facebook.react.ReactActivity', 'com.facebook.react.ReactNativeHost',
                 'com.facebook.react.bridge.ReactContext', 'com.facebook.react.modules.core.DeviceEventManagerModule',
                 'com.facebook.react.modules.core.DefaultHardwareBackBtnHandler',
                 'com.swmansion.rnscreens.fragment.restoration.RNScreensFragmentFactory'}
        missing = sorted(uses - known)
        changes.append(f'{name}: React Native replaced by lab stand-ins (sign-up / AI screens show nothing in the lab)'
                       + (f'; NOT covered yet: {", ".join(missing)} (the build will say if it matters)' if missing else ''))
    if 'namespace' not in g:
        mf = os.path.join(mod, 'src', 'main', 'AndroidManifest.xml')
        m = re.search(r'package="([\w.]+)"', open(mf, errors='replace').read()) if os.path.exists(mf) else None
        if m and re.search(r'^\s*android\s*\{', g, re.M):
            g = re.sub(r'^(\s*android\s*\{)', lambda x: f'{x.group(1)}\n    namespace \'{m.group(1)}\'   {MARK} the lab Gradle plugin needs it',
                       g, count=1, flags=re.M)
            changes.append(f'{name}: namespace {m.group(1)} added (this older module has none; the lab Gradle plugin needs it)')
    if changes:
        open(gp, 'w', encoding='utf-8').write(g)
    return changes
