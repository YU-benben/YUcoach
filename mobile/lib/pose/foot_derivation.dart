/// 足部点的几何推导。
///
/// ## 为什么需要它
///
/// COCO-17 **没有脚跟和脚尖**。而好几个指标需要它们：
///
///     胫骨角（着地）  = 小腿相对竖直的夹角  —— 只需要膝、踝
///     踝角（着地）    = ∠(膝, 踝, 脚尖)     —— **需要脚尖**
///     触地/离地判定    —— 需要足部位置
///
/// 而这两个点恰好是**本项目最大的精度短板**。
///
/// ## ⚠️ 局限（必须如实告知，不能藏着）
///
/// 真实足部姿态在步态周期内变化很大：
///
///     着地期   足部与小腿约 90°
///     蹬离期   踝关节跖屈可达 **120° 以上**
///
/// 而本推导**假定足部与小腿约呈 90°**，所以在蹬离期误差最大 ——
/// 而这个误差恰好落在最关键的触地/离地时刻附近。
///
/// **结论：推导出的足部点，位置不可用于精细分析。**
/// 要精确测量触地时间，必须用带足部关键点的模型（如 MediaPipe）。
///
/// ## 与电脑端的关系
///
/// 这是 `backend/analysis/keypoint_map.py` 的 `derive_foot_points` 的
/// Dart 版本，**用于绘制**。算法层的足部点仍由电脑端推导 ——
/// 手机端不参与指标计算，只把骨架画出来。
///
/// ⚠️ 但两边的**参数必须一致**，否则手机上画的脚尖位置
///    和电脑报告里算的不是同一个点。
library;

import 'dart:math' as math;

import 'pose_types.dart';

/// 人体测量学常数。**必须与电脑端 `keypoint_map.py` 一致。**
///
/// ⚠️ 这里踩过一次坑，值得记下来：
///
///     `heelBelowAnkleRatio` 我凭记忆写成了 **0.08**，
///     而电脑端是 **0.20**。
///
///     后果：角度全对（因为角度不依赖脚跟），但**脚跟的 y 坐标差了 0.0037**
///     —— 换算成画面就是几个像素。如果只看"角度对不对"，
///     这个错误完全看不出来。
///
///     是 `mobile/test/angle_parity_test.dart` 里**顺带验证足部点**
///     的那一段抓出来的。教训：对拍要覆盖**所有**两边各写了一遍的公式，
///     不能只比最终结论。
class FootConstants {
  const FootConstants._();

  /// 足长约占身高 15.2%。
  static const double footLengthRatio = 0.152;

  /// 脚尖在踝前约足长的 75%。
  static const double toeAheadAnkleRatio = 0.75;

  /// 足跟在踝后约足长的 25%。
  static const double heelBehindAnkleRatio = 0.25;

  /// 足跟在踝下约足长的 20%。
  ///
  /// ⚠️ 电脑端 `keypoint_map.py:78` 的值是 0.20。改动必须两边同步。
  static const double heelBelowAnkleRatio = 0.20;
}

/// 一对足部点。
class FootPoints {
  const FootPoints({required this.heel, required this.toe});

  final Keypoint heel;
  final Keypoint toe;
}

/// 估计足长（归一化坐标下的长度）。
///
/// 优先用人体的**头到最低踝**的距离近似身高 ——
/// 精度差一些，但总比给一个拍脑袋的常数好。
///
/// 电脑端还会优先用人体包围框高度（更准），但手机端拿到的
/// COCO-17 没有包围框信息（框在我们的数据结构里是候选级别的，
/// 不随姿态帧传下来），所以退回用头到踝。
double estimateFootLength(PoseFrame frame) {
  final nose = frame.byName('nose');
  if (nose == null || !nose.visible) {
    // 没有头就彻底没有尺度信息。给一个中等身材的典型值 ——
    // 上层会把结果标注为低置信。
    return 0.20 * FootConstants.footLengthRatio;
  }

  // 取最低那只踝（y 向下，所以取 y 较大的）
  double? lowestY;
  for (final name in ['ankle_l', 'ankle_r']) {
    final a = frame.byName(name);
    if (a == null || !a.visible) continue;
    lowestY = lowestY == null ? a.y : math.max(lowestY, a.y);
  }
  if (lowestY == null) {
    return 0.20 * FootConstants.footLengthRatio;
  }

  // ⚠️ 用鼻尖而不是真正的头顶。COCO-17 只有鼻尖，
  //    而鼻尖到脚底比身高短约 10%。所以这里**不做补偿** ——
  //    足长估小一点比估大了安全（画出来的脚不会超出画面）。
  final h = (lowestY - nose.y).abs();
  if (h <= 0.05) {
    return 0.20 * FootConstants.footLengthRatio;
  }
  return h * FootConstants.footLengthRatio;
}

