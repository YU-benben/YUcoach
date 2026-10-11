/// 姿态估计的数据类型。
///
/// ## 与 Python 端保持一致
///
/// 这里的定义必须和 `backend/analysis/pose_types.py` 对齐 ——
/// 因为两边算出来的骨架会进同一个算法，也会出现在同一批报告里。
/// 不一致的话，同一个运动员在手机上和在电脑上会得到不同的结论。
///
/// ## 关键点的顺序是**契约**
///
/// COCO-17 的顺序不能改。模型输出就是按这个顺序来的，
/// 改了会让所有关节对错位置 —— 而且因为人体左右对称，
/// 错了之后数值看起来还挺"合理"，很难发现。
library;

import 'dart:math' as math;

/// 质量码。
///
/// 与 Python 端 `Q_INVISIBLE / Q_UNCERTAIN / Q_CLEAR` 一致。
class QualityCode {
  const QualityCode._();

  /// 不可见。**不绘制**，相关骨骼线断开。
  static const int invisible = 0;

  /// 存疑。用空心点绘制，提示"别全信"。
  static const int uncertain = 1;

  /// 清晰。实心点。
  static const int clear = 2;
}

/// COCO-17 关键点名称，顺序与模型输出一致。
///
/// ⚠️ **不要重排这个列表。** 模型输出的第 i 个点就是这里的第 i 个名字。
///    重排会让关节全部错位，而且左右对称的人体让错误看起来"正常"。
const List<String> cocoNames = [
  'nose', // 0
  'eye_l', // 1
  'eye_r', // 2
  'ear_l', // 3
  'ear_r', // 4
  'shoulder_l', // 5
  'shoulder_r', // 6
  'elbow_l', // 7
  'elbow_r', // 8
  'wrist_l', // 9
  'wrist_r', // 10
  'hip_l', // 11
  'hip_r', // 12
  'knee_l', // 13
  'knee_r', // 14
  'ankle_l', // 15
  'ankle_r', // 16
];

/// COCO-17 的点数。
const int cocoKeypointCount = 17;

/// 一个关键点。
class Keypoint {
  const Keypoint({
    required this.x,
    required this.y,
    required this.confidence,
  });

  /// 归一化坐标（0~1），相对**原图**尺寸。
  ///
  /// 用归一化而不是像素，是因为：
  ///   · 算法层不需要知道图片多大
  ///   · 换分辨率不影响已有数据
  ///   · 和 Python 端一致
  final double x;
  final double y;

  /// 模型对这个点的置信度（0~1）。**不是**质量码。
  ///
  /// 质量码要由置信度 + 其他判断（可见性、解剖学合理性）综合得出，
  /// 这一步在 [qualityOf] 里做。
  final double confidence;

  /// 对应的质量码。
  int get quality => qualityOf(confidence);

  /// 按置信度判定质量码。
  ///
  /// ⚠️ 阈值必须和 Python 端一致。
  ///    Python 端：`pose_estimator.py` 里把 YOLO 的置信度映射成质量码。
  ///    两边不一致的话，手机上显示"清晰"的点在电脑上可能显示"存疑"。
  static int qualityOf(double conf) {
    if (conf >= 0.5) return QualityCode.clear;
    if (conf >= 0.25) return QualityCode.uncertain;
    return QualityCode.invisible;
  }

  /// 是否可见（质量码非 0）。
  bool get visible => quality != QualityCode.invisible;

  @override
  String toString() =>
      'Keypoint(${x.toStringAsFixed(4)}, ${y.toStringAsFixed(4)}, '
      'conf=${confidence.toStringAsFixed(3)})';
}

/// 一个人的姿态（某一帧）。
class PoseFrame {
  const PoseFrame({
    required this.frameIndex,
    required this.keypoints,
    this.boxConfidence = 1.0,
  });

  final int frameIndex;

  /// 17 个关键点，顺序见 [cocoNames]。
  final List<Keypoint> keypoints;

  /// 该人的整体检出置信度。
  ///
  /// 为什么要单独存：选人时用的是它，而不是各关键点的平均置信度。
  /// 一个蹲着的人可能所有点都模糊（低点置信度），
  /// 但"这里确实有个人"这件事是确定的。
  final double boxConfidence;

  /// 按名字取关键点。名字不存在时返回 null。
  Keypoint? byName(String name) {
    final i = cocoNames.indexOf(name);
    if (i < 0 || i >= keypoints.length) return null;
    return keypoints[i];
  }

  /// 可见点的比例。用于质量评分。
  double get coverage {
    if (keypoints.isEmpty) return 0;
    final n = keypoints.where((k) => k.visible).length;
    return n / keypoints.length;
  }

  /// 关键点包围盒（归一化坐标），格式 (minX, minY, maxX, maxY)。
  ///
  /// 只统计可见点 —— 一个跑到画面外的点会把包围盒撑得很大，
  /// 那会让裁剪、缩放全部算错。
  (double, double, double, double)? get boundingBox {
    final vis = keypoints.where((k) => k.visible).toList();
    if (vis.length < 3) return null;
    var minX = vis.first.x, maxX = vis.first.x;
    var minY = vis.first.y, maxY = vis.first.y;
    for (final k in vis) {
      minX = math.min(minX, k.x);
      maxX = math.max(maxX, k.x);
      minY = math.min(minY, k.y);
      maxY = math.max(maxY, k.y);
    }
    return (minX, minY, maxX, maxY);
  }

  @override
  String toString() =>
      'PoseFrame(#$frameIndex, ${keypoints.length} 点, '
      '覆盖 ${(coverage * 100).toStringAsFixed(0)}%)';
}

/// 一段视频的全部姿态。
class PoseSequence {
  PoseSequence({
    required this.frames,
    required this.sourceWidth,
    required this.sourceHeight,
  });

  final List<PoseFrame> frames;

  /// 原图尺寸。归一化坐标乘上它就是像素坐标。
  final int sourceWidth;
  final int sourceHeight;

  int get length => frames.length;
  bool get isEmpty => frames.isEmpty;
  bool get isNotEmpty => frames.isNotEmpty;

  /// 按帧号取。找不到返回 null。
  PoseFrame? at(int frameIndex) {
    for (final f in frames) {
      if (f.frameIndex == frameIndex) return f;
    }
    return null;
  }

  /// 每个关键点的可见率。用于质量报告。
  Map<String, double> coverageByKeypoint() {
    if (frames.isEmpty) return {};
    final out = <String, double>{};
    for (var i = 0; i < cocoNames.length; i++) {
      var n = 0;
      for (final f in frames) {
        if (i < f.keypoints.length && f.keypoints[i].visible) n++;
      }
      out[cocoNames[i]] = n / frames.length;
    }
    return out;
  }

  @override
  String toString() =>
      'PoseSequence(${frames.length} 帧, ${sourceWidth}x$sourceHeight)';
}
