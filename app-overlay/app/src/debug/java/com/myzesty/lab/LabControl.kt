package com.myzesty.lab

// DEBUG BUILDS ONLY (src/debug). Night Shift lab control: setup shortcuts so lab runs skip slow UI navigation.
// Every command runs the same app code a user's tap runs (same Activity, same extras, same picker result); the
// crash trigger itself is always real input from the lab. Send with:
//   adb shell am broadcast -a com.myzesty.LAB -p com.myzesty --es cmd <ping|open_draft|open_draft_id|drafts|open_slideshow|slideshow_add> [--ei n 4] [--ei index 0] [--es id <draft id>]
//   ENGINE REPLAY (Night Shift turbo): --es cmd jni --es calls "destroyPlayer();createPlayer();getMediaStartingTime(0,1)"
//   [--es thread bg|main] [--ei repeat 1]: calls Player's static engine methods directly, in order (sleep(ms) waits).
//   Only primitive / String arguments. Each call logs "LAB step jni ..."; the end logs "LAB ok jni done ...".
//   A replay is a LEAD and a fast fix check, never the proof: the proof is still a real-tap run.
// Every answer is one logcat line with tag ZestyLab: "LAB ok <cmd> ..." or "LAB fail <cmd>: ...".

import android.app.Activity
import android.app.Application
import android.content.BroadcastReceiver
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.database.Cursor
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Log
import androidx.core.os.bundleOf
import androidx.fragment.app.FragmentActivity
import com.common.myzesty.utils.Constants
import com.common.myzesty.videoPlayer.DestroyPlayerManager
import com.myzesty.quickcut.ui.QuickCutActivity
import com.picker.gallery.model.GalleryData
import com.video.myzesty.PlayerActivity
import com.video.myzesty.draft.DraftManager
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.io.File
import java.lang.ref.WeakReference

class LabControl : ContentProvider() {
    companion object {
        const val TAG = "ZestyLab"
        @Volatile var top: WeakReference<Activity>? = null
        @Volatile var resumed = 0          // activities of this app currently resumed (0 = app not in front)
        fun topActivity(): Activity? = top?.get()
    }

    override fun onCreate(): Boolean {
        (context?.applicationContext as? Application)?.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityResumed(a: Activity) { top = WeakReference(a); resumed++ }
            override fun onActivityCreated(a: Activity, b: Bundle?) { top = WeakReference(a) }
            override fun onActivityStarted(a: Activity) {}
            override fun onActivityPaused(a: Activity) { if (resumed > 0) resumed-- }
            override fun onActivityStopped(a: Activity) {}
            override fun onActivitySaveInstanceState(a: Activity, b: Bundle) {}
            override fun onActivityDestroyed(a: Activity) {}
        })
        startMainWatch()
        Log.i(TAG, "LAB ready")
        return true
    }

    // Main-thread watch (lab only): when main does not answer a ping for 4 s, log its stack as "LAB MAINSTACK" lines.
    // The lab phone is not rooted, so debuggerd cannot dump the app, and the system ANR record is sometimes lost
    // ("contents lost"); this keeps the hung main stack in logcat so Night Shift can match the field frames.
    /** Stall threshold for the main-thread watch: 4 s by default; `adb shell setprop debug.zesty.mainwatch_ms 300`
     *  makes it sample short blocks too (to find WHAT blocks main for a fraction of a second). */
    private fun watchLimitMs(): Int = try {
        val c = Class.forName("android.os.SystemProperties")
        (c.getMethod("getInt", String::class.java, Int::class.javaPrimitiveType)
            .invoke(null, "debug.zesty.mainwatch_ms", 4000) as Int).coerceIn(100, 10000)
    } catch (e: Throwable) { 4000 }

    private fun startMainWatch() {
        val main = Handler(Looper.getMainLooper())
        Thread({
            var seq = 0L
            while (true) {
                try {
                    val answered = java.util.concurrent.atomic.AtomicBoolean(false)
                    val my = ++seq
                    main.post { answered.set(true) }
                    var waited = 0
                    val limit = watchLimitMs()
                    val step = if (limit < 1000) 50L else 250L
                    while (!answered.get() && waited < limit) { Thread.sleep(step); waited += step.toInt() }
                    var dumps = 0
                    while (!answered.get() && dumps < 4) {
                        val st = Looper.getMainLooper().thread.stackTrace
                        Log.w(TAG, "LAB MAINSTACK begin stall=${limit}ms+${dumps * 3}s seq=$my")
                        st.take(60).forEach { Log.w(TAG, "LAB MAINSTACK   at $it") }
                        Log.w(TAG, "LAB MAINSTACK end")
                        dumps++
                        var w = 0
                        while (!answered.get() && w < 3000) { Thread.sleep(250); w += 250 }
                    }
                    Thread.sleep(if (limit < 1000) 20L else 500L)
                } catch (e: Throwable) {
                    Log.w(TAG, "LAB main watch: $e")
                }
            }
        }, "lab-main-watch").apply { isDaemon = true; start() }
    }

    override fun query(u: Uri, p: Array<String>?, s: String?, a: Array<String>?, o: String?): Cursor? = null
    override fun getType(u: Uri): String? = null
    override fun insert(u: Uri, v: ContentValues?): Uri? = null
    override fun delete(u: Uri, s: String?, a: Array<String>?): Int = 0
    override fun update(u: Uri, v: ContentValues?, s: String?, a: Array<String>?): Int = 0
}

