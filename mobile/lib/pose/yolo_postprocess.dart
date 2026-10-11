/// YOLO-pose 输出的解析。
///
/// ## 为什么手机端要自己写这部分
///
/// 电脑上，从网络输出到 17 个关键点，是 **Ultralytics 帮着做的**
/// （含置信度筛选、NMS、坐标反映射）。手机上没这个库，要自己实现。
///
/// ## ⚠️ 这是最容易出错、也最难发现错误的地方
///
/// 错了不会报错，只会让关键点**悄悄偏一点**：
///
///   · letterbox 填充算错 → 所有点整体偏移，看起来"人站歪了"
///   · 坐标反映射漏掉 → 所有点缩放错误，看起来"人变大变小了"
///   · 关键点索引错位 → 关节对错位置，但**人体左右对称会让它看起来正常**
///
/// 所以这一段的每一处都要有测试守护，而且要和 Python 端**对拍**。
library;

import 'dart:math' as math;
import 'dart:typed_data';

import 'pose_types.dart';

/// letterbox 的结果。
class Letterbox {
  const Letterbox({
    required this.scale,
    required this.padX,
    required this.padY,
    required this.inputSize,
    required this.originalWidth,
    required this.originalHeight,
  });

  /// 缩放比例（原图 → 网络输入）。
  final double scale;

  /// 填充量（网络输入坐标系，单位像素）。
  final double padX;
  final double padY;

  /// 网络输入边长（正方形）。
  final int inputSize;

  final int originalWidth;
  final int originalHeight;

  /// 网络输入坐标系（**像素**，0~inputSize）→ 原图归一化坐标。
  ///
  /// ## ⚠️ 输出的量纲是**像素**，不是归一化值 —— 这里踩过坑
  ///
  /// 第一版假设模型输出的框和关键点坐标是 0~1 归一化的，写成：
  ///
  ///     原图归一化 = (输出值 × inputSize − pad) / scale / 原图边长
  ///
  /// **结果解析出来的坐标整体大了 640 倍**（正好等于输入边长）。
  ///
  /// 实测确认（`scripts/_check_output_units.py`）：
  ///
  ///     关键点 x 范围 [181.70, 226.07]
  ///     框 cx  范围 [  3.07, 637.38]     ← 明显是 0~640 的像素值
  ///
  /// 用像素公式算出的值与 Ultralytics 的期望值**小数点后 4 位完全吻合**。
  ///
  /// 这个错误是**对拍测试**抓出来的，不是靠肉眼看代码发现的 ——
  /// 因为算错的结果不会报错，只是数字大了一截。
  ///
  /// ## 推导
  ///
  ///     原图像素 = (网络输入像素 − pad) / scale
  ///     原图归一化 = 原图像素 / 原图边长
  ///
  /// 合并即下式。
  double toOriginalX(double px) =>
      (px - padX) / scale / originalWidth;

  double toOriginalY(double py) =>
      (py - padY) / scale / originalHeight;

  @override
  String toString() => 'Letterbox(scale=${scale.toStringAsFixed(4)}, '
      'pad=(${padX.toStringAsFixed(1)}, ${padY.toStringAsFixed(1)}), '
      'input=$inputSize, orig=${originalWidth}x$originalHeight)';
}

/// 计算 letterbox 参数。
///
/// ## 为什么用 letterbox 而不是直接拉伸
///
/// 拉伸会改变长宽比。一个 16:9 的视频拉成 1:1，
/// 人会被横向压扁 —— 所有角度指标全错。
///
/// letterbox 保持比例，多出来的部分填灰（114,114,114 ——
/// YOLO 训练时用的填充色，必须一致，否则填充区会被当成真实内容）。
Letterbox computeLetterbox(int width, int height, int inputSize) {
  final scale = math.min(inputSize / width, inputSize / height);
  final newW = width * scale;
  final newH = height * scale;
  // 居中填充。YOLO 官方实现是这样做的，必须一致。
  final padX = (inputSize - newW) / 2;
  final padY = (inputSize - newH) / 2;
  return Letterbox(
    scale: scale,
    padX: padX,
    padY: padY,
    inputSize: inputSize,
    originalWidth: width,
    originalHeight: height,
  );
}

