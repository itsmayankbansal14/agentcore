package com.agentcore.companion.executors

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.HandlerThread
import android.os.Environment
import android.util.DisplayMetrics
import android.view.WindowManager
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer

/**
 * Screen capture via MediaProjection (Phase 6).
 *
 * Android REQUIRES an explicit per-session user grant: the user taps
 * "Start recording/casting?" in the system dialog before each capture
 * session. The app requests it lazily when the laptop first asks for a
 * screenshot, then keeps the projection for a short idle window.
 *
 * Laptop command: device.android.screenshot
 */
object ScreenshotExecutor {
    @Volatile private var projection: MediaProjection? = null
    @Volatile private var resultCode: Int = -1
    @Volatile private var resultData: Intent? = null

    /** The UI activity calls this with the MediaProjection permission result. */
    fun onProjectionResult(code: Int, data: Intent) {
        resultCode = code; resultData = data
    }

    fun capture(ctx: Context): Pair<Boolean, Any> {
        val mpm = ctx.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        if (resultCode == -1 || resultData == null) {
            // no grant yet — we can't launch the dialog from a service; signal the app
            return false to mapOf("error" to "screen capture requires the in-app permission grant",
                                  "grant" to true)
        }
        try {
            val proj = projection ?: mpm.getMediaProjection(resultCode, resultData!!).also { projection = it }
            val metrics = ctx.resources.displayMetrics
            val density = metrics.densityDpi
            val width = metrics.widthPixels
            val height = metrics.heightPixels

            val handlerThread = HandlerThread("shot").apply { start() }
            val handler = Handler(handlerThread.looper)
            val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)

            val display: VirtualDisplay = proj.createVirtualDisplay(
                "agentcore-shot", width, height, density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.surface, null, handler)

            // wait for one frame
            var bitmap: Bitmap? = null
            val latch = java.util.concurrent.CountDownLatch(1)
            reader.setOnImageAvailableListener({ r ->
                val image: Image? = r.acquireLatestImage()
                if (image != null) {
                    bitmap = imageToBitmap(image, width, height)
                    image.close()
                    latch.countDown()
                }
            }, handler)

            latch.await(3, java.util.concurrent.TimeUnit.SECONDS)
            display.release()
            handlerThread.quitSafely()

            if (bitmap == null) return false to mapOf("error" to "no frame captured")
            val dir = File(ctx.getExternalFilesDir(null), "screenshots").apply { mkdirs() }
            val file = File(dir, "shot_${System.currentTimeMillis()}.png")
            FileOutputStream(file).use { bitmap!!.compress(Bitmap.CompressFormat.PNG, 90, it) }
            return true to mapOf("file" to file.absolutePath, "mime" to "image/png",
                                 "size" to file.length())
        } catch (e: Exception) {
            return false to mapOf("error" to e.message)
        }
    }

    private fun imageToBitmap(image: Image, width: Int, height: Int): Bitmap {
        val plane = image.planes[0]
        val buffer: ByteBuffer = plane.buffer
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val rowPadding = rowStride - pixelStride * width
        val bitmap = Bitmap.createBitmap(width + rowPadding / pixelStride, height,
                                         Bitmap.Config.ARGB_8888)
        bitmap.copyPixelsFromBuffer(buffer)
        return Bitmap.createBitmap(bitmap, 0, 0, width, height)
    }
}
