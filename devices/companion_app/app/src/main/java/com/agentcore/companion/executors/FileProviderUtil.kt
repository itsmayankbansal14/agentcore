package com.agentcore.companion

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File

/** Resolves a filesystem path to a shareable content:// URI via FileProvider. */
object FileProviderUtil {
    fun uriFor(ctx: Context, path: String): Uri? {
        return try {
            val f = File(path)
            if (!f.exists()) return null
            FileProvider.getUriForFile(ctx, "com.agentcore.companion.files", f)
        } catch (_: Exception) { null }
    }
}