/// YOLO 输出的维度布局。
///
/// 输出的形状是 `(1, 4 + 1 + 17×3, 候选框数)` = `(1, 56, 8400)`。
///
/// ⚠️ **这是转置的**：每个候选的 56 个数是**跨行**分布的，
///    即 `output[k * n + i]` 是第 i 个候选的第 k 个数。
///    内存里是按 [通道][候选] 排的，不是按 [候选][通道]。
///
///    搞错这个会让解析出来的数字完全是乱的，但**形状仍然对**，
///    所以不会有异常，只会得到一堆垃圾关键点。
///
/// ⚠️ 坐标的量纲是**像素**（0~inputSize），不是 0~1 归一化值。
///    这一点被实测确认过，详见 [Letterbox.toOriginalX] 的说明。
class YoloPoseLayout {
  const YoloPoseLayout._();

  /// 框参数个数：中心 x、中心 y、宽、高。
  static const int boxParams = 4;

  /// 每个候选的总通道数。
  static int channels(int keypointCount) =>
      boxParams + 1 + keypointCount * 3;

  /// 框置信度在第几个通道。
  static const int confidenceIndex = 4;

  /// 关键点从第几个通道开始。
  static const int keypointStart = 5;
}

/// 一个候选框（还没做 NMS）。
class PoseCandidate {
  PoseCandidate({
    required this.boxConfidence,
    required this.cx,
    required this.cy,
    required this.w,
    required this.h,
    required this.keypoints,
    this.areaFraction,
  });

  final double boxConfidence;

  /// 框参数。**与关键点同量纲：像素（0~inputSize）**。
  ///
  /// ⚠️ 这里踩过两次坑，都记下来：
  ///
  ///   ① 一开始以为框是 0~1 归一化的 —— 错了。
  ///      实测框宽在 21~72 之间，若是归一化就是 2100%~7200%，不可能。
  ///
  ///   ② 为确认量纲，做了个几何交叉验证：
  ///      从关键点算包围盒宽度，除以框宽，得到比值
  ///          w 比 0.690，h 比 0.668
  ///      比值接近 1（框比关键点包围盒略大是正常的，框含人体轮廓余量），
  ///      所以**框与关键点同量纲**。
  ///
  /// 这个坑的危险之处：算出来的"面积"是错的，但因为不会报错，
  /// 只会让选人判据失效 —— 表现为"每一帧都难以判断选谁"。
  final double cx, cy, w, h;

  /// 17 个关键点，坐标已**映射回原图的归一化坐标**。
  final List<Keypoint> keypoints;

  /// 框**占整幅原图的面积比例**（0~1）。由上层换算后填入。
  ///
  /// 为什么要单独一个字段而不是算 [w]×[h]：
  ///   [w] 和 [h] 是网络输入坐标系下的像素值，直接相乘得到的
  ///   不是"占画面多少"。要换算必须知道 letterbox 参数和原图尺寸 ——
  ///   那属于解析阶段的信息，不该让使用者自己再算一遍。
  final double? areaFraction;

  /// 占画面面积比例。没换算过时退回用像素值估算（仅用于排序，绝对值无意义）。
  double get area => areaFraction ?? (w * h);

  @override
  String toString() {
    final a = areaFraction;
    return 'PoseCandidate(conf=${boxConfidence.toStringAsFixed(3)}, '
        '${a == null ? "框=${w.toStringAsFixed(1)}×${h.toStringAsFixed(1)}px" : "占画面 ${(a * 100).toStringAsFixed(2)}%"}, '
        '${keypoints.length} 点)';
  }
}

