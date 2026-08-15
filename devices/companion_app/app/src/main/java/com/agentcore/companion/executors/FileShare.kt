package com.agentcore.companion

import android.content.Context
import android.content.Intent

/** Shares a local file via a chooser (no broad storage permission needed on modern Android). */
class FileShare(private val ctx: Context) {

    fun share(path: String): Triple<Boolean, Map<String, Any?>, String?> {
        val uri = FileProviderUtil.uriFor(ctx, path) ?: return Triple(
            false, emptyMap(), "file not found or outside app dirs: $path")
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "application/octet-stream"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        try {
            ctx.startActivity(Intent.createChooser(intent, "Share via AgentCore"))
            return Triple(true, mapOf("shared" to path, "uri" to uri.toString()), null)
        } catch (e: Exception) {
            return Triple(false, emptyMap(), e.message)
        }
    }
}