class LabControlReceiver : BroadcastReceiver() {
    private val main = Handler(Looper.getMainLooper())

    override fun onReceive(ctx: Context, intent: Intent) {
        val cmd = intent.getStringExtra("cmd") ?: return
        val n = intent.getIntExtra("n", 1)
        val index = intent.getIntExtra("index", 0)
        main.post {
            try {
                when (cmd) {
                    "ping" -> ok(cmd, "top=${LabControl.topActivity()?.javaClass?.simpleName}")
                    "ui" -> uiDump(intent.getStringExtra("nonce") ?: "")
                    "open_draft" -> openDraft(index)
                    "open_draft_id" -> openDraftId(intent.getStringExtra("id") ?: "")
                    "drafts" -> listDrafts()
                    "open_slideshow" -> openSlideshow(n)
                    "slideshow_add" -> deliverMedia(cmd, n, pickerMustBeOpen = false)
                    "jni" -> engineCalls(intent.getStringExtra("calls") ?: "", intent.getStringExtra("thread") ?: "bg",
                                         intent.getIntExtra("repeat", 1))
                    else -> fail(cmd, "unknown command")
                }
            } catch (t: Throwable) {
                fail(cmd, t.toString())
            }
        }
    }

    private fun ok(cmd: String, msg: String = "") { Log.i(LabControl.TAG, "LAB ok $cmd $msg".trim()) }
    private fun fail(cmd: String, msg: String) { Log.w(LabControl.TAG, "LAB fail $cmd: $msg") }

    /** Every draft in My Projects as one line each: "LAB draft <index> id=<id> name=<name> videos=<n> images=<n>",
     *  then "LAB ok drafts n=<count>". Night Shift keeps the ids of the projects it built (lab fixtures). */
    private fun listDrafts() {
        MainScope().launch {
            val drafts = DraftManager.getDraftList().first()
            drafts.forEachIndexed { i, d ->
                Log.i(LabControl.TAG, "LAB draft $i id=${d.id} name=${d.name} videos=${d.videoCount} images=${d.imageCount}")
            }
            ok("drafts", "n=${drafts.size}")
        }
    }

    /** Same as tapping the draft with this id in My Projects (a lab fixture Night Shift built earlier). */
    private fun openDraftId(id: String) {
        MainScope().launch {
            val drafts = DraftManager.getDraftList().first()
            val i = drafts.indexOfFirst { it.id.toString() == id }
            if (i < 0) return@launch fail("open_draft_id", "no draft with id=$id (have ${drafts.size})")
            openDraftAt(i, "open_draft_id")
        }
    }

    /** Same as tapping draft #index in My Projects (DraftListFragment): set the current draft, start the editor. */
    private fun openDraft(index: Int) = openDraftAt(index, "open_draft")

