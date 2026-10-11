/// 手机端姿态提取管线。
///
/// ## 完整链路
///
/// ```
/// 视频 URI
///   ↓  ① 原生取帧（MediaMetadataRetriever，缩到 640 长边，JPEG）
/// JPEG 帧流
///   ↓  ② 解码 JPEG + letterbox 到 640×640 RGBA
/// 方形像素缓冲
///   ↓  ③ ONNX 推理（yolov8n-pose）
/// (1, 56, 8400) 张量
///   ↓  ④ 后处理（置信度筛选 + 坐标反映射 + 选人）
/// 每帧 17 个关键点
///   ↓  ⑤ 足部点推导
/// 骨架序列
///   ↓  ⑥ 事件检测 + 相位划分
/// 关键帧 + 相位
/// ```
///
/// 每一步都记了「为什么这么做」和「什么情况下会出错」。
///
/// ## ⚠️ 手机端与电脑端的分工
///
/// | 工作 | 手机 | 电脑 |
/// |---|---|---|
/// | 取帧 | ✅ | ✅（更精确，逐帧顺序解码） |
/// | 姿态提取 | ✅ | ✅ |
/// | 事件检测 | ✅（简化版） | ✅ |
/// | **20 个指标** | ❌ | ✅ |
/// | **标准值比较** | ❌ | ✅ |
///
/// 为什么不把指标也搬过来：那会**引入第二套实现**，
/// 两套实现会慢慢漂移，而教练会拿两个版本的报告对比。
/// 而骨架数据只有 200 KB 左右，传过去是瞬间的事。
library;

import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'pose_types.dart';
import 'yolo_postprocess.dart';
import 'pose_inference.dart';
import 'frame_decoder.dart';
import 'foot_derivation.dart';
import 'gait_events.dart';
import 'keyframe_selection.dart';

/// 提取进度。
class ExtractionProgress {
  const ExtractionProgress({
    required this.phase,
    required this.fraction,
    this.detail = '',
  });

  /// 阶段名。给用户看。
  final String phase;

  /// 0~1。
  final double fraction;

  final String detail;
}

/// 提取结果。
class PoseExtractionResult {
  const PoseExtractionResult({
    required this.sequence,
    required this.derivedFrames,
    required this.events,
    required this.phases,
    required this.keyframes,
    required this.elapsedMs,
    required this.framesDecoded,
    required this.framesWithPose,
    required this.personHeights,
    this.ambiguousFrames = 0,
    this.notes = const [],
  });

  /// 姿态序列（只有关键点）。
  final PoseSequence sequence;

  /// 带推导足部点的帧。
  final List<DerivedFrame> derivedFrames;

  final GaitEvents events;
  final List<PhaseSegment> phases;
  final List<KeyframeSelection> keyframes;

  /// 总耗时（毫秒）。
  final int elapsedMs;

  /// 成功解码的帧数。
  final int framesDecoded;

  /// 其中检出人的帧数。
  final int framesWithPose;

  /// 每帧的人物高度占画面比例。用于拍摄质量检查。
  final Map<int, double> personHeights;

  /// 选人有歧义的帧数。
  final int ambiguousFrames;

  /// 过程中的提示。例如"这一帧取不到"。
  final List<String> notes;

  /// 平均每帧耗时（毫秒）。**这是最有价值的性能数字** ——
  /// 决定将来能不能做实时、要不要降分辨率。
  double get msPerFrame =>
      framesDecoded == 0 ? 0 : elapsedMs / framesDecoded;
}

/// 姿态提取配置。
class PoseExtractionConfig {
  const PoseExtractionConfig({
    this.fps = 10,
    this.maxFrames = 300,
    this.startMs = 0,
    this.confThreshold = 0.25,
  });

  /// 采样帧率。
  ///
  /// ## 为什么默认 10 fps 而不是 120
  ///
  /// 1200 帧在手机上要跑一分多钟，而**现有素材本来就只有 30 fps** ——
  /// 取 120 fps 只是把同一帧重复取好几遍，没有任何信息增益。
  ///
  /// 10 fps 对姿态提取足够了（姿态变化没那么快），
  /// 而且 300 帧大约 20~40 秒能跑完。
  ///
  /// 将来有了真正的 120 fps 素材，再把这个值提上去。
  final double fps;

