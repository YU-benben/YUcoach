/// 可标注角度的目录。
///
/// ## ⚠️ 先读这段：这里的角度计算与"指标计算"是什么关系
///
/// 项目有一条原则：**指标算法只有一份**（在电脑端 `metrics.py`）。
/// 手机端不做指标计算 —— 这是为了避免两套实现慢慢漂移。
///
/// 但**要画出角度弧，手机端就必须自己算角度**。弧的形状依赖角度值，
/// 而等电脑端把数值传回来再画，用户就要盯着空画面等。
///
/// 所以这里划清了界限：
///
/// ```
/// 手机端算角度  →  只用于【画弧】。用户拖时间轴时能立刻看到角度变化。
/// 电脑端算角度  →  报告里的数值。有相位、有标准值、有规则判定。
/// ```
///
/// **不冲突的原因**：两边的输入是同一份关键点，公式也是同一套。
/// 而"报告以电脑端为准"这条不变 —— 手机端算的数从不出现在报告里。
///
/// 为了确保两边真的一致，`mobile/test/angle_parity_test.dart` 会用
/// 同一份关键点做对拍。
///
/// ## 公式来源
///
/// 全部对应 `backend/analysis/metrics_base.py`：
///
///     angle_at(a, b, c)               ∠ABC，b 是顶点，返回 0–180
///     segment_angle_from_vertical()   线段相对竖直的夹角
library;

import 'dart:math' as math;

import 'foot_derivation.dart';

/// 角度的类型。
enum AngleKind {
  /// 三点角 ∠ABC，b 是顶点。
  threePoint,

  /// 线段相对**竖直方向**的夹角。
  ///
  /// 短跑里胫骨角、躯干前倾角的行业惯例都是以竖直为基准。
  segmentFromVertical,
}

/// 一个可标注的角度。
class AngleDefinition {
  const AngleDefinition({
    required this.metricId,
    required this.nameZh,
    required this.kind,
    required this.points,
    required this.vertexIndex,
    required this.views,
    required this.side,
    this.derived = false,
    this.description = '',
  });

  /// 与契约的 metric_id 对应。**必须和电脑端一致**，
  /// 否则手机上标的角在报告里找不到对应项。
  final String metricId;

  /// 中文名。
  final String nameZh;

  final AngleKind kind;

  /// 参与计算的点名（顺序有意义）。
  final List<String> points;

  /// 顶点在 [points] 里的下标。只有 [AngleKind.threePoint] 用。
  final int vertexIndex;

  /// 适用于哪些视角。**跨视角混用会让几何量完全变味。**
  final List<String> views;

  /// 用哪一侧的点。'L' / 'R' / 'both'。
  ///
  /// 侧面拍摄时只有朝向镜头的那一侧可靠，所以侧面指标固定用右侧。
  final String side;

  /// 是否用到了推导点（足部点）。
  ///
  /// 用到的会在界面上标注"推导值" —— 因为它的误差明显更大。
  final bool derived;

  /// 一句话说明这个角度看什么。
  final String description;
}

