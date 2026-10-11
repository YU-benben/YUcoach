/// 视频取帧（Dart 侧）。
///
/// ## 为什么不一次取完
///
/// 一次分析可能要取上千帧。如果原生侧攒齐再返回：
///   · 内存要几十到几百 MB → OOM
///   · 用户看不到任何进度
///
/// 所以走 **EventChannel 流式推送**：原生侧解一帧、推一帧，
/// Dart 侧收一帧、推理一帧。内存占用恒定，进度天然可报。
///
/// ## 与电脑端的差别（必须知情）
///
/// 电脑端用 OpenCV 逐帧顺序解码，**精确到帧**。
/// 手机端用 `MediaMetadataRetriever.getFrameAtTime`，取的是
/// **最接近的关键帧**，可能不是请求的那个精确时刻。
///
/// 后果：时序类指标（触地时间）在手机上**不可靠**。
/// 所以手机端只做姿态提取与关键帧展示，
/// 指标计算仍以电脑端为准（那里有精确的逐帧解码）。
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

/// 一帧。
class DecodedFrame {
  const DecodedFrame({
    required this.index,
    required this.jpeg,
    required this.width,
    required this.height,
  });

  /// 第几帧（从 0 开始，按**取样序列**计数，不是视频的绝对帧号）。
  final int index;

  /// JPEG 编码的帧数据。
  ///
  /// ## 为什么传 JPEG 而不是原始像素
  ///
  /// 原生侧缩到 640 长边后，原始 RGBA 是 1.6 MB/帧。
  /// JPEG 质量 90 大约 60~120 KB，**小了十几倍**，
  /// 而且跨通道传输的开销主要在这里。
  ///
  /// 代价是多一次解码。但 Dart 侧本来也要把像素喂给模型 ——
  /// Flutter 的 `instantiateImageCodec` 解 JPEG 很快（几十毫秒）。
  ///
  /// 为 null 表示这一帧取不到（文件尾、损坏）。
  /// **上层必须处理 null**，而不是假设每帧都有数据。
  final Uint8List? jpeg;

  final int width;
  final int height;

  bool get isValid => jpeg != null && jpeg!.isNotEmpty;

  @override
  String toString() =>
      'DecodedFrame(#$index, ${isValid ? "${jpeg!.length ~/ 1024} KB" : "无效"}, '
      '${width}x$height)';
}

/// 取帧进度。
class DecodeProgress {
  const DecodeProgress({required this.done, required this.total});

  final int done;
  final int total;

  double get fraction => total <= 0 ? 0 : (done / total).clamp(0.0, 1.0);
}

/// 取帧失败。
class FrameDecodeException implements Exception {
  const FrameDecodeException(this.code, this.message);

  final String code;
  final String message;

  /// 给用户看的话。
  String get userMessage => switch (code) {
        'bad_args' => '视频信息不完整，请重新选择文件。',
        'decode_failed' => '视频解码失败。\n\n'
            '常见原因：文件损坏、编码格式不支持（如某些 HEVC 变体），'
            '或视频被其他应用占用。',
        _ => '取帧失败：$message',
      };

  @override
  String toString() => 'FrameDecodeException($code: $message)';
}

/// 取帧器。
class FrameDecoder {
  const FrameDecoder();

  static const _method = MethodChannel('cn.yucoach/video_probe');
  static const _events = EventChannel('cn.yucoach/video_frames');

  /// 是否支持当前平台。
  ///
  /// 桌面端（开发时在 Windows 上跑）没有这套原生 API。
  static bool get isSupported => Platform.isAndroid;

  /// 取帧。返回一个流，依次产出进度与帧。
  ///
  /// 参数
  /// ----
  /// uri : 视频地址（content:// 或 file://）
  /// count : 要取多少帧
  /// startMs : 起始时刻
  /// fps : 目标采样帧率
  ///
  /// ## 为什么 count 和 fps 都要传
  ///
  /// 有 count 就够算间隔了，但**显式传 fps 让意图清楚**：
  /// 调用方想的是"按 10 fps 采样"，而不是"取 120 帧"。
  /// 而且帧间隔本身是 chain 上的一个独立概念 ——
  /// 将来做"每步取一帧"时，间隔会由事件决定而不是固定值。
  Stream<dynamic> decode({
    required String uri,
    required int count,
    int startMs = 0,
    double fps = 10,
  }) {
    if (!isSupported) {
      return Stream.error(const FrameDecodeException(
        'unsupported_platform',
        '取帧目前只支持 Android',
      ));
    }

    final intervalMs = fps <= 0 ? 33 : (1000 / fps).round();

    final controller = StreamController<dynamic>();

    // 先订阅再启动 —— 顺序反了会丢掉最早几帧的消息。
    StreamSubscription<dynamic>? sub;

    sub = _events.receiveBroadcastStream().listen(
      (event) {
        if (controller.isClosed) return;
        final map = (event as Map).cast<String, dynamic>();
        final type = map['type'] as String?;

        switch (type) {
          case 'progress':
            controller.add(DecodeProgress(
              done: (map['done'] as num?)?.toInt() ?? 0,
              total: (map['total'] as num?)?.toInt() ?? 0,
            ));
            break;

          case 'frame':
            final bytes = map['bytes'];
            controller.add(DecodedFrame(
              index: (map['index'] as num?)?.toInt() ?? 0,
              jpeg: bytes is Uint8List
                  ? bytes
                  : (bytes is List<int> ? Uint8List.fromList(bytes) : null),
              width: (map['width'] as num?)?.toInt() ?? 0,
              height: (map['height'] as num?)?.toInt() ?? 0,
            ));
            break;

          case 'done':
            controller.close();
            sub?.cancel();
            break;

          case 'error':
            controller.addError(FrameDecodeException(
              map['code'] as String? ?? 'unknown',
              map['message'] as String? ?? '未知错误',
            ));
            controller.close();
            sub?.cancel();
            break;
        }
      },
      onError: (Object e) {
        if (controller.isClosed) return;
        controller.addError(FrameDecodeException('channel_error', '$e'));
        controller.close();
      },
      onDone: () {
        if (!controller.isClosed) controller.close();
      },
    );

    // 启动取帧。原生侧立刻返回，真正的活在线程里干。
    _method.invokeMethod<void>('decodeFrames', {
      'uri': uri,
      'start_ms': startMs,
      'count': count,
      'interval_ms': intervalMs,
    }).catchError((Object e) {
      if (!controller.isClosed) {
        controller.addError(FrameDecodeException('start_failed', '$e'));
        controller.close();
      }
    });

    // 调用方取消订阅时，通知原生侧停下来。
    controller.onCancel = () async {
      await sub?.cancel();
      await _method.invokeMethod<void>('cancelDecode').catchError((_) {});
    };

    return controller.stream;
  }
}