/// 从 YOLO 的原始输出里解出所有候选。
///
/// 参数
/// ----
/// output : 形状 (1, 56, 8400) 的扁平数据，**按 [通道][候选] 排列**
/// lb : letterbox 参数，用于把坐标映射回原图
/// keypointCount : 关键点数量，默认 17
/// confThreshold : 低于此置信度的候选直接丢弃
///
/// 返回按置信度**从高到低**排序的候选列表。
///
/// ## 为什么要先按置信度筛
///
/// 8400 个候选里绝大多数是背景噪声（置信度 0.001 量级）。
/// 全留着会让后续排序变慢，而且它们的关键点坐标是没有意义的
/// —— 网络对"这里没有人"的位置照样会输出一组坐标。
List<PoseCandidate> parseYoloPose(
  Float32List output, {
  required Letterbox lb,
  int keypointCount = cocoKeypointCount,
  double confThreshold = 0.25,
}) {
  final channels = YoloPoseLayout.channels(keypointCount);
  final total = output.length;
  if (channels == 0 || total % channels != 0) {
    throw ArgumentError(
      '输出长度 $total 不是通道数 $channels 的整数倍 —— '
      '形状假设错了，请检查模型是否真的是 YOLO-pose 输出',
    );
  }
  final n = total ~/ channels;

  final out = <PoseCandidate>[];

  for (var i = 0; i < n; i++) {
    final conf = output[YoloPoseLayout.confidenceIndex * n + i];
    if (conf < confThreshold) continue;

    final cx = output[0 * n + i];
    final cy = output[1 * n + i];
    final w = output[2 * n + i];
    final h = output[3 * n + i];

    // 框的像素宽高 → 占原图的面积比例。
    //
    // 框和关键点同量纲（网络输入的像素），所以要先用同样的
    // letterbox 逆变换换算回原图，再除以原图尺寸。
    final wOrig = w / lb.scale / lb.originalWidth;
    final hOrig = h / lb.scale / lb.originalHeight;

    final kps = <Keypoint>[];
    for (var k = 0; k < keypointCount; k++) {
      final base = YoloPoseLayout.keypointStart + k * 3;
      final kx = output[(base + 0) * n + i];
      final ky = output[(base + 1) * n + i];
      final kc = output[(base + 2) * n + i];
      kps.add(Keypoint(
        x: lb.toOriginalX(kx),
        y: lb.toOriginalY(ky),
        confidence: kc,
      ));
    }

    out.add(PoseCandidate(
      boxConfidence: conf,
      cx: cx,
      cy: cy,
      w: w,
      h: h,
      keypoints: kps,
      areaFraction: wOrig * hOrig,
    ));
  }

  out.sort((a, b) => b.boxConfidence.compareTo(a.boxConfidence));
  return out;
}

/// 选人的判据权重。
///
/// ## 为什么不能只看置信度（实测踩到的坑）
///
/// 第一版用"取置信度最高的一个"。在操场的真实素材上，
/// 每帧检出 **6~21 个人**（背景有其他运动员、路人、远处的观众），
/// 而且 **4 帧全部存在歧义** —— 最高和次高的置信度差距小于 0.15。
///
/// 也就是说：那个"最高"很可能只是运气好，下一帧就换成别人了。
/// 更糟的是，训练场里背景的人可能**离镜头更近**，置信度天然更高。
///
/// ## 为什么"框更大"是可靠的判据
///
/// 拍摄标准要求运动员占画面高度的 1/3 以上。而背景的人
/// 要么更远（框更小），要么只是路过。所以**框最大的那个大概率是运动员**。
///
/// 这个判据还有一个好处：它和"拍摄质量"是同一件事 ——
/// 如果画面里最大的框也很小，那说明素材本身不合格，
/// 应当提示用户重拍，而不是硬选一个。
class PoseSelectionWeights {
  const PoseSelectionWeights({
    this.confidence = 1.0,
    this.area = 3.0,
  });

  /// 检出置信度的权重。
  final double confidence;

  /// 框面积的权重。
  ///
  /// 默认比置信度高 3 倍 —— 因为实测表明背景干扰很强，
  /// 而"占画面大"是运动员最稳定的特征。
  final double area;

  /// 综合得分。越大越可能是运动员。
  double score(PoseCandidate c) =>
      c.boxConfidence * confidence + c.area * area;
}