    private fun openDraftAt(index: Int, cmd: String) {
        MainScope().launch {
            val drafts = DraftManager.getDraftList().first()
            val d = drafts.getOrNull(index) ?: return@launch fail(cmd, "no draft #$index (have ${drafts.size})")
            var waited = 0
            while (!DestroyPlayerManager.isDestroyCompleted() && waited < 10000) {   // the UI refuses until the old player is gone
                kotlinx.coroutines.delay(100); waited += 100
            }
            val a = LabControl.topActivity() ?: return@launch fail(cmd, "no activity")
            DraftManager.setCurrentDraft(d)
            val i = Intent(a, PlayerActivity::class.java)
            i.putExtra(Constants.EXTRA_DRAFT, true)
            i.putExtra(Constants.WIZARD_EDITOR, d.isWizardEditor)
            i.putExtra(Constants.TEMP_NAV_TYPE_FE, false)
            a.startActivity(i)
            if (a.javaClass.simpleName == "BaseVideoEditorActivity") a.finish()    // the draft list does the same
            ok(cmd, "index=$index id=${d.id}")
        }
    }

    /** Same as Home -> SlideShow -> pick the n newest clips -> Done: start QuickCutActivity(isSlideShow), then hand
     *  its picker the result the picker itself returns on Done. */
    private fun openSlideshow(n: Int) {
        val a = LabControl.topActivity() ?: return fail("open_slideshow", "no activity")
        a.startActivity(Intent(a, QuickCutActivity::class.java).putExtra("isSlideShow", true))
        var tries = 0
        fun poll() {
            val t = LabControl.topActivity()
            val picker = (t as? FragmentActivity)?.supportFragmentManager?.findFragmentByTag("Picker")
            // wait until the picker's grid shows media: closing it while its paging load still runs makes
            // AllMediaInteractor call requireActivity() on a detached fragment (an app crash the lab caused itself)
            if (t is QuickCutActivity && picker != null && picker.isResumed && gridLoaded(picker.view)) {
                main.postDelayed({ deliverMedia("open_slideshow", n, pickerMustBeOpen = true) }, 600)
            } else if (++tries < 75) {
                main.postDelayed({ poll() }, 200)
            } else {
                fail("open_slideshow", "picker did not open in 15 s (top=${t?.javaClass?.simpleName})")
            }
        }
        main.postDelayed({ poll() }, 200)
    }

    private fun gridLoaded(v: android.view.View?): Boolean {
        if (v is android.view.ViewGroup && v.javaClass.name.endsWith("RecyclerView") && v.isShown && v.childCount > 0) return true
        if (v is android.view.ViewGroup) for (i in 0 until v.childCount) if (gridLoaded(v.getChildAt(i))) return true
        return false
    }

    private fun deliverMedia(cmd: String, n: Int, pickerMustBeOpen: Boolean) {
        val fa = LabControl.topActivity() as? QuickCutActivity ?: return fail(cmd, "top is not QuickCutActivity")
        val list = newestVideos(fa, n)
        if (list.size < n) return fail(cmd, "only ${list.size} videos on the phone")
        val fm = fa.supportFragmentManager
        fm.setFragmentResult(Constants.REQUEST_RESULT_CODE, bundleOf("MEDIA" to list))
        if (pickerMustBeOpen && fm.findFragmentByTag("Picker") != null) fm.popBackStack()   // the picker closes itself on Done
        ok(cmd, "n=${list.size} " + list.joinToString(",") { File(it.photoUri).name })
    }