/// 由踝与膝推导脚跟、脚尖。
///
/// ## 做法（与电脑端一致）
///
///   1. 取小腿方向（膝 → 踝）
///   2. 足部方向 = 小腿方向的**垂线**（即足部与小腿成 90°）
///   3. 在这条线上按人体测量学比例放脚尖与脚跟
///
/// ## ⚠️ 垂线有两个方向，必须选对
///
/// 垂线可以向"身体前方"也可以向"后方"，两者相差 180°。
/// 电脑端的判据是：**真实的足部在画面中总是低于或等于踝的高度**，
/// 脚尖不可能明显高于踝。
///
/// 这个判据看着粗糙但很可靠 —— 因为它基于重力，不依赖姿态估计。
///
/// 选错的后果：脚尖会画到踝的上方，看起来像"脚长到小腿上了"。
FootPoints? deriveFootPoints({
  required Keypoint ankle,
  Keypoint? knee,
  required double footScale,
}) {
  if (!ankle.visible) return null;
  if (footScale <= 1e-9) return null;

  final ax = ankle.x;
  final ay = ankle.y;

  double sx, sy;
  if (knee != null && knee.visible) {
    sx = ax - knee.x;
    sy = ay - knee.y;
    final norm = math.sqrt(sx * sx + sy * sy);
    if (norm > 1e-6) {
      sx /= norm;
      sy /= norm;
    } else {
      // 膝与踝重合（不该发生）——假定小腿竖直向下
      sx = 0.0;
      sy = 1.0;
    }
  } else {
    // 膝不可见：假定小腿竖直向下
    sx = 0.0;
    sy = 1.0;
  }

  // 垂线方向（两个候选）
  var px = -sy;
  var py = sx;

  // 选朝向"身体下方"的那一条。
  //
  // ⚠️ 这一步不能省。省掉的话，脚尖有一半概率画到踝的上方 ——
  //    而画错的图不会报错，看起来只是"这个模型不太准"。
  if (py < 0) {
    px = -px;
    py = -py;
  }

  final toe = Keypoint(
    x: ax + px * footScale * FootConstants.toeAheadAnkleRatio,
    y: ay + py * footScale * FootConstants.toeAheadAnkleRatio,
    // 推导点的置信度取踝的置信度 —— 它的可信度完全来自踝。
    // 不虚高：踝是 0.4 的话，推导出的脚尖不该报 0.9。
    confidence: ankle.confidence,
  );

  // 脚跟在小腿后方、略偏下。
  //
  // ⚠️ 这里的 `+ footScale * heelBelowAnkleRatio` 是往**下方**偏移。
  //    图像坐标 y 向下，所以加号才是"更低"。
  final heel = Keypoint(
    x: ax - px * footScale * FootConstants.heelBehindAnkleRatio,
    y: ay -
        py * footScale * FootConstants.heelBehindAnkleRatio +
        footScale * FootConstants.heelBelowAnkleRatio,
    confidence: ankle.confidence,
  );

  return FootPoints(heel: heel, toe: toe);
}

/// 给一帧补齐足部点，返回一个**扩展后的**姿态。
///
/// ## 为什么要单独一个函数而不是改 [PoseFrame]
///
/// [PoseFrame] 的 17 个点直接对应模型输出，是"原始测量值"。
/// 把推导点混进去会让"哪些是测的、哪些是推的"变模糊 ——
/// 而这个区分很重要（质量报告要分开统计）。
///
/// 所以推导点单独放在一个附加结构里，绘制时按需取用。
class DerivedFrame {
  const DerivedFrame({
    required this.frame,
    required this.heelLeft,
    required this.toeLeft,
    required this.heelRight,
    required this.toeRight,
  });

  final PoseFrame frame;
  final Keypoint? heelLeft;
  final Keypoint? toeLeft;
  final Keypoint? heelRight;
  final Keypoint? toeRight;

  /// 按名字取点。**优先返回模型直接输出的点**，推推导点作为补充。
  ///
  /// 这样调用方可以无差别地按名字取 —— 而"哪些是推的"这个信息
  /// 通过 [isDerived] 单独查询。
  Keypoint? byName(String name) {
    final direct = frame.byName(name);
    if (direct != null) return direct;
    return switch (name) {
      'heel_l' => heelLeft,
      'toe_l' => toeLeft,
      'heel_r' => heelRight,
      'toe_r' => toeRight,
      _ => null,
    };
  }

  /// 这个点是推导出来的吗。
  static bool isDerived(String name) => const {
        'heel_l', 'toe_l', 'heel_r', 'toe_r',
      }.contains(name);

  /// 有哪些足部点成功推导出来了。
  List<String> get availableFootPoints => [
        if (heelLeft != null) 'heel_l',
        if (toeLeft != null) 'toe_l',
        if (heelRight != null) 'heel_r',
        if (toeRight != null) 'toe_r',
      ];
}

/// 给一帧推导足部点。
DerivedFrame deriveFrame(PoseFrame frame) {
  final scale = estimateFootLength(frame);

  final lAnkle = frame.byName('ankle_l');
  final lKnee = frame.byName('knee_l');
  final rAnkle = frame.byName('ankle_r');
  final rKnee = frame.byName('knee_r');

  FootPoints? left;
  if (lAnkle != null && lAnkle.visible) {
    left = deriveFootPoints(
        ankle: lAnkle, knee: lKnee, footScale: scale);
  }

  FootPoints? right;
  if (rAnkle != null && rAnkle.visible) {
    right = deriveFootPoints(
        ankle: rAnkle, knee: rKnee, footScale: scale);
  }

  return DerivedFrame(
    frame: frame,
    heelLeft: left?.heel,
    toeLeft: left?.toe,
    heelRight: right?.heel,
    toeRight: right?.toe,
  );
}