/// 从候选里选出要用的那一个人。
///
/// ## 评分方式
///
///     得分 = 置信度 × w₁ + 框面积 × w₂
///
/// 默认 w₁=1、w₂=3（见 [PoseSelectionWeights]）。面积权重更高，
/// 因为实测中背景干扰很强（一帧检出 21 个人），
/// 而"占画面大"是运动员最稳定的特征。
///
/// ## 为什么不做完整的 NMS
///
/// 完整 NMS 要比较所有候选两两之间的框重叠度，8400 个候选是
/// 7000 万次比较 —— 手机上太慢。而本项目是单人分析场景，
/// 直接选一个即可。
PoseCandidate? pickPrimary(
  List<PoseCandidate> candidates, {
  PoseSelectionWeights weights = const PoseSelectionWeights(),
}) {
  if (candidates.isEmpty) return null;
  if (candidates.length == 1) return candidates.first;

  var best = candidates.first;
  var bestScore = weights.score(best);
  for (final c in candidates.skip(1)) {
    final s = weights.score(c);
    if (s > bestScore) {
      best = c;
      bestScore = s;
    }
  }
  return best;
}

/// 选人的结果，附带"这次选得靠不靠谱"的判断。
class PoseSelection {
  const PoseSelection({
    required this.primary,
    required this.candidateCount,
    required this.isAmbiguous,
    required this.reason,
  });

  /// 选中的那个人。没有候选时为 null。
  final PoseCandidate? primary;

  /// 这一帧检出了几个候选。
  final int candidateCount;

  /// 是否存在歧义（前两名得分接近）。
  final bool isAmbiguous;

  /// 人话说明。用于界面提示与排查。
  final String reason;

  bool get ok => primary != null;
}

/// 带判断地选出这一帧的人。
///
/// 相比 [pickPrimary]，这个函数会**说明为什么这样选**，
/// 并在结果可疑时告诉上层。教练看到的应该是"可能选错了"的提示，
/// 而不是一个悄悄用错的骨架。
PoseSelection selectPerson(
  List<PoseCandidate> candidates, {
  PoseSelectionWeights weights = const PoseSelectionWeights(),
  double ambiguousRatio = 0.85,
}) {
  if (candidates.isEmpty) {
    return const PoseSelection(
      primary: null,
      candidateCount: 0,
      isAmbiguous: false,
      reason: '这一帧没有检出人',
    );
  }

  final scored = candidates
      .map((c) => (c, weights.score(c)))
      .toList()
    ..sort((a, b) => b.$2.compareTo(a.$2));

  final best = scored.first.$1;
  if (scored.length == 1) {
    return PoseSelection(
      primary: best,
      candidateCount: 1,
      isAmbiguous: false,
      reason: '画面里只有一个人',
    );
  }

  final second = scored[1];
  // 用**比值**而不是差值判断歧义。
  // 差值在不同量级下含义不同；比值是尺度无关的。
  final ratio = second.$2 / scored.first.$2;
  final ambiguous = ratio > ambiguousRatio;

  return PoseSelection(
    primary: best,
    candidateCount: candidates.length,
    isAmbiguous: ambiguous,
    reason: ambiguous
        ? '画面里检出 ${candidates.length} 个人，且前两名得分接近'
            '（比值 ${ratio.toStringAsFixed(2)}）—— **可能选错了人**。'
            '建议让拍摄者把镜头对准运动员，减少画面里的其他人。'
        : '画面里检出 ${candidates.length} 个人，'
            '选中了占画面最大的那个（得分是第二名的 '
            '${(1 / ratio).toStringAsFixed(1)} 倍）',
  );
}

/// 判断这一帧的选人是否**可能有歧义**（旧接口，保留兼容）。
bool isAmbiguous(List<PoseCandidate> candidates,
    {double ambiguousGap = 0.15}) {
  if (candidates.length < 2) return false;
  final gap = candidates[0].boxConfidence - candidates[1].boxConfidence;
  return gap < ambiguousGap;
}

/// 把候选转成 [PoseFrame]。
PoseFrame toPoseFrame(PoseCandidate c, int frameIndex) => PoseFrame(
      frameIndex: frameIndex,
      keypoints: c.keypoints,
      boxConfidence: c.boxConfidence,
    );