    /** The n newest items of the picker's default tab (photos + videos, newest first), filled the way the picker fills
     *  them (AllMediaInteractor), marked selected: the same list tapping the top n tiles and Done produces. */
    private fun newestVideos(ctx: Context, n: Int): ArrayList<GalleryData> {
        val out = ArrayList<GalleryData>()
        val VIDEO = MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO
        val IMAGE = MediaStore.Files.FileColumns.MEDIA_TYPE_IMAGE
        val cols = arrayOf("_id", "_data", "date_added", "media_type", "mime_type", "_size", "width", "height", "duration")
        val sel = "media_type=$VIDEO OR (media_type=$IMAGE AND mime_type IN ('image/jpeg','image/jpg','image/png'))"
        ctx.contentResolver.query(MediaStore.Files.getContentUri("external"), cols, sel, null, "date_added DESC")?.use { c ->
            var i = 0
            while (c.moveToNext() && out.size < n) {
                val data = c.getString(1) ?: continue
                val g = GalleryData()
                g.albumName = File(data).parentFile?.name ?: ""
                g.photoUri = data
                g.originalUri = data
                g.id = c.getString(0).toInt()
                g.dateAdded = c.getString(2) ?: ""
                g.size = c.getLong(5).toInt()
                if (c.getInt(3) == VIDEO) {
                    g.mediaType = VIDEO
                    g.duration = c.getInt(8)
                } else {
                    g.mediaType = IMAGE
                    val swap = try {
                        val o = android.media.ExifInterface(data).getAttributeInt(
                            android.media.ExifInterface.TAG_ORIENTATION, 1)
                        o == android.media.ExifInterface.ORIENTATION_ROTATE_90 ||
                            o == android.media.ExifInterface.ORIENTATION_ROTATE_270
                    } catch (e: Exception) { false }
                    g.width = if (swap) c.getInt(7) else c.getInt(6)
                    g.height = if (swap) c.getInt(6) else c.getInt(7)
                }
                g.importId = i++
                g.isSelected = true
                out.add(g)
            }
        }
        return out
    }

    /** Engine replay: Player's @JvmStatic external methods by name, in order, with literal arguments. */
    private fun engineCalls(calls: String, thread: String, repeat: Int) {
        val player = Class.forName("com.common.myzesty.videoPlayer.Player")
        val statics = player.methods.filter { java.lang.reflect.Modifier.isStatic(it.modifiers) }
        val steps = calls.split(';').map { it.trim() }.filter { it.isNotEmpty() }
        val parsed = steps.map { s ->
            val m = Regex("""^(\w+)\s*\((.*)\)$""").find(s) ?: throw IllegalArgumentException("bad call: $s")
            val name = m.groupValues[1]
            val raw = m.groupValues[2].trim()
            val args = if (raw.isEmpty()) emptyList() else raw.split(',').map { it.trim() }
            Triple(name, args, s)
        }
        val work = Runnable {
            try {
                for (k in 0 until maxOf(1, repeat)) {
                    for ((name, args, src) in parsed) {
                        if (name == "sleep") { Thread.sleep(args.firstOrNull()?.toLongOrNull() ?: 0L); continue }
                        val meth = statics.firstOrNull { it.name == name && it.parameterTypes.size == args.size }
                            ?: throw IllegalArgumentException("no static Player.$name with ${args.size} argument(s)")
                        val vals = meth.parameterTypes.zip(args).map { (ty, a) ->
                            when (ty) {
                                Int::class.javaPrimitiveType -> a.toInt()
                                Long::class.javaPrimitiveType -> a.toLong()
                                Float::class.javaPrimitiveType -> a.toFloat()
                                Double::class.javaPrimitiveType -> a.toDouble()
                                Boolean::class.javaPrimitiveType -> a.toBoolean()
                                String::class.java -> a.trim('"', '\'')
                                else -> throw IllegalArgumentException("Player.$name: argument type ${ty.simpleName} not supported")
                            }
                        }.toTypedArray()
                        Log.i(LabControl.TAG, "LAB step jni call $src")
                        val r = meth.invoke(null, *vals)
                        Log.i(LabControl.TAG, "LAB step jni $src -> $r")
                    }
                }
                ok("jni", "done ${parsed.size} call(s) x${maxOf(1, repeat)}")
            } catch (t: Throwable) {
                fail("jni", (t.cause ?: t).toString())
            }
        }
        if (thread == "main") work.run() else Thread(work, "NightShiftReplay").start()
    }