  /// 最多取多少帧。防止用户选了一个 10 分钟的视频把手机跑死。
  final int maxFrames;

  final int startMs;

  final double confThreshold;
}

/// 姿态提取器。
class PoseExtractor {
  PoseExtractor({PoseOnnxModel? model})
      : _injectedModel = model;

  final PoseOnnxModel? _injectedModel;
  PoseOnnxModel? _ownModel;

  PoseOnnxModel get _model => _injectedModel ?? (_ownModel ??= PoseOnnxModel());

  bool _cancelled = false;

  void cancel() => _cancelled = true;

  /// 跑完整管线。
  ///
  /// 返回 null 表示被取消。
  Future<PoseExtractionResult?> run({
    required String videoUri,
    PoseExtractionConfig config = const PoseExtractionConfig(),
    void Function(ExtractionProgress)? onProgress,
  }) async {
    _cancelled = false;
    final t0 = DateTime.now();
    final notes = <String>[];

    // ---- ① 加载模型 ----
    //
    // 这一步要几秒（12.9 MB 的模型 + 原生层初始化）。
    // 先做，因为它最容易失败 —— 失败了后面都不用跑。
    onProgress?.call(const ExtractionProgress(
      phase: '加载模型',
      fraction: 0.0,
      detail: '首次使用需要几秒',
    ));
    await _model.load();

    if (_cancelled) return null;

    // ---- ② 取帧 ----
    final decoder = FrameDecoder();
    final frames = <DerivedFrame>[];
    final heights = <int, double>{};
    var decoded = 0;
    var ambiguous = 0;

    onProgress?.call(const ExtractionProgress(
      phase: '读取视频',
      fraction: 0.02,
    ));

    final stream = decoder.decode(
      uri: videoUri,
      count: config.maxFrames,
      startMs: config.startMs,
      fps: config.fps,
    );

    await for (final event in stream) {
      if (_cancelled) return null;

      if (event is DecodeProgress) {
        onProgress?.call(ExtractionProgress(
          phase: '读取视频',
          // 取帧占总进度的前 25%
          fraction: 0.02 + event.fraction * 0.23,
          detail: '${event.done} / ${event.total} 帧',
        ));
        continue;
      }

      if (event is! DecodedFrame) continue;
      decoded++;

      if (!event.isValid) {
        // 取不到这一帧。如实记一笔，**不跳过序号** ——
        // 跳过会让后面的帧号与时间对不上，而那种错很难查。
        notes.add('第 ${event.index} 帧取不到');
        continue;
      }

      // ---- ③ 解码 JPEG ----
      final image = await _decodeJpeg(event.jpeg!);
      if (image == null) {
        notes.add('第 ${event.index} 帧解码失败');
        continue;
      }

      // ---- ④ letterbox + 推理 ----
      final lb = computeLetterbox(image.width, image.height, _model.inputSize);
      final rgba = await _letterboxToRgba(image, lb);
      image.dispose();

      List<PoseCandidate> cands;
      try {
        cands = _model.inferFrame(rgba, letterbox: lb);
      } on PoseInferenceException {
        // 推理失败是**致命**的（模型/原生库有问题），不该逐帧吞掉。
        rethrow;
      }

      // ---- ⑤ 选人 ----
      final sel = selectPerson(cands);
      if (sel.isAmbiguous) ambiguous++;

      final primary = sel.primary;
      if (primary == null) continue;

      final frame = toPoseFrame(primary, event.index);
      frames.add(deriveFrame(frame));

      // 记录人物高度占画面的比例 —— 拍摄质量检查要用
      final bb = frame.boundingBox;
      if (bb != null) {
        heights[event.index] = bb.$4 - bb.$2;
      }

      // 推理占总进度的 25%~85%
      if (decoded % 5 == 0) {
        onProgress?.call(ExtractionProgress(
          phase: '识别姿态',
          fraction: 0.25 + (decoded / config.maxFrames) * 0.60,
          detail: '已处理 $decoded 帧，检出 ${frames.length} 帧姿态',
        ));
      }
    }

    if (_cancelled) return null;

    final seq = PoseSequence(
      frames: frames.map((d) => d.frame).toList(),
      sourceWidth: 0,   // 手机端不保留原图尺寸（坐标已是归一化）
      sourceHeight: 0,
    );

    // ---- ⑥ 事件与相位 ----
    onProgress?.call(const ExtractionProgress(
      phase: '检测步态事件',
      fraction: 0.88,
    ));

    // fps 用**实际采样帧率**，不是视频的原始帧率 ——
    // 因为我们每 intervalMs 取一帧，序列的时间轴就是采样后的。
    final events = detectGaitEvents(seq, fps: config.fps);
    final phases = detectPhases(seq, fps: config.fps, events: events);

    // ---- ⑦ 选关键帧 ----
    onProgress?.call(const ExtractionProgress(
      phase: '挑选关键帧',
      fraction: 0.95,
    ));

    final keyframes = selectKeyframes(
      seq,
      phases,
      events: events,
      personHeights: heights,
    );

    onProgress?.call(const ExtractionProgress(
      phase: '完成',
      fraction: 1.0,
    ));

    return PoseExtractionResult(
      sequence: seq,
      derivedFrames: frames,
      events: events,
      phases: phases,
      keyframes: keyframes,
      elapsedMs: DateTime.now().difference(t0).inMilliseconds,
      framesDecoded: decoded,
      framesWithPose: frames.length,
      personHeights: heights,
      ambiguousFrames: ambiguous,
      notes: notes,
    );
  }

