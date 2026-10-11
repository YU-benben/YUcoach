/// 关键帧选择（手机端）。
///
/// ## 什么是"关键帧"
///
/// 不是随便挑几帧，而是**特定事件发生的那些帧**：
///
///     起跑那一帧    = 检出「第一次着地」
///     途中跑那一帧  = 检出「最高速度阶段」的支撑中期
///
/// 所以要知道哪一帧是关键帧，必须先做事件检测
/// （见 [detectGaitEvents]）—— 这不是可选项。
///
/// ## 与电脑端的关系
///
/// 电脑端的 `backend/analysis/keyframes.py` 也做同样的事，但：
///   · 它会**渲染成 JPEG** 并写进报告的 `keyframes` 字段
///   · 手机端只挑帧，渲染交给 Flutter
///
/// 两边挑帧的**策略**要尽量一致，否则教练会看到"手机上 6 张、
/// 电脑上 4 张"这种不一致。但不要求逐帧相同 ——
/// 因为手机端的相位划分本来就是简化的（按步数而非速度曲线）。
library;

import 'dart:math' as math;

import 'gait_events.dart';
import 'pose_types.dart';

/// 一个被选中的关键帧。
class KeyframeSelection {
  const KeyframeSelection({
    required this.frameIndex,
    required this.event,
    required this.phase,
    required this.reason,
    this.stepIndex,
  });

  /// 帧号。
  final int frameIndex;

  /// 事件类型。与契约的 Event 枚举一致。
  final String event;

  /// 所属运动阶段。
  final String phase;

  /// 第几步。null 表示推不出来。
  final int? stepIndex;

  /// 为什么选这一帧。**必须给出人话解释** ——
  /// 教练看到一张图会问"为什么是这一张"。
  final String reason;

  @override
  String toString() =>
      'KeyframeSelection(#$frameIndex, $event, $phase, 第$stepIndex步)';
}

/// 事件名。与契约的 Event 枚举一致。
class EventName {
  const EventName._();

  static const setPosition = 'set_position';
  static const gunFire = 'gun_fire';
  static const blockClearance = 'block_clearance';
  static const touchdown = 'touchdown';
  static const midstance = 'midstance';
  static const toeOff = 'toe_off';
  static const swingPeak = 'swing_peak';
  static const finish = 'finish';

  static String zh(String e) => switch (e) {
        setPosition => '各就位',
        gunFire => '枪响',
        blockClearance => '离器',
        touchdown => '着地',
        midstance => '支撑中期',
        toeOff => '离地',
        swingPeak => '摆动最高',
        finish => '冲线',
        _ => e,
      };
}

/// 选帧的配置。
class KeyframeConfig {
  const KeyframeConfig({
    this.maxKeyframes = 6,
    this.minGapFrames = 8,
  });

  /// 最多选几帧。
  ///
  /// 为什么要上限：一场跑动有十几步，全画出来教练看不过来，
  /// 而且手机端渲染每一帧都要从视频取图（有开销）。
  final int maxKeyframes;

  /// 同一阶段内两帧的最小间隔。
  ///
  /// 太近的两帧画出来几乎一样，浪费一个宝贵的名额。
  final int minGapFrames;
}

