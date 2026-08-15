package com.agentcore.companion

import android.app.usage.UsageStatsManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context

object ClipboardExecutor {
    fun handle(ctx: Context, action: String, text: String?): Triple<Boolean, Map<String, Any?>, String?> {
        val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        return when (action) {
            "get" -> {
                val clip = cm.primaryClip
                val value = clip?.getItemAt(0)?.text?.toString() ?: ""
                Triple(true, mapOf("clipboard" to value), null)
            }
            "set" -> {
                cm.setPrimaryClip(ClipData.newPlainText("agentcore", text ?: ""))
                Triple(true, mapOf("set" to (text ?: "")), null)
            }
            else -> Triple(false, emptyMap(), "unknown clipboard action $action")
        }
    }
}

object ForegroundApp {
    /** Requires Usage Access permission (optional feature; degrades to "unknown"). */
    fun get(ctx: Context): String {
        return try {
            val um = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
            val end = System.currentTimeMillis()
            val stats = um.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, end - 60_000, end)
            stats.maxByOrNull { it.lastTimeUsed }?.packageName ?: "unknown"
        } catch (_: Exception) { "unknown" }
    }
}
