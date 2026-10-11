/// 步态事件与运动阶段的检测。
///
/// ## 为什么手机端也要做这件事
///
/// 「关键帧」不是随便挑几帧，而是**特定事件发生的那些帧**：
///
///     起跑那一帧   = 检出「第一次着地」
///     途中跑那一帧 = 检出「最高速度阶段」的支撑中期
///
/// 所以**要知道哪一帧是关键帧，必须先做事件检测**。
/// 这不是可选项 —— 它是出关键帧图的前提。
///
/// ## 与 Python 端的关系
///
/// 这里的实现对应 `backend/analysis/phases.py`，但**做了刻意的简化**：
///
///   Python 端：完整的相位划分（含速度曲线、断点检测）
///   手机端：  只检测事件 + 粗粒度阶段
///
/// 为什么可以简化：手机端的目标是**挑出关键帧给教练看**，
/// 而精确的指标计算在电脑端做。挑帧只需要知道"哪一帧是着地"，
/// 不需要知道"加速段在第 40 帧结束"这种精确边界。
///
/// ⚠️ 但**事件检测的口径必须和 Python 端一致** ——
///    否则手机挑的帧和电脑算的帧不是同一帧，
///    教练会看到图和数字对不上。
library;

import 'dart:math' as math;

import 'pose_types.dart';
import 'smoothing.dart';

/// 运动阶段。与契约的 Phase 枚举一致。
class PhaseName {
  const PhaseName._();

  static const set = 'set';
  static const start = 'start';
  static const acceleration = 'acceleration';
  static const transition = 'transition';
  static const maxVelocity = 'max_velocity';
  static const deceleration = 'deceleration';

  /// 中文名。用于界面显示。
  static String zh(String phase) => switch (phase) {
        set => '各就位',
        start => '起动',
        acceleration => '加速段',
        transition => '过渡',
        maxVelocity => '最高速度',
        deceleration => '减速',
        _ => phase,
      };
}

/// 一个运动阶段。
class PhaseSegment {
  const PhaseSegment({
    required this.phase,
    required this.fromFrame,
    required this.toFrame,
    this.confidence = 1.0,
  });

  final String phase;
  final int fromFrame;
  final int toFrame;
  final double confidence;

  bool contains(int frame) => frame >= fromFrame && frame <= toFrame;

  int get length => toFrame - fromFrame + 1;

  @override
  String toString() =>
      'PhaseSegment($phase, $fromFrame-$toFrame, conf=$confidence)';
}

/// 步态事件。
///
/// 与 Python 端的 `GaitEvents` 对应，但只保留手机端用得上的部分。
class GaitEvents {
  const GaitEvents({
    this.touchdowns = const [],
    this.midstances = const [],
    this.toeOffs = const [],
    this.method = '',
    this.reliability = '',
    this.notes = const [],
  });

  /// 着地帧号（按时间升序）。
  final List<int> touchdowns;

  /// 支撑中期帧号。
  final List<int> midstances;

  /// 离地帧号。
  final List<int> toeOffs;

  /// 检测方法。用于排查。
  final String method;

  /// 可靠性：good / fair / poor。
  final String reliability;

  /// 说明。为什么不可靠、缺什么。
  final List<String> notes;

  bool get isEmpty =>
      touchdowns.isEmpty && midstances.isEmpty && toeOffs.isEmpty;

  /// 检测到的步数（按着地次数算）。
  int get stepCount => touchdowns.length;

  @override
  String toString() => 'GaitEvents(${touchdowns.length} 次着地, '
      '${midstances.length} 次支撑中期, reliability=$reliability)';
}

/// 事件检测的配置。
class GaitDetectionConfig {
  const GaitDetectionConfig({
    this.minStepIntervalS = 0.12,
    this.smoothWindow = 5,
    this.minHipOscillation = 0.002,
  });

  /// 两步之间的最小间隔（秒）。
  ///
  /// 选手步频上限约 5 步/秒，所以两步至少间隔 0.2 秒。
  /// 取 0.12 是留了余量，同时能滤掉同一只脚在支撑期内的抖动。
  final double minStepIntervalS;

  /// 平滑窗口（帧）。
  final int smoothWindow;

  /// 髋部高度曲线的最小振幅。低于它说明没检出有效信号。
  ///
  /// 为什么需要这个判据：如果运动员在画面里几乎不动（或者模型没检到人），
  /// 髋高曲线是平的，任何极值检测都会产生一堆假事件。
  /// 实测踩过这个坑 —— 一条平曲线产生过 20 个假事件。
  final double minHipOscillation;
}

