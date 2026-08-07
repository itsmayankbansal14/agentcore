package com.agentcore.companion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

/**
 * Foreground service holding the WebSocket link to the laptop.
 * Reconnects with exponential backoff, heartbeats every 20s,
 * and routes commands to CommandExecutor.
 */
class ConnectionService : Service() {

    companion object {
        const val CHANNEL_ID = "agentcore_link"
        const val NOTIF_ID = 1
        const val ACTION_PAIR = "com.agentcore.companion.PAIR"
        const val ACTION_STOP = "com.agentcore.companion.STOP"
        const val EXTRA_PAIR_CODE = "pair_code"

        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, ConnectionService::class.java))
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var ws: WebSocket? = null
    private var reconnectAttempt = 0
    private var heartbeatSeq = 0
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)
        .build()
    private var executor: CommandExecutor? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(NOTIF_ID, NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("AgentCore")
            .setContentText("Connected to laptop")
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setOngoing(true)
            .build())
        executor = CommandExecutor(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PAIR -> {
                val code = intent.getStringExtra(EXTRA_PAIR_CODE) ?: ""
                scope.launch { connect(pairCode = code) }
            }
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }
            else -> {
                // already paired → reconnect with stored token
                if (SecureStore.token(this).isNotEmpty()) scope.launch { connect() }
            }
        }
        return START_STICKY
    }

    private suspend fun connect(pairCode: String? = null) {
        val url = SecureStore.url(this).ifEmpty { return }
        val token = SecureStore.token(this)
        val name = SecureStore.name(this)

        val request = Request.Builder().url(url).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(w: WebSocket, response: Response) {
                reconnectAttempt = 0
                val hello = if (token.isNotEmpty()) Protocol.helloWithToken(name, token)
                            else Protocol.hello(name, pairCode ?: "")
                w.send(Protocol.encode(hello))
            }

            override fun onMessage(w: WebSocket, text: String) {
                val env = Protocol.decode(text)
                when (env.type) {
                    "paired" -> {
                        val newToken = env.data?.let {
                            // data: {"token": "..."} — parse the token field
                            val s = it.toString()
                            Regex("\"token\":\"([^\"]+)\"").find(s)?.groupValues?.get(1) ?: token
                        } ?: token
                        SecureStore.save(applicationContext, newToken, url, name)
                        heartbeatSeq = 0
                    }
                    "pair_error" -> {
                        // wrong code — surface to the UI via a broadcast
                        sendBroadcast(Intent("com.agentcore.companion.PAIR_ERROR"))
                    }
                    "command" -> {
                        scope.launch {
                            executor?.execute(env)
                        }
                    }
                    "heartbeat" -> { /* keep-alive; nothing to do */ }
                }
            }

            override fun onFailure(w: WebSocket, t: Throwable, response: Response?) {
                scheduleReconnect()
            }

            override fun onClosed(w: WebSocket, code: Int, reason: String) {
                scheduleReconnect()
            }
        })

        // periodic heartbeat
        while (isActive && ws != null) {
            delay(20_000)
            try {
                ws?.send(Protocol.encode(Protocol.heartbeat(heartbeatSeq++, token)))
            } catch (_: Exception) { }
        }
    }

    private fun scheduleReconnect() {
        val backoff = listOf(1L, 2L, 4L, 8L, 16L).getOrElse(reconnectAttempt) { 30L }
        reconnectAttempt++
        scope.launch {
            delay(backoff * 1000)
            if (SecureStore.token(this@ConnectionService).isNotEmpty()) connect()
        }
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL_ID, "AgentCore link",
                NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null
    override fun onDestroy() {
        scope.cancel()
        ws?.close(1000, "service stopped")
        super.onDestroy()
    }
}
