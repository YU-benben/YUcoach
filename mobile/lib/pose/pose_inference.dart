/// ONNX Runtime 推理封装。
///
/// ## 这一层的职责
///
/// ```
/// 图片（RGBA 像素） → 前处理 → 模型 → 后处理 → 关键点
///                     ↓                    ↓
///                  letterbox          yolo_postprocess.dart
/// ```
///
/// 中间那步（跑模型）就是本文件。
///
/// ## ⚠️ 关于 onnxruntime 这个包
///
/// 它最后发布于两年前，**没有在真机上验证过**。所以这里的做法是：
///
///   · 所有可能失败的地方都**捕获并给出人话错误**，而不是让异常冒上去
///   · 加载失败时**明确告诉用户原因**，而不是白屏
///   · 暴露 [warmup] 让调用方能在正式跑之前先探一次
///
/// 一旦真机验证发现问题，改动集中在这一个文件里。
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:onnxruntime/onnxruntime.dart';

import 'pose_types.dart';
import 'yolo_postprocess.dart';

/// 推理失败的原因。
enum InferenceError {
  /// 模型文件加载失败（asset 缺失或损坏）。
  modelLoadFailed,

  /// ONNX Runtime 原生库没加载上（架构不匹配时会发生）。
  nativeLibraryMissing,

  /// 推理过程抛异常。
  runFailed,

  /// 输入图像尺寸不对。
  badInput,
}

extension InferenceErrorText on InferenceError {
  String get message => switch (this) {
        InferenceError.modelLoadFailed =>
          '模型文件加载失败。可能是安装包损坏，重新安装试试。',
        InferenceError.nativeLibraryMissing =>
          '推理引擎没有加载上。\n\n'
              '这个版本只支持 64 位 ARM 手机（2017 年后的机型）。'
              '如果你的是更早的手机，请用「上传到电脑分析」的方式。',
        InferenceError.runFailed => '推理出错。可以重试，或换一段更短的视频。',
        InferenceError.badInput => '图像尺寸不对，这是程序错误，请反馈。',
      };
}

/// 推理异常。
class PoseInferenceException implements Exception {
  const PoseInferenceException(this.kind, [this.detail]);

  final InferenceError kind;

  /// 技术细节。给开发者看，不直接显示给用户。
  final String? detail;

  /// 给用户看的说明。
  String get userMessage => kind.message;

  @override
  String toString() => 'PoseInferenceException(${kind.name}'
      '${detail == null ? '' : ': $detail'})';
}

/// ONNX 姿态模型。
///
/// ## 用法
///
/// ```dart
/// final model = PoseOnnxModel();
/// await model.load();                 // 加载模型（几秒）
/// final kps = model.inferFrame(rgba); // 逐帧推理
/// model.dispose();
/// ```
///
/// ## 线程
///
/// ONNX Runtime 的推理是**同步阻塞**的。在 UI 线程上跑会卡死界面。
/// 所以调用方必须自己在 `Isolate` 里跑（见 `pose_pipeline.dart`）。
class PoseOnnxModel {
  PoseOnnxModel({
    this.assetPath = defaultAssetPath,
    this.inputSize = 640,
    this.confThreshold = 0.25,
  });

  /// 模型在 assets 里的路径。
  static const defaultAssetPath = 'assets/models/yolov8n-pose-640.onnx';

  final String assetPath;

  /// 模型输入边长。**必须和导出时一致** ——
  /// 不一致的话输出会完全错乱，而且不会报错。
  final int inputSize;

  /// 置信度阈值。
  final double confThreshold;

  OrtSession? _session;
  bool _ready = false;

  bool get isReady => _ready;

  /// 加载模型。
  ///
  /// 抛 [PoseInferenceException]，调用方据此显示人话提示。
  Future<void> load() async {
    if (_ready) return;

    try {
      // OrtEnv 是全局单例。重复 init 会怎样取决于包的实现，
      // 所以用 try 包住 —— 已经初始化过就当成功。
      try {
        OrtEnv.instance.init();
      } catch (_) {
        // 已经初始化过了。忽略。
      }
    } catch (e) {
      throw PoseInferenceException(
          InferenceError.nativeLibraryMissing, e.toString());
    }

    ByteData raw;
    try {
      raw = await rootBundle.load(assetPath);
    } catch (e) {
      throw PoseInferenceException(
          InferenceError.modelLoadFailed, '读不到 $assetPath: $e');
    }

    try {
      final options = OrtSessionOptions();
      // 图优化开到最大：手机上能省不少时间。
      options.setSessionGraphOptimizationLevel(
          GraphOptimizationLevel.ortEnableAll);
      // 线程数交给运行时自己定。手工设成 CPU 核数在手机上常常更慢
      // （大核小核混在一起，线程间同步开销反而更大）。

      final bytes = raw.buffer.asUint8List();
      _session = OrtSession.fromBuffer(bytes, options);
      _ready = true;
    } catch (e) {
      throw PoseInferenceException(
          InferenceError.modelLoadFailed, e.toString());
    }
  }

