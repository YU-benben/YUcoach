package cn.yucoach.yu_coach

import android.graphics.Bitmap
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import io.flutter.plugin.common.EventChannel
import java.io.ByteArrayOutputStream

/**
 * 视频取帧。
 *
 * ## 为什么用 EventChannel 而不是 MethodChannel
 *
 * 一次分析可能要取上千帧。如果用一个 MethodChannel 调用返回"所有帧的数组"：
 *
 *   · 原生侧要先在内存里攒齐上千帧的位图 → **几十 MB 到几百 MB**，直接 OOM
 *   · 跨通道一次性传输这么大的数据 → 卡顿几秒甚至超时
 *   · 没有进度可言 —— 用户只能干等，不知道是在跑还是卡死了
 *
 * 用 EventChannel 逐帧推给 Dart 侧：
 *
 *   · 内存占用是**恒定**的（一帧在途）
 *   · 每帧推完可以顺手报进度
 *   · Dart 侧是流式处理，收到一帧就推理一帧
 *
 * ## 为什么在后台线程
 *
 * `MediaMetadataRetriever.getFrameAtTime` 是**同步阻塞**的，
 * 解一帧要几十到几百毫秒。在主线程上跑会直接 ANR（应用无响应）。
 * 所以整个取帧循环放在一个 HandlerThread 上。
 *
 * ## ⚠️ 已知的精度取舍
 *
 * 这里用 `getFrameAtTime` 按**时间**取帧，而不是按帧号顺序解码。
 * 原因是按顺序解码需要 MediaCodec，代码量大好几倍，且要处理各种编码器差异。
 *
 * 代价：`getFrameAtTime` 返回的是**最接近的关键帧**，可能不是请求的那个
 * 精确时刻。对上采样后的帧率（比如每 4 帧取 1 帧）来说，
 * 这个偏差会让时序类指标（触地时间）不准。
 *
 * 所以：**本实现用于姿态提取与关键帧展示，时序类指标仍以电脑端为准。**
 * 要精确到帧，需要改用 MediaCodec 顺序解码 —— 那是下一步的事。
 */
class FrameDecoder {

    companion object {
        const val CHANNEL = "cn.yucoach/video_frames"

        /** 单帧最大边长。超过就等比缩小。 */
        private const val MAX_DIM = 640

        /** 进度回调的最小间隔（帧），避免每帧都发消息。 */
        private const val PROGRESS_EVERY = 5
    }

    private val thread = HandlerThread("yucoach-frames").apply { start() }
    private val handler = Handler(thread.looper)
    private val main = Handler(Looper.getMainLooper())

    private var sink: EventChannel.EventSink? = null
    private var cancelled = false