/// 全部可标注的角度。
///
/// ## 要点
///
///   · `points` 里的点必须能用 [DerivedFrame.byName] 取到
///   · 侧面指标固定用 `_r`（右侧）—— 与电脑端 `angle_at` 的调用一致
///   · 额状面指标（正面/背面）用左右两侧的点
const List<AngleDefinition> angleCatalog = [
  // ======================== 侧面（矢状面）========================

  AngleDefinition(
    metricId: 'trunk_lean',
    nameZh: '躯干前倾',
    kind: AngleKind.segmentFromVertical,
    // ⚠️ 电脑端用的是 neck → pelvis_center。COCO-17 没有这两个点，
    //    手机端用 shoulder_center 的等价物：双肩中点 → 双髋中点。
    //    两者在人体上很接近（都在躯干线上），差异远小于测量误差。
    points: ['shoulder_mid', 'hip_mid'],
    vertexIndex: 0,
    views: ['side'],
    side: 'both',
    description: '躯干相对竖直的前倾角。加速段前倾大，途中跑接近直立。',
  ),

  AngleDefinition(
    metricId: 'knee_angle_touchdown',
    nameZh: '着地膝角',
    kind: AngleKind.threePoint,
    points: ['hip_r', 'knee_r', 'ankle_r'],
    vertexIndex: 1,
    views: ['side'],
    side: 'R',
    description: '着地瞬间大腿与小腿的夹角。太小说明缓冲过多、蹬伸不充分。',
  ),

  AngleDefinition(
    metricId: 'knee_angle_midstance',
    nameZh: '支撑中期膝角',
    kind: AngleKind.threePoint,
    points: ['hip_r', 'knee_r', 'ankle_r'],
    vertexIndex: 1,
    views: ['side'],
    side: 'R',
    description: '支撑中期身体被压缩最大的时刻。',
  ),

  AngleDefinition(
    metricId: 'hip_angle_toeoff',
    nameZh: '离地髋角',
    kind: AngleKind.threePoint,
    points: ['shoulder_r', 'hip_r', 'knee_r'],
    vertexIndex: 1,
    views: ['side'],
    side: 'R',
    description: '离地瞬间躯干与大腿的夹角。偏小说明髋伸展不充分。',
  ),

  AngleDefinition(
    metricId: 'shank_angle_touchdown',
    nameZh: '着地胫骨角',
    kind: AngleKind.segmentFromVertical,
    points: ['knee_r', 'ankle_r'],
    vertexIndex: 0,
    views: ['side'],
    side: 'R',
    description: '着地时小腿相对竖直的夹角。偏大说明着地点在重心前方更远，制动更多。',
  ),

  AngleDefinition(
    metricId: 'ankle_angle_touchdown',
    nameZh: '着地踝角',
    kind: AngleKind.threePoint,
    points: ['knee_r', 'ankle_r', 'toe_r'],
    vertexIndex: 1,
    views: ['side'],
    side: 'R',
    // ⚠️ 用到脚尖 —— 那是**推导点**，蹬离期误差最大。
    derived: true,
    description: '（脚部点为几何推导，精度有限）',
  ),

  // ======================== 正面 / 背面（额状面）========================

  AngleDefinition(
    metricId: 'pelvis_tilt',
    nameZh: '骨盆倾斜',
    kind: AngleKind.segmentFromVertical,
    points: ['hip_l', 'hip_r'],
    vertexIndex: 0,
    views: ['front', 'back'],
    side: 'both',
    description: '左右髋的高度差。偏大说明支撑侧骨盆下沉。',
  ),

  AngleDefinition(
    metricId: 'knee_valgus_touchdown',
    nameZh: '着地膝内扣',
    kind: AngleKind.threePoint,
    points: ['hip_r', 'knee_r', 'ankle_r'],
    vertexIndex: 1,
    views: ['front', 'back'],
    side: 'R',
    description: '着地时膝关节向内偏移。膝内扣是常见的损伤风险因素。',
  ),

  AngleDefinition(
    metricId: 'trunk_lateral_lean',
    nameZh: '躯干侧倾',
    kind: AngleKind.segmentFromVertical,
    points: ['shoulder_mid', 'hip_mid'],
    vertexIndex: 0,
    views: ['front', 'back'],
    side: 'both',
    description: '躯干左右方向的倾斜。',
  ),
];

/// 侧面拍摄时用哪些。
List<AngleDefinition> anglesForView(String view) =>
    angleCatalog.where((a) => a.views.contains(view)).toList();

/// 按 metric_id 找定义。
AngleDefinition? angleById(String metricId) {
  for (final a in angleCatalog) {
    if (a.metricId == metricId) return a;
  }
  return null;
}

// ---------------------------------------------------------------------------
// 计算
// ---------------------------------------------------------------------------

/// 求 ∠ABC，返回 0–180 度。b 是顶点。
///
/// ## 为什么用 atan2 而不是 arccos(点积)
///
/// 电脑端的注释已经说清了：点积法在角度接近 0° 或 180° 时数值不稳定
/// （浮点误差可能让 |cos| 略大于 1 从而抛 domain error）。
///
/// **这里必须用和电脑端相同的方法** —— 不同方法在边界附近会给出
/// 不同的结果，对拍就会失败。
double angleAt(
  (double, double) a,
  (double, double) b,
  (double, double) c,
) {
  final v1x = a.$1 - b.$1, v1y = a.$2 - b.$2;
  final v2x = c.$1 - b.$1, v2y = c.$2 - b.$2;

  final n1 = math.sqrt(v1x * v1x + v1y * v1y);
  final n2 = math.sqrt(v2x * v2x + v2y * v2y);
  if (n1 < 1e-9 || n2 < 1e-9) return double.nan;

  final cross = v1x * v2y - v1y * v2x;
  final dot = v1x * v2x + v1y * v2y;
  return (math.atan2(cross, dot).abs()) * 180 / math.pi;
}

/// 线段相对**竖直方向**的夹角。
///
/// 图像坐标 y 轴向下，所以"竖直"是 (0, 1)。
/// 返回带符号的值：正表示偏向画面右侧，负表示偏向左侧。
///
/// **调用方按需取绝对值** —— 与电脑端一致。
double segmentAngleFromVertical(
  (double, double) top,
  (double, double) bottom,
) {
  final dx = bottom.$1 - top.$1;
  final dy = bottom.$2 - top.$2;
  if (dx.abs() < 1e-9 && dy.abs() < 1e-9) return double.nan;
  return math.atan2(dx, dy) * 180 / math.pi;
}