  /// 跑一帧。
  ///
  /// 参数 [rgba] 是**已 letterbox 到 inputSize×inputSize 的 RGBA 像素**，
  /// 长度必须是 `inputSize * inputSize * 4`。
  ///
  /// 返回所有候选（已做置信度筛选与坐标反映射），按得分排序。
  ///
  /// ## 为什么输入是"已经 letterbox 过的"
  ///
  /// 缩放和填充是纯数学，放在 Dart 里做很快，而且**便于单元测试**。
  /// 让原生层去做的话，出错了很难查。
  List<PoseCandidate> inferFrame(
    Uint8List rgba, {
    required Letterbox letterbox,
  }) {
    final session = _session;
    if (session == null) {
      throw const PoseInferenceException(
          InferenceError.modelLoadFailed, '模型尚未加载');
    }

    final expected = inputSize * inputSize * 4;
    if (rgba.length != expected) {
      throw PoseInferenceException(
          InferenceError.badInput,
          '期望 $expected 字节，实际 ${rgba.length}');
    }

    // ---- 前处理：RGBA → 归一化的 CHW float32 ----
    final tensor = _toChwFloat(rgba);

    final inputOrt = OrtValueTensor.createTensorWithDataList(
      tensor,
      [1, 3, inputSize, inputSize],
    );

    List<OrtValue?>? outputs;
    try {
      final inputs = {session.inputNames.first: inputOrt};
      final runOptions = OrtRunOptions();
      try {
        outputs = session.run(runOptions, inputs);
      } finally {
        runOptions.release();
      }

      if (outputs.isEmpty || outputs.first == null) {
        throw const PoseInferenceException(
            InferenceError.runFailed, '模型没有返回输出');
      }

      final out = outputs.first!.value;
      if (out is! List) {
        throw const PoseInferenceException(
            InferenceError.runFailed, '输出类型不是张量');
      }

      // 输出形状 (1, 56, 8400)。包会给成嵌套 List，
      // 这里拍平成 Float32List 交给解析器 ——
      // 解析器只认平铺的 [通道][候选] 布局。
      final flat = _flattenToFloat32(out);
      return parseYoloPose(
        flat,
        lb: letterbox,
        keypointCount: cocoKeypointCount,
        confThreshold: confThreshold,
      );
    } finally {
      // ⚠️ OrtValue 必须在原生层释放，否则每帧泄漏一块内存。
      //    一场 1200 帧的分析足以把手机内存吃光。
      inputOrt.release();
      outputs?.forEach((o) => o?.release());
    }
  }

  /// RGBA → 归一化的 CHW float32。
  ///
  /// 模型要的是 RGB 平面排列（先所有 R，再所有 G，再所有 B），
  /// 数值范围 0~1。而手机给的是交错排列的 RGBA、0~255。
  Float32List _toChwFloat(Uint8List rgba) {
    final n = inputSize * inputSize;
    final out = Float32List(3 * n);

    for (var i = 0; i < n; i++) {
      final o = i * 4;
      // 除以 255 而不是 256 —— 与电脑端一致（cv2 的 /255.0）
      out[i] = rgba[o] / 255.0;             // R
      out[n + i] = rgba[o + 1] / 255.0;     // G
      out[2 * n + i] = rgba[o + 2] / 255.0; // B
      // alpha 丢掉：模型的输入是 3 通道
    }
    return out;
  }

  /// 把包返回的嵌套 List 拍平成 Float32List。
  ///
  /// 输出是 (1, 56, 8400)，包会包成 `[[[..],[..],...]]`。
  /// 解析器要的是**按 [通道][候选] 排列的一维数组**，
  /// 也就是把 batch 维度去掉后的 `[56][8400]` 直接铺平。
  Float32List _flattenToFloat32(List<dynamic> nested) {
    // 去掉 batch 维
    var cur = nested;
    while (cur.length == 1 && cur.first is List) {
      cur = cur.first as List<dynamic>;
    }

    final channels = YoloPoseLayout.channels(cocoKeypointCount);

    // 期望 cur 是 [56][8400]
    if (cur.length != channels) {
      throw PoseInferenceException(
        InferenceError.runFailed,
        '输出通道数是 ${cur.length}，期望 $channels',
      );
    }

    final first = cur.first;
    if (first is! List) {
      throw const PoseInferenceException(
          InferenceError.runFailed, '输出第二维不是数组');
    }
    final n = first.length;

    final flat = Float32List(channels * n);
    for (var c = 0; c < channels; c++) {
      final row = cur[c];
      if (row is! List || row.length != n) {
        throw const PoseInferenceException(
            InferenceError.runFailed, '输出各行长度不一致');
      }
      final base = c * n;
      for (var i = 0; i < n; i++) {
        final v = row[i];
        flat[base + i] = v is num ? v.toDouble() : 0.0;
      }
    }
    return flat;
  }

  /// 释放原生资源。
  ///
  /// **必须调用** —— 不释放的话 OrtSession 在原生层一直占着内存，
  /// 反复分析会累积到 OOM。
  void dispose() {
    _session?.release();
    _session = null;
    _ready = false;
  }
}

/// 把模型的加载状态做成一个可观察对象，供界面显示。
///
/// 为什么要单独一个类：模型加载要几秒，界面需要知道
/// "正在加载 / 加载好了 / 加载失败（什么原因）"。
class PoseModelStatus extends ChangeNotifier {
  final _model = PoseOnnxModel();

  PoseOnnxModel get model => _model;

  bool _loading = false;
  bool _ready = false;
  String? _error;

  bool get loading => _loading;
  bool get ready => _ready;
  String? get error => _error;

  /// 加载模型。可以重复调用，已加载则直接返回。
  Future<void> ensureLoaded() async {
    if (_ready || _loading) return;

    _loading = true;
    _error = null;
    notifyListeners();

    try {
      await _model.load();
      _ready = true;
    } on PoseInferenceException catch (e) {
      _error = e.userMessage;
    } catch (e) {
      // 兜底：任何非预期异常也变成人话，而不是让界面崩掉。
      _error = '推理引擎初始化失败。\n\n技术细节：$e';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _model.dispose();
    super.dispose();
  }
}