    fun attach(messenger: io.flutter.plugin.common.BinaryMessenger) {
        EventChannel(messenger, CHANNEL).setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(args: Any?, events: EventChannel.EventSink?) {
                    sink = events
                }

                override fun onCancel(args: Any?) {
                    // 用户退出页面时取消。必须真的停下来 ——
                    // 否则解码线程会继续跑，白耗电和白占 CPU。
                    cancelled = true
                    sink = null
                }
            }
        )
    }

    fun release() {
        cancelled = true
        sink = null
        thread.quitSafely()
    }

    /**
     * 让正在跑的取帧循环停下来。
     *
     * ## 为什么不能只置 cancelled 就完事
     *
     * 取帧循环每次迭代都会检查 [cancelled]，所以置位之后最多再解一帧。
     * 但**必须同时把 sink 置空** —— 否则循环里已经排进主线程队列的
     * 那条消息还会被发出去，而 Dart 侧可能已经关了流。
     *
     * ## 为什么单独一个方法而不是复用 onCancel
     *
     * EventChannel 的 onCancel 只在**流被取消**时触发。
     * 而用户点「取消」按钮时流可能还开着（只是不想继续了）。
     * 两个入口分开更清楚。
     */
    fun cancel() {
        cancelled = true
        sink = null
    }

    /**
     * 开始取帧。
     *
     * 参数（来自 Dart）：
     *   uri          视频地址
     *   startMs      起始时刻
     *   count        要取多少帧
     *   intervalMs   帧间隔（1000 / 目标帧率）
     */
    fun decode(args: Map<String, Any?>) {
        val uriString = args["uri"] as? String
        val startMs = (args["start_ms"] as? Number)?.toLong() ?: 0L
        val count = (args["count"] as? Number)?.toInt() ?: 0
        val intervalMs = (args["interval_ms"] as? Number)?.toLong() ?: 33L

        if (uriString.isNullOrBlank() || count <= 0) {
            sendError("bad_args", "缺少 uri 或 count 无效", null)
            return
        }

        cancelled = false

        handler.post {
            val retriever = MediaMetadataRetriever()
            try {
                retriever.setDataSource(
                    FrameDecoderContext.appContext, Uri.parse(uriString)
                )

                val out = ByteArrayOutputStream()
                var sent = 0
                var scaledW = 0
                var scaledH = 0

                for (i in 0 until count) {
                    if (cancelled) return@post

                    val timeUs = (startMs + i * intervalMs) * 1000

                    // OPTION_CLOSEST_SYNC：取最接近的关键帧。
                    //
                    // 为什么不用 OPTION_CLOSEST：那会解码到精确时间点，
                    // 但要解更多帧，手机上慢好几倍。对姿态提取来说，
                    // 关键帧的清晰度更重要，时间上几十毫秒的偏差可接受。
                    val bitmap = try {
                        retriever.getFrameAtTime(
                            timeUs, MediaMetadataRetriever.OPTION_CLOSEST_SYNC
                        )
                    } catch (_: Exception) {
                        null
                    }

                    if (bitmap == null) {
                        // 取不到这一帧（文件尾、损坏）。
                        // **如实上报**而不是跳过 —— 跳过会让 Dart 侧的
                        // 帧号与真实时间对不上，而那种错很难查。
                        sendFrame(i, null, 0, 0)
                        continue
                    }

                    val scaled = scaleDown(bitmap)
                    if (scaled !== bitmap) bitmap.recycle()

                    if (scaledW == 0) {
                        scaledW = scaled.width
                        scaledH = scaled.height
                    }

                    out.reset()
                    scaled.compress(Bitmap.CompressFormat.JPEG, 90, out)
                    val bytes = out.toByteArray()
                    // 压缩完就可以回收了 —— 内存里同时只有一帧
                    scaled.recycle()

                    sendFrame(i, bytes, scaledW, scaledH)
                    sent++

                    if (i % PROGRESS_EVERY == 0) {
                        sendProgress(i + 1, count)
                    }
                }

                sendDone(sent, scaledW, scaledH)

            } catch (e: Exception) {
                sendError("decode_failed", e.message ?: e.toString(), null)
            } finally {
                try {
                    retriever.release()
                } catch (_: Exception) {
                }
            }
        }
    }

    /**
     * 等比缩小到位图长边不超过 [MAX_DIM]。
     *
     * 为什么在原生侧缩：原始帧可能是 4K（3840×2160），
     * RGBA 展开是 33 MB。传到 Dart 再缩的话，光传输和分配就够呛。
     * 在这一侧缩到 640 长边，只有 1.6 MB。
     */
    private fun scaleDown(src: Bitmap): Bitmap {
        val longSide = maxOf(src.width, src.height)
        if (longSide <= MAX_DIM) return src

        val ratio = MAX_DIM.toFloat() / longSide
        val w = (src.width * ratio).toInt().coerceAtLeast(1)
        val h = (src.height * ratio).toInt().coerceAtLeast(1)
        return Bitmap.createScaledBitmap(src, w, h, true)
    }

    // ---- 向 Dart 侧发送 ----

    private fun sendFrame(
        index: Int, jpeg: ByteArray?, width: Int, height: Int
    ) {
        val payload = HashMap<String, Any?>()
        payload["type"] = "frame"
        payload["index"] = index
        payload["bytes"] = jpeg
        payload["width"] = width
        payload["height"] = height
        post(payload)
    }

    private fun sendProgress(done: Int, total: Int) {
        val payload = HashMap<String, Any?>()
        payload["type"] = "progress"
        payload["done"] = done
        payload["total"] = total
        post(payload)
    }

    private fun sendDone(sent: Int, width: Int, height: Int) {
        val payload = HashMap<String, Any?>()
        payload["type"] = "done"
        payload["sent"] = sent
        payload["width"] = width
        payload["height"] = height
        post(payload)
    }

    private fun sendError(code: String, message: String, detail: Any?) {
        val payload = HashMap<String, Any?>()
        payload["type"] = "error"
        payload["code"] = code
        payload["message"] = message
        payload["detail"] = detail
        post(payload)
    }

    /** EventChannel 必须在主线程上发消息。 */
    private fun post(payload: Map<String, Any?>) {
        main.post {
            val s = sink ?: return@post
            if (cancelled) return@post
            try {
                s.success(payload)
            } catch (_: Exception) {
                // 通道已经关了（用户退出了页面）。忽略。
            }
        }
    }
}

/**
 * 存一个全局 Context。
 *
 * 为什么需要：MediaMetadataRetriever.setDataSource(Context, Uri) 需要
 * Context，而 FrameDecoder 是普通对象、拿不到 Activity。
 *
 * 用 applicationContext 而不是 Activity —— 后者被回收后就是内存泄漏。
 */
object FrameDecoderContext {
    lateinit var appContext: android.content.Context
}
