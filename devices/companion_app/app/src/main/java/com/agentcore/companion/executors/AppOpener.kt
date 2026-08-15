package com.agentcore.companion

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings

/** Opens apps / URLs / settings via intents. No special permissions needed. */
class AppOpener(private val ctx: Context) {

    private val commonPackages = mapOf(
        "whatsapp" to "com.whatsapp",
        "youtube" to "com.google.android.youtube",
        "settings" to "com.android.settings",
        "camera" to "com.android.camera",
        "chrome" to "com.android.chrome",
        "gmail" to "com.google.android.gm",
        "maps" to "com.google.android.apps.maps",
        "calculator" to "com.google.android.calculator",
        "phone" to "com.google.android.dialer",
        "playstore" to "com.android.vending",
    )

    fun openApp(app: String): Triple<Boolean, Map<String, Any?>, String?> {
        val pkg = commonPackages[app.lowercase()] ?: app
        val launch: Intent? = ctx.packageManager.getLaunchIntentForPackage(pkg)
        return if (launch != null) {
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(launch)
            Triple(true, mapOf("opened" to app, "package" to pkg), null)
        } else Triple(false, emptyMap(), "app not installed: $app ($pkg)")
    }

    fun openUrl(url: String): Triple<Boolean, Map<String, Any?>, String?> {
        return try {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
            Triple(true, mapOf("url" to url), null)
        } catch (e: Exception) {
            Triple(false, emptyMap(), e.message)
        }
    }

    fun openYoutube(query: String): Triple<Boolean, Map<String, Any?>, String?> {
        val uri = if (query.isBlank()) "https://www.youtube.com"
                  else "https://www.youtube.com/results?search_query=${Uri.encode(query)}"
        return openUrl(uri)
    }

    fun openWhatsApp(number: String?): Triple<Boolean, Map<String, Any?>, String?> {
        val target = if (number.isNullOrBlank()) "https://wa.me/"
                     else "https://wa.me/${number.trim()}"
        return openUrl(target)
    }

    fun openSettings(panel: String): Triple<Boolean, Map<String, Any?>, String?> {
        val action = when (panel.lowercase()) {
            "wifi" -> Settings.Panel.ACTION_WIFI
            "bluetooth" -> Settings.Panel.ACTION_BLUETOOTH
            "battery" -> Settings.Panel.ACTION_BATTERY_SAVER
            "internet", "data" -> Settings.Panel.ACTION_INTERNET_CONNECTIVITY
            else -> Settings.ACTION_SETTINGS
        }
        return try {
            ctx.startActivity(Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Triple(true, mapOf("panel" to panel), null)
        } catch (e: Exception) {
            Triple(false, emptyMap(), e.message)
        }
    }
}
