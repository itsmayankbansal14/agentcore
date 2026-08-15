package com.agentcore.companion.executors

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Accessibility UI-control service (Phase 6 — v2).
 *
 * ENABLED ONLY IF THE USER OPTED IN (Settings → Accessibility → AgentCore UI control).
 * Privacy posture: the service never reads passwords / sensitive fields; it only
 * performs gestures (tap/swipe) and types into the currently focused field when
 * the laptop asks. No screen content is streamed by default.
 *
 * The laptop drives it via:  device.android.ui_tap / ui_swipe / ui_text
 */
class UIActionsService : AccessibilityService() {

    companion object {
        @Volatile var instance: UIActionsService? = null
    }

    override fun onServiceConnected() {
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) { /* listeners only */ }
    override fun onInterrupt() {}

    fun tap(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 80))
            .build()
        return dispatchGesture(gesture, null, null)
    }

    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, ms: Long = 300): Boolean {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, ms))
            .build()
        return dispatchGesture(gesture, null, null)
    }

    fun type(text: String): Boolean {
        return try {
            val node: AccessibilityNodeInfo? = rootInActiveWindow
            if (node == null) return false
            // find the focused or first editable node
            val target = if (node.isFocused) node
                         else node.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: node
            target.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,
                                 android.os.Bundle().apply { putCharSequence(
                                     AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) })
            true
        } catch (_: Exception) { false }
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }
}
