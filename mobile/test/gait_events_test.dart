import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/gait_events.dart';
import 'package:yu_coach/pose/pose_types.dart';
import 'package:yu_coach/pose/smoothing.dart';

/// 步态事件检测的测试。
///
/// ## 为什么这组测试重要
///
/// 关键帧是**按事件挑的**：起跑那一帧 = 第一次着地。
/// 事件检测错了，挑出来的关键帧就是错的 ——
/// 而教练看到"这是起跑姿势"的标签配着一张中途跑的图，
/// 会以为系统坏了。
void main() {
  /// 造一段有周期性髋部起伏的姿态序列。
  ///
  /// [periodFrames] 一个步态周期的帧数。
  /// 髋高用余弦，最低点在每个周期的中点。
  PoseSequence makeSeq({
    required int frames,
    required int periodFrames,
    double amplitude = 0.03,
    double baseY = 0.5,
  }) {
    final out = <PoseFrame>[];
    for (var i = 0; i < frames; i++) {
      final phase = 2 * math.pi * i / periodFrames;
      // 髋部最低点出现在 cos = 1 处
      final y = baseY + amplitude * math.cos(phase);
      final kps = List.generate(17, (k) {
        if (k == 11 || k == 12) {
          // hip_l / hip_r
          return Keypoint(x: 0.5, y: y, confidence: 0.9);
        }
        return Keypoint(x: 0.4 + k * 0.005, y: 0.5, confidence: 0.9);
      });
      out.add(PoseFrame(frameIndex: i, keypoints: kps));
    }
    return PoseSequence(frames: out, sourceWidth: 960, sourceHeight: 540);
  }

  // -------------------------------------------------------------------------
  group('平滑', () {
    test('滑动平均不改变长度', () {
      final x = List.generate(20, (i) => i.toDouble());
      expect(movingAverage(x, 5).length, 20);
    });

    test('滑动平均让曲线更平滑（二阶差分变小）', () {
      final rnd = math.Random(1);
      final noisy = List.generate(100, (_) => rnd.nextDouble());
      final smooth = movingAverage(noisy, 9);

      double roughness(List<double> v) {
        var s = 0.0;
        for (var i = 1; i < v.length - 1; i++) {
          s += (v[i + 1] - 2 * v[i] + v[i - 1]).abs();
        }
        return s;
      }

      expect(roughness(smooth), lessThan(roughness(noisy)),
          reason: '平滑后应当更光滑');
    });

    test('常数序列平滑后不变', () {
      final x = List.filled(30, 0.42);
      for (final v in movingAverage(x, 7)) {
        expect(v, closeTo(0.42, 1e-12));
      }
    });

    test('线性序列平滑后仍是同一线性（中段不偏移）', () {
      // ⚠️ 这条防的是"平滑引入系统性偏移"。
      //    对称窗口对线性数据是保号的；如果边界处理不对称，中段会偏。
      final x = List.generate(50, (i) => i * 2.0);
      final s = movingAverage(x, 7);
      for (var i = 10; i < 40; i++) {
        expect(s[i], closeTo(x[i], 1e-9),
            reason: '第 $i 点被平滑偏移了 —— 窗口不对称');
      }
    });

    test('窗口大于数据长度时不崩', () {
      final x = [1.0, 2.0, 3.0];
      expect(() => movingAverage(x, 99), returnsNormally);
      expect(movingAverage(x, 99).length, 3);
    });

    test('中值滤波能滤掉单个离群值', () {
      // 一个飞到画面外的关键点会把平均值拉偏，但不影响中位数。
      final x = List.filled(21, 0.5);
      x[10] = 99.0;
      final m = medianFilter(x, 5);
      expect(m[10], closeTo(0.5, 1e-9), reason: '离群值应当被滤掉');

      final avg = movingAverage(x, 5);
      expect(avg[10], greaterThan(0.5),
          reason: '滑动平均会被离群值拉偏 —— 这正是中值滤波的价值');
    });

    test('差分对线性序列给出常数斜率', () {
      final y = List.generate(20, (i) => 3.0 * i);
      final d = gradient(y, 1.0);
      for (var i = 1; i < y.length - 1; i++) {
        expect(d[i], closeTo(3.0, 1e-9));
      }
    });
  });

  // -------------------------------------------------------------------------
  group('局部极值', () {
    test('找简单的极大极小', () {
      final z = [0.0, 1.0, 0.0, -1.0, 0.0];
      expect(localExtrema(z, 1, findMax: true), [1]);
      expect(localExtrema(z, 1, findMax: false), [3]);
    });

    test('平台期合并到中心，而不是每个点都算候选', () {
      // ⚠️ 这条守着真实踩过的坑：
      //    浮点运算常产生连续相同的值，按 >= 判断会让它们全都成为候选，
      //    而选哪个取决于排序稳定性 —— 结果不确定。
      final z = [0.0, 1.0, 1.0, 1.0, 0.0];
      final got = localExtrema(z, 1, findMax: true);
      expect(got.length, 1, reason: '平台期应当只产生一个极值');
      expect(got.first, 2, reason: '应当取平台期的中心');
    });

    test('最小间隔约束生效：相邻极值只保留更极端的', () {
      // 两个极大：值 1.5 在 index 3，值 1.8 在 index 5，间隔 2
      final z = [0.0, 1.0, 0.5, 1.5, 0.5, 1.8, 0.0];
      final got = localExtrema(z, 5, findMax: true);
      expect(got.length, 1, reason: '间隔 2 < minGap 5，应当只保留一个');
      expect(got.first, 5, reason: '应当保留更极端的那个（1.8 > 1.5）');
    });

    test('间隔足够时都保留', () {
      final z = List<double>.filled(30, 0);
      z[5] = 1.0;
      z[20] = 1.0;
      final got = localExtrema(z, 5, findMax: true);
      expect(got, containsAll([5, 20]));
    });

    test('单调序列没有内部极值', () {
      final z = List.generate(20, (i) => i.toDouble());
      expect(localExtrema(z, 2, findMax: true), isEmpty);
      expect(localExtrema(z, 2, findMax: false), isEmpty);
    });

    test('太短的序列返回空而不是崩', () {
      expect(localExtrema([], 1, findMax: true), isEmpty);
      expect(localExtrema([1.0], 1, findMax: true), isEmpty);
      expect(localExtrema([1.0, 2.0], 1, findMax: true), isEmpty);
    });

    test('返回的索引是升序的', () {
      final z = List<double>.filled(60, 0);
      for (final i in [50, 10, 30, 5]) {
        z[i] = 1.0;
      }
      final got = localExtrema(z, 3, findMax: true);
      for (var i = 1; i < got.length; i++) {
        expect(got[i], greaterThan(got[i - 1]),
            reason: '索引必须升序 —— 后面按时间挑关键帧依赖它');
      }
    });
  });

  // -------------------------------------------------------------------------
  group('步态事件检测', () {
    test('周期性信号能检出事件，且次数合理', () {
      // 30 fps，步态周期 20 帧 → 1.5 步/秒 = 90 步/分
      // 300 帧 = 10 秒 → 应当检出约 15 次支撑中期
      final seq = makeSeq(frames: 300, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);

      expect(ev.midstances.length, greaterThanOrEqualTo(10),
          reason: '10 秒 1.5 步/秒应当检出 10 次以上');
      expect(ev.midstances.length, lessThanOrEqualTo(20),
          reason: '不该检出远超实际步数的假事件');
      expect(ev.touchdowns.length, ev.midstances.length,
          reason: '每个支撑中期对应一次着地');
    });

    test('髋高几乎不动时拒绝出事件，而不是产生一堆假的', () {
      // ⚠️ 这条守着真实踩过的坑：一条几乎平的曲线产生过 20 个假事件，
      //    因为它们都"满足局部极值的定义"。
      final seq = makeSeq(frames: 300, periodFrames: 20, amplitude: 0.0001);
      final ev = detectGaitEvents(seq, fps: 30);

      expect(ev.isEmpty, isTrue, reason: '振幅过低时不该产生事件');
      expect(ev.reliability, 'poor');
      expect(ev.notes.join(), contains('起伏'));
    });

    test('帧数太少时明确说明原因', () {
      final seq = makeSeq(frames: 5, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);
      expect(ev.isEmpty, isTrue);
      expect(ev.notes.join(), contains('帧数太少'));
    });

    test('髋部点全部不可见时明确说明原因', () {
      final frames = List.generate(100, (i) => PoseFrame(
        frameIndex: i,
        keypoints: List.generate(17,
            (_) => const Keypoint(x: 0.5, y: 0.5, confidence: 0.01)),
      ));
      final seq = PoseSequence(
          frames: frames, sourceWidth: 960, sourceHeight: 540);
      final ev = detectGaitEvents(seq, fps: 30);
      expect(ev.isEmpty, isTrue);
      expect(ev.notes.join(), contains('髋部点太少'));
    });

    test('着地在支撑中期之前，离地在之后', () {
      // 这是时序上的硬约束。反了的话关键帧会挑错位置。
      final seq = makeSeq(frames: 300, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);
      expect(ev.midstances, isNotEmpty);

      final m = ev.midstances.first;
      final td = ev.touchdowns.first;
      expect(td, lessThan(m),
          reason: '着地必须在支撑中期之前 —— 支撑期是从着地开始的');
    });

    test('事件不重复（去重生效）', () {
      final seq = makeSeq(frames: 300, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);
      final uniq = ev.touchdowns.toSet();
      expect(uniq.length, ev.touchdowns.length, reason: '着地帧有重复');
      final uniqM = ev.midstances.toSet();
      expect(uniqM.length, ev.midstances.length, reason: '支撑中期有重复');
    });

    test('事件帧号在有效范围内', () {
      final seq = makeSeq(frames: 300, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);
      for (final f in ev.midstances) {
        expect(f, greaterThanOrEqualTo(0));
        expect(f, lessThan(300));
      }
      for (final f in ev.touchdowns) {
        expect(f, greaterThanOrEqualTo(0));
        expect(f, lessThan(300));
      }
    });

    test('噪声下仍能检出事件', () {
      final rnd = math.Random(7);
      final frames = <PoseFrame>[];
      for (var i = 0; i < 300; i++) {
        final phase = 2 * math.pi * i / 20;
        final noise = (rnd.nextDouble() - 0.5) * 0.008;
        final y = 0.5 + 0.03 * math.cos(phase) + noise;
        frames.add(PoseFrame(
          frameIndex: i,
          keypoints: List.generate(17, (k) => k == 11 || k == 12
              ? Keypoint(x: 0.5, y: y, confidence: 0.9)
              : const Keypoint(x: 0.4, y: 0.5, confidence: 0.9)),
        ));
      }
      final seq = PoseSequence(
          frames: frames, sourceWidth: 960, sourceHeight: 540);
      final ev = detectGaitEvents(seq, fps: 30);
      expect(ev.midstances.length, greaterThanOrEqualTo(8),
          reason: '加了噪声后仍应检出大部分事件');
    });

    test('说明里必须写明着地是推算的', () {
      // ⚠️ 这条守着一个诚实性要求：
      //    着地位置是从支撑中期推出的，不是直接测量的。
      //    报告里必须说清楚，否则教练会以为它是精确测量值。
      final seq = makeSeq(frames: 300, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);
      expect(ev.notes.join(), contains('推算'));
    });
  });

  // -------------------------------------------------------------------------
  group('相位划分', () {
    test('加速段覆盖前几步，后面是途中跑', () {
      final seq = makeSeq(frames: 300, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);
      final ph = detectPhases(seq, fps: 30, events: ev);

      expect(ph, isNotEmpty);
      final names = ph.map((p) => p.phase).toList();
      expect(names, contains(PhaseName.acceleration));

      // 相位必须按时间排列且不重叠
      for (var i = 1; i < ph.length; i++) {
        expect(ph[i].fromFrame, greaterThan(ph[i - 1].toFrame),
            reason: '相位区间重叠了');
      }
    });

    test('没有事件时返回空，而不是猜', () {
      final seq = makeSeq(frames: 300, periodFrames: 20, amplitude: 0.0001);
      final ev = detectGaitEvents(seq, fps: 30);
      expect(detectPhases(seq, fps: 30, events: ev), isEmpty);
    });

    test('相位置信度不虚高（按步数划分是启发式）', () {
      // 按步数划分不如按速度曲线精确，置信度应当低于 1.0，
      // 让上层知道这个边界是估的。
      final seq = makeSeq(frames: 300, periodFrames: 20);
      final ev = detectGaitEvents(seq, fps: 30);
      for (final p in detectPhases(seq, fps: 30, events: ev)) {
        expect(p.confidence, lessThan(1.0),
            reason: '${p.phase} 的置信度是 1.0 —— 但它是按步数估的');
      }
    });

    test('PhaseSegment.contains 正确判断', () {
      const p = PhaseSegment(
          phase: PhaseName.acceleration, fromFrame: 10, toFrame: 20);
      expect(p.contains(10), isTrue);
      expect(p.contains(15), isTrue);
      expect(p.contains(20), isTrue);
      expect(p.contains(9), isFalse);
      expect(p.contains(21), isFalse);
      expect(p.length, 11);
    });

    test('阶段中文名齐全', () {
      expect(PhaseName.zh(PhaseName.acceleration), '加速段');
      expect(PhaseName.zh(PhaseName.maxVelocity), '最高速度');
      expect(PhaseName.zh('unknown_phase'), 'unknown_phase');
    });
  });
}