  /// 解码 JPEG 为 RGBA 图。
  Future<ui.Image?> _decodeJpeg(Uint8List jpeg) async {
    try {
      final codec = await ui.instantiateImageCodec(jpeg);
      final frame = await codec.getNextFrame();
      codec.dispose();
      return frame.image;
    } catch (_) {
      return null;
    }
  }

  /// letterbox 到方形并转成 RGBA 字节。
  ///
  /// ## 为什么在 Dart 里做缩放而不是原生侧
  ///
  /// 原生侧只做"缩到 640 长边"这一步粗缩放。**精确的 letterbox
  /// 必须在 Dart 里做**，因为：
  ///   · letterbox 参数要参与坐标反映射，两边必须用同一套数
  ///   · 放在 Dart 里便于单元测试（原生代码在测试里跑不了）
  ///
  /// 用 `Canvas.drawImageRect` 而不是逐像素循环：
  /// 后者在 Dart 里对 640×640 要跑 40 万次迭代，明显卡顿。
  Future<Uint8List> _letterboxToRgba(ui.Image src, Letterbox lb) async {
    final size = _model.inputSize;
    final recorder = ui.PictureRecorder();
    final canvas = ui.Canvas(recorder);

    // 填充色 114 —— 与 YOLO 训练时一致。
    // 用别的颜色会让填充区被当成真实内容，影响检出。
    canvas.drawRect(
      ui.Rect.fromLTWH(0, 0, size.toDouble(), size.toDouble()),
      ui.Paint()..color = const ui.Color.fromARGB(255, 114, 114, 114),
    );

    final dst = ui.Rect.fromLTWH(
      lb.padX,
      lb.padY,
      src.width * lb.scale,
      src.height * lb.scale,
    );
    final srcRect =
        ui.Rect.fromLTWH(0, 0, src.width.toDouble(), src.height.toDouble());

    canvas.drawImageRect(
      src,
      srcRect,
      dst,
      ui.Paint()..filterQuality = ui.FilterQuality.medium,
    );

    final picture = recorder.endRecording();
    final img = await picture.toImage(size, size);
    picture.dispose();

    final data = await img.toByteData(format: ui.ImageByteFormat.rawRgba);
    img.dispose();

    if (data == null) {
      throw StateError('letterbox 后拿不到像素数据');
    }
    return data.buffer.asUint8List();
  }

  void dispose() {
    _ownModel?.dispose();
    _ownModel = null;
  }
}