/// 检测步态事件。
///
/// ## 方法：用髋部高度曲线
///
/// 跑步时髋部高度是周期性起伏的：
///
///     支撑中期 → 髋部最低（身体被压缩）
///     腾空最高 → 髋部最高
///
/// 所以髋高曲线的**局部最低点**就是支撑中期，两次支撑中期之间是着地。
///
/// ## ⚠️ 为什么不用"脚着地"直接判
///
/// 因为**足部点不可靠** —— COCO-17 没有脚跟脚尖，
/// 我们是用小腿方向旋转 90° 几何推导的，蹬离瞬间误差最大。
/// 用不可靠的点判着地，会得到一堆假事件。
///
/// 髋部点（hip_l / hip_r）是模型的**直接输出**，比推导的足部点可靠得多。
/// 这也是 Python 端采用同样策略的原因。
GaitEvents detectGaitEvents(
  PoseSequence seq, {
  required double fps,
  GaitDetectionConfig config = const GaitDetectionConfig(),
}) {
  final notes = <String>[];

  if (seq.length < 10) {
    return GaitEvents(
      method: 'hip_height',
      reliability: 'poor',
      notes: ['帧数太少（${seq.length}），无法检测步态事件'],
    );
  }

  // ---- 1. 取髋部高度序列（用髋中心，比单个髋关节稳定）----
  final idxs = <int>[];
  final ys = <double>[];
  for (final f in seq.frames) {
    final l = f.byName('hip_l');
    final r = f.byName('hip_r');
    if (l == null || r == null) continue;
    if (!l.visible && !r.visible) continue;

    // 用可见的那个；两个都可见就取平均
    double y;
    if (l.visible && r.visible) {
      y = (l.y + r.y) / 2;
    } else if (l.visible) {
      y = l.y;
    } else {
      y = r.y;
    }
    idxs.add(f.frameIndex);
    ys.add(y);
  }

  if (ys.length < 10) {
    return GaitEvents(
      method: 'hip_height',
      reliability: 'poor',
      notes: ['可用的髋部点太少（${ys.length} 帧）'],
    );
  }

  // ---- 2. 平滑 ----
  //
  // 为什么要平滑：模型有约 3 像素的关键点抖动，
  // 而髋高曲线的起伏只有几像素 —— 不平滑的话抖动会淹没真实信号。
  final smooth = movingAverage(ys, config.smoothWindow);

  // ---- 3. 先看有没有信号 ----
  //
  // ⚠️ 这一步不能省。实测踩过坑：
  //    一条几乎平的曲线产生了 20 个假事件，
  //    因为它们都"满足局部极值的定义"。
  final amp = smooth.reduce(math.max) - smooth.reduce(math.min);
  if (amp < config.minHipOscillation) {
    return GaitEvents(
      method: 'hip_height',
      reliability: 'poor',
      notes: [
        '髋部高度几乎没有起伏（振幅 ${amp.toStringAsFixed(4)}），'
            '无法定位步态事件',
        '常见原因：运动员在画面里太小、被遮挡，或镜头跟随导致'
            '画面里的位置变化很小',
      ],
    );
  }

  // ---- 4. 找支撑中期（髋高局部最低点）----
  final minGap = math.max(2, (config.minStepIntervalS * fps).round());
  final mins = localExtrema(smooth, minGap, findMax: false);

  if (mins.isEmpty) {
    return GaitEvents(
      method: 'hip_height',
      reliability: 'poor',
      notes: ['找到了起伏但没定位到局部最低点 —— 信号可能不是周期性的'],
    );
  }

  // ---- 5. 由支撑中期推着地 ----
  //
  // 着地在支撑中期**之前**。支撑期通常占一个步周期的 40% 左右，
  // 所以着地大约在支撑中期前 40% 步周期处。
  //
  // ⚠️ 这是**推算**，不是直接测量。图上的"第 N 步"标签依赖它，
  //    所以要在报告里说明这一点。
  final medGap = _medianGap(mins);
  final halfStep = medGap ~/ 2;

  final touchdowns = <int>[];
  for (final m in mins) {
    final td = m - halfStep ~/ 1;   // 约半个支撑期之前
    if (td >= 0) touchdowns.add(td);
  }
  // 去重并排序
  final tdSorted = touchdowns.toSet().toList()..sort();

  // ---- 6. 由着地推离地 ----
  //
  // 离地在支撑中期**之后**，大约再半个支撑期。
  final toeOffs = <int>[];
  for (final m in mins) {
    final to = m + halfStep;
    if (to < seq.length) toeOffs.add(to);
  }
  toeOffs.sort();

  // ---- 7. 可靠性 ----
  //
  // 判据：检出的步数是否合理，以及信号的周期性是否明显。
  final durationS = seq.length / fps;
  final cadence = mins.length / durationS * 60;   // 步/分
  String reliability;
  if (cadence >= 150 && cadence <= 400 && mins.length >= 3) {
    reliability = 'good';
  } else if (mins.length >= 2) {
    reliability = 'fair';
    notes.add('检出 ${mins.length} 次支撑中期，'
        '换算步频 ${cadence.toStringAsFixed(0)} 步/分 —— '
        '不在常见的 150~400 范围内，事件位置可能不准');
  } else {
    reliability = 'poor';
    notes.add('只检出 ${mins.length} 次支撑中期，不足以定位步态');
  }

  notes.add('着地与离地位置由支撑中期**推算**得出'
      '（足部点为几何推导，不足以直接判定着地）');

  return GaitEvents(
    touchdowns: tdSorted,
    midstances: mins.map((i) => idxs[i]).toList(),
    toeOffs: toeOffs,
    method: 'hip_height',
    reliability: reliability,
    notes: notes,
  );
}