/// 计算某一帧上某个角度的值。
///
/// 返回 null 表示算不出来（点不可见、退化几何等）。
///
/// ## 特殊点名
///
/// `shoulder_mid` / `hip_mid` 是**运行时算出来的中点**，
/// 不是关键点。加它们是因为：
///   · 电脑端的躯干角用 `neck → pelvis_center`
///   · COCO-17 没有这两个点，但有双肩和双髋
///   · 取中点是最接近的等价物
double? computeAngle(
  AngleDefinition def,
  DerivedFrame derived,
) {
  // ---- 解析点坐标 ----
  final pts = <(double, double)>[];
  for (final name in def.points) {
    final p = _resolvePoint(name, derived);
    if (p == null) return null;
    pts.add(p);
  }

  if (pts.length < 2) return null;

  switch (def.kind) {
    case AngleKind.threePoint:
      if (pts.length < 3) return null;
      final v = angleAt(pts[0], pts[1], pts[2]);
      return v.isNaN ? null : v;

    case AngleKind.segmentFromVertical:
      // 相对竖直的角取**绝对值** —— 画弧不关心偏哪边，
      // 而指标定义里也是按绝对值用的（躯干前倾、胫骨角都是）。
      final v = segmentAngleFromVertical(pts[0], pts[1]);
      return v.isNaN ? null : v.abs();
  }
}

/// 解析点名到坐标。支持运行时算出的中点。
(double, double)? _resolvePoint(String name, DerivedFrame d) {
  switch (name) {
    case 'shoulder_mid':
      final l = d.frame.byName('shoulder_l');
      final r = d.frame.byName('shoulder_r');
      if (l == null || r == null || !l.visible || !r.visible) return null;
      return ((l.x + r.x) / 2, (l.y + r.y) / 2);

    case 'hip_mid':
      final l = d.frame.byName('hip_l');
      final r = d.frame.byName('hip_r');
      if (l == null || r == null || !l.visible || !r.visible) return null;
      return ((l.x + r.x) / 2, (l.y + r.y) / 2);

    default:
      final kp = d.byName(name);
      if (kp == null || !kp.visible) return null;
      return (kp.x, kp.y);
  }
}

/// 这个角度在画布上画弧需要的三个点：起点、顶点、终点。
///
/// ## 为什么顶点不一定在中间
///
/// `segmentFromVertical` 类型（躯干前倾、胫骨角）只有两个真实点：
/// 线段的上下端。但画弧需要一个顶点和两条边。
///
/// 做法是**造一条竖直参考线**：从段的顶端向下画一条竖直虚线，
/// 弧就画在真实线段和这条虚线之间。这正好体现了"相对竖直"的含义 ——
/// 而且比只画一条弧更容易理解。
///
/// ## 返回值的含义
///
///   `(起点, 顶点, 终点)` —— 弧从"起点→顶点"这条边扫到"顶点→终点"这条边。
///   `null` 表示算不出来。
///
/// 对 `segmentFromVertical` 类型，额外返回一个 `isReferenceEdge`，
/// 告诉绘制方"顶点→终点这条边是参考线，要画成虚线"。
AngleArcPoints? arcPointsFor(
  AngleDefinition def,
  DerivedFrame derived,
) {
  final pts = <(double, double)>[];
  for (final name in def.points) {
    final p = _resolvePoint(name, derived);
    if (p == null) return null;
    pts.add(p);
  }
  if (pts.length < 2) return null;

  switch (def.kind) {
    case AngleKind.threePoint:
      if (pts.length < 3) return null;
      return AngleArcPoints(
        from: pts[0],
        vertex: pts[1],
        to: pts[2],
        referenceEdgeIsEnd: false,
      );

    case AngleKind.segmentFromVertical:
      // 段的顶端作顶点，另一端作"起点"。
      //
      // ⚠️ 竖直参考线的方向要和段的实际方向一致 ——
      //    否则弧会画在 180° 那一侧，看起来角度完全不对。
      //
      //    做法：取段的 dy 符号。dy 为正（段向下）时参考线也向下。
      final top = pts[0];
      final bottom = pts[1];
      final dy = bottom.$2 - top.$2;
      final sign = dy >= 0 ? 1.0 : -1.0;
      // 参考线长度取段长 —— 太短弧会挤在一起，太长会超出画面。
      final len = math.sqrt(
          math.pow(bottom.$1 - top.$1, 2) + math.pow(bottom.$2 - top.$2, 2));
      final ref = (top.$1, top.$2 + len * sign);

      return AngleArcPoints(
        from: bottom,
        vertex: top,
        to: ref,
        referenceEdgeIsEnd: true,
      );
  }
}

/// 画一个角度弧需要的三个点。
class AngleArcPoints {
  const AngleArcPoints({
    required this.from,
    required this.vertex,
    required this.to,
    required this.referenceEdgeIsEnd,
  });

  /// 一条边的端点。
  final (double, double) from;

  /// 顶点（弧心）。
  final (double, double) vertex;

  /// 另一条边的端点。
  final (double, double) to;

  /// `vertex → to` 这条边是不是**参考线**（竖直方向）。
  ///
  /// 是的话要画成虚线 —— 提醒教练"这条线不是身体的一部分"。
  final bool referenceEdgeIsEnd;
}
