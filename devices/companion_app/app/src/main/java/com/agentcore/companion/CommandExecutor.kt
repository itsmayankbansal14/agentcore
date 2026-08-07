package com.agentcore.companion

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import com.agentcore.companion.executors.ScreenshotExecutor
import com.agentcore.companion.executors.UIActionsService
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
            "device.android.screenshot" -> {
                val (ok, data) = ScreenshotExecutor.capture(ctx)
                Triple(ok, data as Map<String, Any?>, if (ok) null else (data["error"] as? String))
            }
            "device.android.ui_tap" -> {
                val svc = UIActionsService.instance
                val ok = svc?.tap((params["x"] ?: "0").toFloat(), (params["y"] ?: "0").toFloat()) ?: false
                Triple(ok, mapOf("tapped" to listOf(params["x"], params["y"])),
                       if (ok) null else "accessibility UI control not enabled")
            }
            "device.android.ui_swipe" -> {
                val svc = UIActionsService.instance
                val ok = svc?.swipe((params["x1"] ?: "0").toFloat(), (params["y1"] ?: "0").toFloat(),
                                   (params["x2"] ?: "0").toFloat(), (params["y2"] ?: "0").toFloat()) ?: false
                Triple(ok, mapOf("swiped" to listOf(params["x1"], params["y1"], params["x2"], params["y2"])),
                       if (ok) null else "accessibility UI control not enabled")
            }
            "device.android.ui_text" -> {
                val svc = UIActionsService.instance
                val ok = svc?.type(params["text"] ?: "") ?: false
                Triple(ok, mapOf("typed" to (params["text"] ?: "").take(40)),
                       if (ok) null else "accessibility UI control not enabled")
            }
            "device.android.report_capabilities" ->
                Triple(true, mapOf(
                    "executors" to listOf("open_app","open_url","open_youtube","open_whatsapp",
                                          "open_settings","read_notifications","screenshot",
                                          "get_foreground_app","clipboard","share_file",
                                          "ui_tap","ui_swipe","ui_text"),
                    "permissions" to mapOf(
                        "notification_access" to NotificationStore.recent().isNotEmpty(),
                        "usage_access" to (ForegroundApp.get(ctx) != "unknown"),
                        "accessibility" to (UIActionsService.instance != null),
                        "screen_capture" to false)), null)
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
