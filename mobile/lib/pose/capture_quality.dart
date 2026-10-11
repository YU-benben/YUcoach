/// 拍摄质量检查。
///
/// ## 为什么这个模块可能是整个手机端最有价值的部分
///
/// 实测那段素材（960×540）：
///
///     运动员占画面   **宽 10.0% × 高 12.6%**
///     拍摄标准要求   高 **33%** 以上
///
/// **差了将近 3 倍。** 而这一条能解释后面所有的精度问题：
///
///     人只有 34 像素高
///         ↓
///     关键点抖动 3 像素 = 相对误差 9%
///         ↓
///     而噪声敏感性分析假设的是 3 像素绝对噪声（约 1% 相对误差）
///         ↓
///     所以所有角度指标的误差都比预期大一个量级
///
/// **这个检查能提前告诉用户"这段素材不行"，而不是让他拿到一份
/// 看不出问题的错误报告。**
///
/// 这比事后修算法有价值得多 —— 因为信息在拍摄那一刻就丢了，
/// 任何算法都补不回来。
library;

import 'dart:math' as math;

import 'pose_types.dart';

/// 拍摄质量问题的严重程度。
enum CaptureIssueLevel {
  /// 可以分析。
  ok,

  /// 能算但精度会下降。应当在报告里说明。
  warning,

  /// 无法得到可靠结果。应当建议重拍。
  blocking,
}

/// 一条拍摄质量问题。
class CaptureIssue {
  const CaptureIssue({
    required this.level,
    required this.title,
    required this.detail,
    required this.suggestion,
  });

  final CaptureIssueLevel level;
  final String title;
  final String detail;

  /// 怎么改进。**必须给出可执行的建议** ——
  /// 只说"素材不合格"对用户没有帮助。
  final String suggestion;

  @override
  String toString() => '[${level.name}] $title：$detail';
}

/// 拍摄质量报告。
class CaptureQuality {
  const CaptureQuality({
    required this.issues,
    required this.maxPersonHeightFraction,
    required this.maxPersonAreaFraction,
    required this.framesWithPerson,
    required this.totalFrames,
    this.fps,
    this.ambiguousFrameRatio = 0,
  });

  final List<CaptureIssue> issues;

  /// 检测到的最大人物高度占画面比例。
  final double maxPersonHeightFraction;

  /// 检测到的最大人物面积占画面比例。
  final double maxPersonAreaFraction;

  /// 检出人的帧数。
  final int framesWithPerson;

  /// 总帧数。
  final int totalFrames;

  /// 帧率。未知为 null。
  final double? fps;

  /// 选人有歧义的帧占比（画面里人多）。
  final double ambiguousFrameRatio;

  /// 是否有阻断级问题。
  bool get hasBlocking =>
      issues.any((i) => i.level == CaptureIssueLevel.blocking);

  /// 是否全部通过。
  bool get isClean => issues.isEmpty;

  /// 检出率（有人的帧占比）。
  double get detectionRate =>
      totalFrames == 0 ? 0 : framesWithPerson / totalFrames;

  /// 一句话结论。
  String get verdict {
    if (issues.any((i) => i.level == CaptureIssueLevel.blocking)) {
      return '素材不满足分析要求，建议重拍';
    }
    if (issues.any((i) => i.level == CaptureIssueLevel.warning)) {
      return '可以分析，但精度会受影响';
    }
    return '素材符合要求';
  }
}

/// 拍摄标准的门槛值。
///
/// 这些数字来自项目的拍摄标准（见 README 与 App 内的拍摄要点），
/// **不是随手定的**：
///
///   · 占画面高度 1/3 —— 低于它关键点会糊，抖动淹没真实信号
///   · 帧率 120 —— 触地只有 80~120 毫秒，60 fps 以下测不准
class CaptureStandards {
  const CaptureStandards._();

  /// 运动员应占画面高度的比例。
  static const double minPersonHeight = 0.33;

  /// 低于这个比例就完全无法分析。
  ///
  /// 取 0.15 而不是 0.33：0.15~0.33 之间是"能算但不准"，
  /// 应当警告；低于 0.15 才是"算了也没意义"。
  ///
  /// 实测那份素材是 0.126 —— 落在 blocking 区间。
  static const double blockingPersonHeight = 0.15;

  /// 触地时间类指标所需的帧率。
  static const double minFpsForTemporal = 120.0;

  /// 角度类指标所需的最低帧率。
  static const double minFpsForAngles = 60.0;

  /// 有人的帧占比低于它就说明跟踪失败。
  static const double minDetectionRate = 0.5;

  /// 选人歧义的帧占比超过它就说明画面里太乱。
  static const double maxAmbiguousRatio = 0.5;
}