    /** FAST SCREEN READ (Night Shift turbo): the app's own view tree in uiautomator's XML format, from inside the app
     *  (~20-50 ms instead of 1-5 s for `uiautomator dump`). Only while this app is in front; else "LAB fail ui" and the
     *  lab falls back to uiautomator (system dialogs, other apps, an ANR'd main thread that cannot answer). */
    private fun uiDump(nonce: String) {
        val t0 = android.os.SystemClock.uptimeMillis()
        val ctx = LabControl.topActivity()?.applicationContext ?: return fail("ui", "no activity")
        val dir0 = ctx.getExternalFilesDir(null)
        fun marker(why: String) {                      // answer at once so the lab falls back without waiting
            try { File(dir0, "ns_ui.xml").writeText("NOFRONT nonce=\"" + esc(nonce) + "\" " + why) } catch (e: Exception) {}
            fail("ui", why)
        }
        if (LabControl.resumed <= 0) return marker("app not in front")
        val roots = ArrayList<android.view.View>()
        try {                                          // every window of the app (dialogs, bottom sheets, popups)
            val wmg = Class.forName("android.view.WindowManagerGlobal")
            val inst = wmg.getMethod("getInstance").invoke(null)
            val f = wmg.getDeclaredField("mRoots"); f.isAccessible = true
            @Suppress("UNCHECKED_CAST")
            val list = ArrayList(f.get(inst) as List<Any>)
            for (r in list) {
                val v = r.javaClass.getMethod("getView").invoke(r) as? android.view.View
                if (v != null && v.isShown) roots.add(v)
            }
        } catch (t: Throwable) {
            LabControl.topActivity()?.window?.decorView?.let { roots.add(it) }
        }
        if (roots.isEmpty()) return marker("no window")
        val sb = StringBuilder("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"0\" nonce=\"")
        sb.append(esc(nonce)).append("\">")
        val res = ctx.resources
        val pkg = ctx.packageName
        fun walk(v: android.view.View, ox: Int, oy: Int) {
            if (v.visibility != android.view.View.VISIBLE) return
            val r = android.graphics.Rect()
            if (!v.getGlobalVisibleRect(r)) return
            r.offset(ox, oy)
            val id = if (v.id != android.view.View.NO_ID) try { res.getResourceName(v.id) } catch (e: Exception) { "" } else ""
            val text = (v as? android.widget.TextView)?.text?.toString() ?: ""
            val desc = v.contentDescription?.toString() ?: ""
            sb.append("<node text=\"").append(esc(text)).append("\" resource-id=\"").append(esc(id))
                .append("\" class=\"").append(esc(v.javaClass.name)).append("\" package=\"").append(pkg)
                .append("\" content-desc=\"").append(esc(desc)).append("\" clickable=\"").append(v.isClickable)
                .append("\" enabled=\"").append(v.isEnabled).append("\" bounds=\"[").append(r.left).append(',').append(r.top)
                .append("][").append(r.right).append(',').append(r.bottom).append("]\">")
            if (v is android.view.ViewGroup) for (i in 0 until v.childCount) walk(v.getChildAt(i), ox, oy)
            sb.append("</node>")
        }
        for (root in roots) {
            val loc = IntArray(2); root.getLocationOnScreen(loc)
            val lp = root.layoutParams as? android.view.WindowManager.LayoutParams
            // getGlobalVisibleRect is in the window's coordinates: shift by the window's place on the screen
            val ox = if (lp != null) loc[0] - root.left else 0
            val oy = if (lp != null) loc[1] - root.top else 0
            walk(root, ox, oy)
        }
        sb.append("</hierarchy>")
        val dir = ctx.getExternalFilesDir(null) ?: return fail("ui", "no files dir")
        val tmp = File(dir, "ns_ui.xml.tmp"); tmp.writeText(sb.toString())
        tmp.renameTo(File(dir, "ns_ui.xml"))
        ok("ui", "${File(dir, "ns_ui.xml").path} ${android.os.SystemClock.uptimeMillis() - t0}ms")
    }

    private fun esc(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")
        .replace("\n", "&#10;").filter { it.code >= 0x20 || it == '\n' }
}
