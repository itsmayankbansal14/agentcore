package com.agentcore.companion

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import java.util.concurrent.TimeUnit

/**
 * Receives a command envelope, dispatches to the right executor,
 * then replies ack + result over the same socket (mirrors the laptop's
 * correlation-by-id contract).
 */
class CommandExecutor(private val ctx: Context) {

    private val appOpener = AppOpener(ctx)
    private val clipboard = ClipboardExecutor(ctx)
    private val fileShare = FileShare(ctx)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var ws: WebSocket? = null

    fun attach(socket: WebSocket) { ws = socket }

    fun execute(env: Protocol.Envelope) {
        val token = SecureStore.token(ctx)
        val id = env.id
        val cmd = env.cmd
        val params = env.params

        // ack first (fast acknowledgment; laptop waits for the result)
        ws?.send(Protocol.encode(Protocol.ack(id, cmd, token)))

        scope.launch {
            val (ok, data, error) = runCatching { dispatch(cmd, params) }
                .getOrElse { Triple(false, emptyMap<String, Any?>(), it.message) }
            ws?.send(Protocol.encode(
                Protocol.result(id, cmd, ok, data as Map<String, Any?>, error, token)))
        }
    }

    private fun dispatch(cmd: String, params: Map<String, String>): Triple<Boolean, Any?, String?> =
        when (cmd) {
            "device.android.open_app" -> appOpener.openApp(params["app"] ?: "")
            "device.android.open_url" -> appOpener.openUrl(params["url"] ?: "")
            "device.android.open_youtube" -> appOpener.openYoutube(params["query"] ?: "")
            "device.android.open_whatsapp" -> appOpener.openWhatsApp(params["number"])
            "device.android.open_settings" -> appOpener.openSettings(params["panel"] ?: "")
            "device.android.clipboard" -> clipboard.handle(params["action"] ?: "get", params["text"])
            "device.android.share_file" -> fileShare.share(params["path"] ?: "")
            "device.android.read_notifications" ->
                Triple(true, NotificationStore.recent(), null)
            "device.android.get_foreground_app" ->
                Triple(true, mapOf("app" to ForegroundApp.get(ctx)), null)
            "device.android.screenshot" ->
                Triple(false, emptyMap<String, Any?>(), "screen capture requires MediaProjection grant — enable in app")
            else -> Triple(false, emptyMap<String, Any?>(), "unknown command $cmd")
        }
}

/** Small holder the NotificationReaderService writes into. */
object NotificationStore {
    @Volatile var recent: List<Map<String, String>> = emptyList()
    fun add(n: Map<String, String>) {
        recent = (listOf(n) + recent).take(20)
    }
}
