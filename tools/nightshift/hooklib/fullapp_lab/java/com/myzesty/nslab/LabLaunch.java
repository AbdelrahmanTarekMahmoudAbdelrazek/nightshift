package com.myzesty.nslab;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * Night Shift lab door (debug lab build only): opens one of the app's OWN screens the way Android, a deep link or a
 * notification can, including with missing or empty extras, which adb cannot do for a non-exported activity.
 *
 *   adb shell am broadcast -f 0x20 -a com.myzesty.LAB_LAUNCH -p com.myzesty --es cls <activity class> \
 *       [--es xs "Type=;Title=Fonts"] [--es xi "count=3"] [--ez xb_flag true]
 *
 * xs: string extras "key=value;key2=" (an empty value = an empty string extra; a key absent = no extra at all).
 * Logs "LAB ok launch <cls>" or "LAB fail launch <reason>" under the ZestyLab tag.
 */
public class LabLaunch extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent in) {
        String cls = in.getStringExtra("cls");
        try {
            if (cls == null || cls.isEmpty()) throw new IllegalArgumentException("no cls");
            if (cls.startsWith(".")) cls = context.getPackageName() + cls;
            Intent out = new Intent();
            out.setClassName(context.getPackageName(), cls);
            out.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            String xs = in.getStringExtra("xs");
            if (xs != null) {
                for (String kv : xs.split(";")) {
                    if (kv.isEmpty()) continue;
                    int eq = kv.indexOf('=');
                    out.putExtra(eq < 0 ? kv : kv.substring(0, eq), eq < 0 ? "" : kv.substring(eq + 1));
                }
            }
            String xi = in.getStringExtra("xi");
            if (xi != null) {
                for (String kv : xi.split(";")) {
                    int eq = kv.indexOf('=');
                    if (eq > 0) out.putExtra(kv.substring(0, eq), Integer.parseInt(kv.substring(eq + 1)));
                }
            }
            context.startActivity(out);
            Log.i("ZestyLab", "LAB ok launch " + cls + " extras=" + (out.getExtras() == null ? "none" : out.getExtras().keySet()));
        } catch (Throwable t) {
            Log.i("ZestyLab", "LAB fail launch " + cls + ": " + t);
        }
    }
}
