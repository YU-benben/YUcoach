package cn.yucoach.yu_coach

import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.net.Uri
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * 视频元数据读取。
 *
 * 为什么必须写原生代码：
 *   Flutter 侧拿不到视频的帧率与帧数。而这两个值是整个分析链路的基础 ——
 *   帧率错一倍，触地时间、腾空时间、步频全部静默出错，而且不会报错。
 *   见 docs/02-数据标准.md §8（帧率可信度协议）。
 *
 * 两个原生 API 各有短板，必须配合使用：
 *
 *   MediaMetadataRetriever
 *     ✔ 支持 content:// URI（相册选来的文件就是这种 URI，无需存储权限）
 *     ✘ **不提供帧率**
 *
 *   MediaExtractor
 *     ✔ 提供 MediaFormat.KEY_FRAME_RATE / KEY_FRAME_COUNT
 *     ✘ setDataSource 只接受文件路径或 FileDescriptor
 *
 * 因此：用 ContentResolver 打开文件描述符喂给 MediaExtractor 拿帧率，
 * 用 MediaMetadataRetriever 拿时长与分辨率。
 */
class MainActivity : FlutterActivity() {

    private val channelName = "cn.yucoach/video_probe"

    /**
     * 取帧器。
     *
     * 做成字段而不是每次调用新建：它内部持有一个 HandlerThread，
     * 新建一次就多一个线程。作为字段则整个 Activity 生命周期只有一个，
     * 在 onDestroy 里释放。
     */
    private val frameDecoder = FrameDecoder()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        // 取帧需要 Context 才能打开 content:// URI。
        // 用 applicationContext 而不是 this —— Activity 被回收后
        // 持有它就是内存泄漏。
        FrameDecoderContext.appContext = applicationContext

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            channelName
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "probe" -> {
                    val uriString = call.argument<String>("uri")
                    if (uriString.isNullOrBlank()) {
                        result.error("bad_args", "缺少 uri 参数", null)
                        return@setMethodCallHandler
                    }
                    try {
                        result.success(probe(uriString))
                    } catch (e: Exception) {
                        // 读取失败是常见情况（文件损坏、编码不支持、权限被收回），
                        // 返回结构化错误让上层给出可操作提示，而不是崩溃。
                        result.error("probe_failed", e.message ?: e.toString(), null)
                    }
                }
                "decodeFrames" -> {
                    // 取帧是异步的：通过 EventChannel 逐帧推送。
                    // 这里只负责启动，**立刻返回** ——
                    // 如果在这里等取帧完成，界面会直接 ANR。
                    @Suppress("UNCHECKED_CAST")
                    val args = call.arguments as? Map<String, Any?>
                    if (args == null) {
                        result.error("bad_args", "缺少参数", null)
                    } else {
                        frameDecoder.decode(args)
                        result.success(null)
                    }
                }
                "cancelDecode" -> {
                    // 用户中途退出时必须能停下来 ——
                    // 否则解码线程会继续跑完剩下的帧，白耗电。
                    frameDecoder.cancel()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }

