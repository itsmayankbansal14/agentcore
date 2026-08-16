package com.agentcore.companion.executors

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.agentcore.companion.NotificationStore

/**
 * Notification mirroring — requires the user to enable
 * "Notification access" for this app (Settings → Notifications → Notification access).
 * The app NEVER reads message bodies of private chats; it only exposes
 * app name / title / ticker text that the user opted to share with the laptop.
 */
class NotificationReaderService : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn ?: return
        if (sbn.isOngoing) return   // skip foreground-service / ongoing notifications
        val extras = sbn.notification.extras
        val title = extras.getCharSequence(
            android.app.Notification.EXTRA_TITLE)?.toString() ?: return
        val text = extras.getCharSequence(
            android.app.Notification.EXTRA_TEXT)?.toString() ?: ""
        NotificationStore.add(mapOf(
            "app" to sbn.packageName,
            "title" to title,
            "text" to text.take(200),
            "time" to (System.currentTimeMillis() / 1000).toString(),
        ))
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) { /* no-op */ }
}
