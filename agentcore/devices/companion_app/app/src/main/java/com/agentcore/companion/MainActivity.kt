package com.agentcore.companion

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat

/**
 * Minimal companion UI: connection status, laptop URL + pairing code entry,
 * permission status (notification access / usage access), and a start button.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { App(this) }
    }
}

@Composable
fun App(ctx: android.content.Context) {
    var url by remember { mutableStateOf(SecureStore.url(ctx)) }
    var pairCode by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("Not connected") }
    val notifAccess = ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS)

    MaterialTheme {
        Column(Modifier.padding(20.dp).fillMaxSize(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("AgentCore Companion", style = MaterialTheme.typography.headlineSmall)
            Text(status, color = MaterialTheme.colorScheme.primary)

            OutlinedTextField(value = url, onValueChange = { url = it },
                label = { Text("Laptop URL (wss://…)") }, modifier = Modifier.fillMaxWidth())

            OutlinedTextField(value = pairCode, onValueChange = { pairCode = it },
                label = { Text("6-digit pairing code") }, modifier = Modifier.fillMaxWidth())

            Button(onClick = {
                SecureStore.save(ctx, "", url.trim(), "My Phone")
                val intent = Intent(ctx, ConnectionService::class.java)
                    .setAction(ConnectionService.ACTION_PAIR)
                    .putExtra(ConnectionService.EXTRA_PAIR_CODE, pairCode.trim())
                ContextCompat.startForegroundService(ctx, intent)
                status = "Pairing…"
            }, modifier = Modifier.fillMaxWidth()) {
                Text(if (SecureStore.token(ctx).isEmpty()) "Connect & Pair" else "Reconnect")
            }

            if (SecureStore.token(ctx).isNotEmpty()) {
                Button(onClick = {
                    ContextCompat.startForegroundService(ctx,
                        Intent(ctx, ConnectionService::class.java))
                    status = "Connected to $url"
                }, modifier = Modifier.fillMaxWidth()) {
                    Text("Start service (reconnect)")
                }
            }

            Divider()
            Text("Permissions", style = MaterialTheme.typography.titleSmall)

            PermissionRow("Notification access", "Mirror notifications to laptop") {
                ctx.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            }
            PermissionRow("Usage access", "See foreground app (optional)") {
                ctx.startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
            }
            PermissionRow("Screen capture", "Screenshots (granted per-session)") {
                // MediaProjection is requested from the app; this just opens the settings hint
                ctx.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:${ctx.packageName}")))
            }

            Spacer(Modifier.weight(1f))
            TextButton(onClick = {
                SecureStore.clear(ctx)
                status = "Cleared — re-pair from scratch"
            }) { Text("Forget this laptop & clear pairing") }
        }
    }
}

@Composable
fun PermissionRow(title: String, desc: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(desc, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        TextButton(onClick = onClick) { Text("Open") }
    }
}