        // 逐帧推送给 Dart 侧。
        // 用 EventChannel 而不是让 MethodChannel 返回一个大数组的原因
        // 见 FrameDecoder 顶部的说明（内存与进度）。
        frameDecoder.attach(flutterEngine.dartExecutor.binaryMessenger)
    }

    override fun onDestroy() {
        // 页面退出时必须停掉解码线程，否则它会继续跑、白耗电。
        frameDecoder.release()
        super.onDestroy()
    }

    private fun probe(uriString: String): Map<String, Any?> {
        val uri = Uri.parse(uriString)
        val out = HashMap<String, Any?>()

        // ---- 时长、分辨率、旋转（MediaMetadataRetriever 支持 content://）----
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(this, uri)

            out["duration_ms"] = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull()

            // 注意：这两个值是**存储方向**下的尺寸。
            // 竖屏视频通常 width < height 且 rotation = 90，
            // 播放时看到的是旋转后的画面，交付时要换算。
            out["width"] = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                ?.toIntOrNull()
            out["height"] = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                ?.toIntOrNull()
            out["rotation"] = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)
                ?.toIntOrNull() ?: 0

            out["bitrate"] = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_BITRATE)
                ?.toIntOrNull()

            out["mime_type"] = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_MIMETYPE)

            out["has_video"] = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO) == "yes"
        } finally {
            try {
                retriever.release()
            } catch (_: Exception) {
                // release 失败无所谓，不能因此让整个调用失败
            }
        }

        // ---- 帧率与帧数（MediaExtractor，需要 FileDescriptor）----
        //
        // 这两个 key 在很多文件里**不存在**。缺失时如实返回 null，
        // 由上层标记为「帧率未知」并交给服务端判定 ——
        // 绝不猜测，也绝不退回容器声称的值当真实值用。
        //
        // 帧数**必须自己数**：MediaFormat 里没有公开的帧数常量
        // （只有 KEY_FRAME_RATE，没有 KEY_FRAME_COUNT —— 后者是隐藏的私有 key，
        // 引用它会编译不过）。所以遍历采样点逐个数。
        // 只推进不读数据，速度很快；并设上限防止异常文件卡死。
        val extractor = MediaExtractor()
        try {
            contentResolver.openFileDescriptor(uri, "r")?.use { pfd ->
                extractor.setDataSource(pfd.fileDescriptor)

                var videoTrack = -1
                for (i in 0 until extractor.trackCount) {
                    val mime = extractor.getTrackFormat(i)
                        .getString(MediaFormat.KEY_MIME) ?: continue
                    if (!mime.startsWith("video/")) continue
                    videoTrack = i
                    break
                }

                if (videoTrack >= 0) {
                    val format = extractor.getTrackFormat(videoTrack)

                    if (format.containsKey(MediaFormat.KEY_FRAME_RATE)) {
                        // 可能是 Integer 也可能是 Float，两种都要处理
                        out["frame_rate"] = try {
                            format.getInteger(MediaFormat.KEY_FRAME_RATE).toDouble()
                        } catch (_: Exception) {
                            format.getFloat(MediaFormat.KEY_FRAME_RATE).toDouble()
                        }
                    }

                    extractor.selectTrack(videoTrack)
                    out["frame_count"] = countFrames(extractor)
                }
            }
        } catch (_: Exception) {
            // 帧率/帧数读取失败不影响已经拿到的时长与分辨率 ——
            // 部分信息比没有信息有用。上层会把缺失当作「未知」处理。
        } finally {
            try {
                extractor.release()
            } catch (_: Exception) {
            }
        }

        return out
    }

    /**
     * 遍历视频轨，数出总帧数。
     *
     * 为什么不用 MediaFormat 的帧数常量：公开 API 里没有。
     *
     * 用 sampleTime 而不是 sampleFlags 判断：sampleFlags 在不同编码器上
     * 语义不一致，而每个采样点都有时间戳，更可靠。
     *
     * 上限 [MAX_FRAMES] 是保护措施：损坏的文件可能让 advance() 一直返回 true，
     * 不设上限会卡住。超过上限时返回 null（表示「数不清」），
     * 而不是返回一个错误的数字 —— 宁可说不知道，也不能给错数据。
     */
    private fun countFrames(extractor: MediaExtractor): Long? {
        var count = 0L
        var lastTime = -1L

        while (count < MAX_FRAMES) {
            val time = extractor.sampleTime
            if (time < 0) break

            // 同一时间戳可能出现多次（多 slice 编码），只计一次
            if (time != lastTime) {
                count++
                lastTime = time
            }

            if (!extractor.advance()) break
        }

        return if (count >= MAX_FRAMES) null else count
    }

    companion object {
        /**
         * 帧数上限。
         *
         * 60 秒 × 240 fps = 14400 帧，取 100000 留足余量
         * （覆盖 4 分钟的高帧率素材）。超过这个量级必然是文件异常，
         * 不是真实素材。
         */
        private const val MAX_FRAMES = 100000L
    }
}