/// 挑出关键帧。
///
/// ## 策略：按阶段分组，每组选"人最大"的那一帧
///
/// 为什么按**阶段**而不是按**步**：
///   一次跑动有十几步，每步都画会有十几张几乎相同的图。
///   教练真正关心的是**不同阶段**的姿态差异 ——
///   起跑什么样、加速期什么样、途中跑什么样。
///
/// 为什么同一阶段内选"人最大"的：
///   实测踩过坑：第一版按"阶段内时间均匀"选，结果选中了
///   运动员蹲着、被前方人挡住的那一帧 —— 而那帧在信息量上
///   恰恰是最差的，教练什么都看不出来。
///
///   "占画面大"是拍摄标准的要求，也是关键点质量最直接的代理指标。
List<KeyframeSelection> selectKeyframes(
  PoseSequence seq,
  List<PhaseSegment> phases, {
  GaitEvents? events,
  Map<int, double> personHeights = const {},
  KeyframeConfig config = const KeyframeConfig(),
}) {
  if (seq.isEmpty) return [];

  // ---- 1. 候选：所有事件帧 ----
  final cands = <(int, String)>[];
  if (events != null) {
    for (final f in events.touchdowns) {
      cands.add((f, EventName.touchdown));
    }
    for (final f in events.midstances) {
      cands.add((f, EventName.midstance));
    }
    for (final f in events.toeOffs) {
      cands.add((f, EventName.toeOff));
    }
  }
  if (cands.isEmpty) return [];

  // ---- 2. 按阶段分组 ----
  final byPhase = <String, List<(int, String)>>{};
  for (final (f, e) in cands) {
    final ph = _phaseOf(phases, f);
    if (ph == null) continue;
    byPhase.putIfAbsent(ph, () => []).add((f, e));
  }
  if (byPhase.isEmpty) return [];

  // ---- 3. 各阶段想选几帧 ----
  //
  // 加速段看两次（起步 + 中段），因为加速期姿态变化最大。
  const want = {
    PhaseName.acceleration: 3,
    PhaseName.maxVelocity: 2,
    PhaseName.start: 1,
    PhaseName.transition: 1,
    PhaseName.deceleration: 1,
  };

  // 阶段优先级：起跑和加速最需要看
  const priority = [
    PhaseName.acceleration,
    PhaseName.maxVelocity,
    PhaseName.start,
    PhaseName.transition,
    PhaseName.deceleration,
  ];

  final picked = <(int, String, String)>[];

  for (final ph in priority) {
    final items = byPhase[ph];
    if (items == null || items.isEmpty) continue;

    final n = want[ph] ?? 1;
    final chosen = _pickBest(items, n, personHeights, config.minGapFrames);
    for (final (f, e) in chosen) {
      picked.add((f, e, ph));
    }
  }

  // ---- 4. 排序 + 封顶 ----
  picked.sort((a, b) => a.$1.compareTo(b.$1));
  final limited = picked.length > config.maxKeyframes
      ? picked.sublist(0, config.maxKeyframes)
      : picked;

  // ---- 5. 组装 ----
  final tds = events?.touchdowns ?? const <int>[];

  return limited.map((t) {
    final (frame, event, phase) = t;
    return KeyframeSelection(
      frameIndex: frame,
      event: event,
      phase: phase,
      stepIndex: _stepIndexAt(tds, frame),
      reason: _explain(event, phase),
    );
  }).toList();
}

/// 这一帧属于哪个阶段。找不到返回 null。
String? _phaseOf(List<PhaseSegment> phases, int frame) {
  for (final p in phases) {
    if (p.contains(frame)) return p.phase;
  }
  return null;
}

/// 这是第几步。着地次数即步数。
int? _stepIndexAt(List<int> touchdowns, int frame) {
  if (touchdowns.isEmpty) return null;
  final n = touchdowns.where((t) => t <= frame).length;
  return n > 0 ? n : null;
}

/// 在一组候选里挑 n 帧：优先清晰的，再照顾时间分布。
///
/// ## 为什么两步走
///
/// 只按"人最大"取，可能几帧全挤在同一时刻；
/// 只按时间取，又会选中看不清的帧。两步兼顾。
///
/// 没有人物高度信息时（`personHeights` 为空）退回纯时间均匀 ——
/// 这是**诚实降级**：宁可选得普通，也不要凭一个不存在的判据乱选。
List<(int, String)> _pickBest(
  List<(int, String)> items,
  int n,
  Map<int, double> heights,
  int minGap,
) {
  if (items.length <= n) return List.of(items);

  List<(int, String)> pool;

  if (heights.isEmpty) {
    pool = List.of(items);
  } else {
    // 按人物大小排序，取前 2n 个作候选池
    final scored = List.of(items)
      ..sort((a, b) => (heights[b.$1] ?? 0).compareTo(heights[a.$1] ?? 0));
    pool = scored.take(math.max(n * 2, n)).toList()
      ..sort((a, b) => a.$1.compareTo(b.$1));
  }

  // 在候选池里按时间均匀取 n 个，并保证最小间隔
  final out = <(int, String)>[];
  final step = (pool.length - 1) / math.max(n - 1, 1);
  final wanted = <int>{};
  for (var i = 0; i < n; i++) {
    wanted.add((i * step).round().clamp(0, pool.length - 1));
  }

  for (final i in wanted.toList()..sort()) {
    final cand = pool[i];
    if (out.any((o) => (o.$1 - cand.$1).abs() < minGap)) continue;
    out.add(cand);
  }

  // 均匀取样被间隔约束挤掉太多时，按顺序补齐
  if (out.length < n) {
    for (final cand in pool) {
      if (out.length >= n) break;
      if (out.any((o) => o.$1 == cand.$1)) continue;
      if (out.any((o) => (o.$1 - cand.$1).abs() < minGap)) continue;
      out.add(cand);
    }
  }

  out.sort((a, b) => a.$1.compareTo(b.$1));
  return out;
}

/// 为什么选这一帧 —— 给教练看的解释。
///
/// 不写的话，教练看到一张图会问"为什么是这一张"。
String _explain(String event, String phase) {
  final phaseZh = PhaseName.zh(phase);
  return switch (event) {
    EventName.touchdown => '$phaseZh的着地瞬间。看落地点和缓冲。',
    EventName.midstance => '$phaseZh的支撑中期。身体被压缩最大的时刻。',
    EventName.toeOff => '$phaseZh的离地瞬间。看蹬伸是否充分。',
    _ => phaseZh,
  };
}