/// 由事件划分运动阶段。
///
/// ## 手机端的简化
///
/// Python 端用速度曲线的断点来划分阶段（含 initial/middle/final 三段）。
/// 手机端**不这么做**，因为：
///
///   1. 跟拍素材下"画面里的速度"是不可靠的（前面已确认）
///   2. 挑关键帧只需要知道"前几步是加速、后面是途中跑"
///
/// 所以这里按**步数**划分，这是稳的：起跑后前几步必然是加速，
/// 后面的步是途中跑。
List<PhaseSegment> detectPhases(
  PoseSequence seq, {
  required double fps,
  required GaitEvents events,
  int accelerationSteps = 5,
}) {
  if (events.touchdowns.isEmpty) return [];

  final tds = events.touchdowns;
  final last = seq.frames.last.frameIndex;

  final out = <PhaseSegment>[];

  // 起动段：第一帧到第一次着地
  if (tds.first > 0) {
    out.add(PhaseSegment(
      phase: PhaseName.start,
      fromFrame: seq.frames.first.frameIndex,
      toFrame: tds.first - 1,
      confidence: 0.6,
    ));
  }

  // 加速段：前 N 步
  final accelEndIdx =
      math.min(accelerationSteps, tds.length) - 1;
  if (accelEndIdx >= 0) {
    final accelEnd = tds.length > accelerationSteps
        ? tds[accelerationSteps] - 1
        : last;
    out.add(PhaseSegment(
      phase: PhaseName.acceleration,
      fromFrame: tds.first,
      toFrame: accelEnd,
      // 按步数划分是**启发式**，不如按速度曲线精确。
      // 置信度调低，让上层知道这个边界是估的。
      confidence: 0.7,
    ));

    // 途中跑：剩下的
    if (accelEnd < last) {
      out.add(PhaseSegment(
        phase: PhaseName.maxVelocity,
        fromFrame: accelEnd + 1,
        toFrame: last,
        confidence: 0.6,
      ));
    }
  }

  return out;
}

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

/// 找局部极值，带最小间隔约束。
///
/// ## 为什么需要最小间隔
///
/// 一条带噪声的曲线会有很多"局部极值"。不加约束的话，
/// 相邻几个像素的抖动都会被当成一个事件。
///
/// [minGap] 保证两个极值之间至少隔这么多采样点。
/// 冲突时**保留更极端的那个**。
///
/// ## 平台期怎么处理
///
/// 如果几个连续点数值相同（浮点运算很常见），按 `>=` 判断会让
/// 它们**全都**成为候选，而选哪个取决于排序稳定性 —— 这是不确定的。
/// 所以先把平台期**合并到中心点**，再做极值判断。
List<int> localExtrema(
  List<double> z,
  int minGap, {
  required bool findMax,
}) {
  if (z.length < 3) return [];

  // ---- 合并平台期 ----
  final collapsed = <int>[];   // 原始索引
  final values = <double>[];
  var i = 0;
  while (i < z.length) {
    var j = i;
    while (j + 1 < z.length && z[j + 1] == z[i]) {
      j++;
    }
    // 平台期的中心
    collapsed.add((i + j) ~/ 2);
    values.add(z[i]);
    i = j + 1;
  }

  // ---- 找候选 ----
  final cands = <int>[];
  for (var k = 1; k < values.length - 1; k++) {
    final a = values[k - 1], b = values[k], c = values[k + 1];
    final isExt = findMax ? (b >= a && b >= c) : (b <= a && b <= c);
    if (isExt) cands.add(collapsed[k]);
  }

  if (cands.isEmpty) return [];

  // ---- 按极端程度排序，再按最小间隔贪心挑选 ----
  //
  // 为什么用"贪心"而不是"直接按顺序过滤"：
  //   按顺序过滤时，先遇到的（不一定是最极端的）会被保留，
  //   结果会偏向曲线的早期部分。
  //   按极端程度排序能保证每个区间内留下的是最有代表性的那一个。
  final sorted = cands.toList()
    ..sort((a, b) => findMax
        ? z[b].compareTo(z[a])
        : z[a].compareTo(z[b]));

  final kept = <int>[];
  for (final c in sorted) {
    if (kept.any((k) => (k - c).abs() < minGap)) continue;
    kept.add(c);
  }
  kept.sort();
  return kept;
}

/// 相邻极值的间隔中位数。
int _medianGap(List<int> sorted) {
  if (sorted.length < 2) return 10;
  final gaps = <int>[];
  for (var i = 1; i < sorted.length; i++) {
    gaps.add(sorted[i] - sorted[i - 1]);
  }
  gaps.sort();
  return gaps[gaps.length ~/ 2];
}