/// 评估拍摄质量。
///
/// 参数
/// ----
/// seq : 姿态序列。只用到每帧的框大小与可见点。
/// fps : 帧率。未知传 null —— 那会跳过帧率检查并给出提示，
///       而不是假装通过。
/// personHeights : 每帧人物高度占画面的比例。
///                 由姿态提取阶段算出（用框高或关键点包围盒高）。
/// ambiguousFrames : 选人有歧义的帧数。
CaptureQuality assessCaptureQuality({
  required PoseSequence seq,
  double? fps,
  required List<double> personHeights,
  int ambiguousFrames = 0,
  int? expectedFrames,
}) {
  final issues = <CaptureIssue>[];

  final total = expectedFrames ?? seq.length;
  final withPerson = personHeights.where((h) => h > 0).length;

  final maxH = personHeights.isEmpty
      ? 0.0
      : personHeights.reduce(math.max);
  // 面积近似：高度比例 × 按 16:9 估算的宽度比例。
  // 精确面积需要框的宽高，而这里只用高度做判据已经足够 ——
  // 因为拍摄标准本身就是按"画面高度"定义的。
  final maxArea = maxH * (maxH * 9 / 16);

  final ambRatio = total == 0 ? 0.0 : ambiguousFrames / total;

  // ---- 1. 人物大小（最重要的判据）----
  if (maxH > 0 && maxH < CaptureStandards.blockingPersonHeight) {
    issues.add(CaptureIssue(
      level: CaptureIssueLevel.blocking,
      title: '运动员在画面里太小',
      detail: '只占画面高度的 ${(maxH * 100).toStringAsFixed(1)}%，'
          '远低于要求的 ${(CaptureStandards.minPersonHeight * 100).round()}%。'
          '关键点会糊在一起，测出来的角度和时序都不可靠。',
      suggestion: '把机位移近，或用手机的变焦把运动员拉大 —— '
          '目标是让他占满画面高度的三分之一以上。'
          '宁可只拍两三步，也不要拍成一个小人影。',
    ));
  } else if (maxH > 0 && maxH < CaptureStandards.minPersonHeight) {
    issues.add(CaptureIssue(
      level: CaptureIssueLevel.warning,
      title: '运动员偏小',
      detail: '占画面高度的 ${(maxH * 100).toStringAsFixed(1)}%，'
          '略低于建议的 ${(CaptureStandards.minPersonHeight * 100).round()}%。'
          '关键点抖动会变大，角度指标仍可用，但时序类指标要谨慎看待。',
      suggestion: '下次拍摄把机位移近一些。',
    ));
  }

  // ---- 2. 帧率 ----
  if (fps == null) {
    issues.add(const CaptureIssue(
      level: CaptureIssueLevel.warning,
      title: '没有读到帧率',
      detail: '无法判断时序类指标（触地时间、腾空时间）能否计算。',
      suggestion: '用手机自带的相机 App 拍摄，不要用第三方压缩过的视频。',
    ));
  } else if (fps < CaptureStandards.minFpsForAngles) {
    issues.add(CaptureIssue(
      level: CaptureIssueLevel.blocking,
      title: '帧率过低',
      detail: '当前 ${fps.toStringAsFixed(0)} fps，'
          '连角度类指标都偏低（建议 ${CaptureStandards.minFpsForAngles.round()} fps 以上）。'
          '触地只有 80~120 毫秒，${fps.toStringAsFixed(0)} fps 下只占 '
          '${(fps * 0.1).toStringAsFixed(0)} 帧左右。',
      suggestion: '用手机的「慢动作」模式拍摄，通常是 120 或 240 fps。',
    ));
  } else if (fps < CaptureStandards.minFpsForTemporal) {
    issues.add(CaptureIssue(
      level: CaptureIssueLevel.warning,
      title: '帧率不足以测时序指标',
      detail: '当前 ${fps.toStringAsFixed(0)} fps。角度类指标可以算，'
          '但触地时间、腾空时间这类只持续几十毫秒的量测不准 —— '
          '每帧间隔就有 ${(1000 / fps).toStringAsFixed(0)} 毫秒。',
      suggestion: '如果关心触地/腾空时间，用慢动作模式（120 fps 以上）重拍；'
          '只看姿态角度的话这个帧率够用。',
    ));
  }

  // ---- 3. 检出率 ----
  final rate = total == 0 ? 0.0 : withPerson / total;
  if (total > 0 && rate < CaptureStandards.minDetectionRate) {
    issues.add(CaptureIssue(
      level: CaptureIssueLevel.blocking,
      title: '大部分帧没检出人',
      detail: '只有 ${(rate * 100).toStringAsFixed(0)}% 的帧找到了运动员。'
          '常见原因：人被遮挡、跑出画面，或者画面太暗。',
      suggestion: '确认镜头一直跟着运动员；避免让他被其他人或器材挡住。',
    ));
  }

  // ---- 4. 画面里人太多 ----
  if (ambRatio > CaptureStandards.maxAmbiguousRatio) {
    issues.add(CaptureIssue(
      level: CaptureIssueLevel.warning,
      title: '画面里人比较多',
      detail: '有 ${(ambRatio * 100).toStringAsFixed(0)}% 的帧存在'
          '「该分析谁」的歧义。系统选了占画面最大的那个，'
          '但如果背景有人离镜头更近，可能会选错。',
      suggestion: '拍摄时让镜头只对准运动员，尽量避开其他人和观众。',
    ));
  }

  return CaptureQuality(
    issues: issues,
    maxPersonHeightFraction: maxH,
    maxPersonAreaFraction: maxArea,
    framesWithPerson: withPerson,
    totalFrames: total,
    fps: fps,
    ambiguousFrameRatio: ambRatio,
  );
}
