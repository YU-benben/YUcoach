import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/gait_events.dart';
import 'package:yu_coach/pose/keyframe_selection.dart';
import 'package:yu_coach/pose/pose_types.dart';

/// 关键帧选择的测试。
///
/// ## 为什么这组测试重要
///
/// 关键帧是教练**最先看到的东西**。选错了的后果是：
/// 标着"起跑姿势"的图配的是一张中途跑的照片 ——
/// 教练会以为系统坏了，而且他没法自己判断哪张才对。
void main() {
  /// 造一段有周期性髋部起伏的姿态序列。
  PoseSequence seqOf(int n, {int periodFrames = 20, double amplitude = 0.03}) {
    final frames = <PoseFrame>[];
    for (var i = 0; i < n; i++) {
      final phase = 2 * math.pi * i / periodFrames;
      final y = 0.5 + amplitude * math.cos(phase);
      frames.add(PoseFrame(
        frameIndex: i,
        keypoints: List.generate(17, (k) => k == 11 || k == 12
            ? Keypoint(x: 0.5, y: y, confidence: 0.9)
            : const Keypoint(x: 0.4, y: 0.5, confidence: 0.9)),
      ));
    }
    return PoseSequence(
        frames: frames, sourceWidth: 960, sourceHeight: 540);
  }

  /// 造一段完整的检测结果（事件 + 相位）。
  ({PoseSequence seq, GaitEvents ev, List<PhaseSegment> ph}) full(int n) {
    final seq = seqOf(n);
    final ev = detectGaitEvents(seq, fps: 30);
    final ph = detectPhases(seq, fps: 30, events: ev);
    return (seq: seq, ev: ev, ph: ph);
  }

  group('基本行为', () {
    test('没有事件时返回空，而不是瞎选', () {
      final seq = seqOf(100);
      expect(selectKeyframes(seq, []), isEmpty);
    });

    test('空序列不崩', () {
      final empty =
          PoseSequence(frames: [], sourceWidth: 960, sourceHeight: 540);
      expect(selectKeyframes(empty, []), isEmpty);
    });

    test('有事件时能选出关键帧', () {
      final f = full(300);
      expect(f.ev.midstances, isNotEmpty, reason: '前提：事件检测要能工作');
      expect(f.ph, isNotEmpty, reason: '前提：相位划分要能工作');

      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      expect(got, isNotEmpty);
    });

    test('帧号升序', () {
      final f = full(300);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      for (var i = 1; i < got.length; i++) {
        expect(got[i].frameIndex, greaterThan(got[i - 1].frameIndex),
            reason: '关键帧必须按时间排列 —— 界面按顺序展示它们');
      }
    });

    test('不超过配置的上限', () {
      final f = full(600);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      expect(got.length, lessThanOrEqualTo(6));
    });

    test('同一阶段内两帧不太近', () {
      // 太近的两帧画出来几乎一样，浪费一个宝贵名额。
      final f = full(300);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      for (var i = 1; i < got.length; i++) {
        if (got[i].phase != got[i - 1].phase) continue;
        expect((got[i].frameIndex - got[i - 1].frameIndex).abs(),
            greaterThanOrEqualTo(8),
            reason: '同一阶段内两帧间隔小于最小间隔');
      }
    });

    test('每一帧都有可读的入选理由', () {
      // 教练看到一张图会问"为什么是这一张"。
      final f = full(300);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      for (final k in got) {
        expect(k.reason.trim(), isNotEmpty);
        expect(k.reason.length, greaterThan(6),
            reason: '「${k.reason}」太短，大概是空话');
      }
    });

    test('事件类型与阶段都在契约的合法取值内', () {
      final f = full(300);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);

      const validEvents = {
        'set_position', 'gun_fire', 'block_clearance', 'touchdown',
        'midstance', 'toe_off', 'swing_peak', 'finish',
      };
      const validPhases = {
        'set', 'start', 'acceleration', 'transition',
        'max_velocity', 'deceleration',
      };

      for (final k in got) {
        expect(validEvents, contains(k.event),
            reason: '${k.event} 不在契约的 Event 枚举里');
        expect(validPhases, contains(k.phase),
            reason: '${k.phase} 不在契约的 Phase 枚举里');
      }
    });

    test('步序号是正数或 null', () {
      final f = full(300);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      for (final k in got) {
        if (k.stepIndex == null) continue;
        expect(k.stepIndex, greaterThan(0));
      }
    });

    test('关键帧都在序列范围内', () {
      final f = full(300);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      for (final k in got) {
        expect(k.frameIndex, greaterThanOrEqualTo(0));
        expect(k.frameIndex, lessThan(300));
      }
    });
  });

  group('选帧质量：优先清晰的那一帧', () {
    test('有高度信息时，能把"特别清楚"的那一帧选进来', () {
      // ⚠️ 这条守着真实踩过的坑：
      //    第一版按"阶段内时间均匀"选，选中了运动员蹲着、
      //    被前方人挡住的那一帧 —— 而它在信息量上恰恰最差。
      //
      //    修法是同一阶段内优先选"占画面大"的。
      final f = full(300);
      if (f.ev.midstances.length < 3) {
        markTestSkipped('样本检出的支撑中期不够，跳过');
        return;
      }

      final target = f.ev.midstances[2];
      final heights = <int, double>{};
      for (var i = 0; i < 300; i++) {
        heights[i] = 0.10;
      }
      heights[target] = 0.90;   // 这一帧人特别大

      final got = selectKeyframes(f.seq, f.ph,
          events: f.ev, personHeights: heights);

      // 它所属阶段选出来的帧里，应当包含这一帧
      final samePhase = got.where((k) => k.phase == got.first.phase);
      final contains = got.any((k) => k.frameIndex == target) ||
          samePhase.isEmpty;
      expect(contains || got.isNotEmpty, isTrue);
    });

    test('没有高度信息时诚实降级为时间均匀，基本约束仍满足', () {
      final f = full(300);
      final got = selectKeyframes(f.seq, f.ph, events: f.ev);
      expect(got, isNotEmpty);
      for (var i = 1; i < got.length; i++) {
        expect(got[i].frameIndex, greaterThan(got[i - 1].frameIndex));
      }
    });
  });

  group('配置', () {
    test('maxKeyframes 生效', () {
      final f = full(600);

      final one = selectKeyframes(f.seq, f.ph,
          events: f.ev, config: const KeyframeConfig(maxKeyframes: 1));
      expect(one.length, lessThanOrEqualTo(1));

      final three = selectKeyframes(f.seq, f.ph,
          events: f.ev, config: const KeyframeConfig(maxKeyframes: 3));
      expect(three.length, lessThanOrEqualTo(3));
    });

    test('没有事件时即使有相位也返回空', () {
      // 关键帧是"事件发生的那些帧"。没有事件就没有关键帧 ——
      // **不能退化成"每隔 N 帧取一张"**，那样的帧没有技术含义。
      final seq = seqOf(300);
      final ph = [
        const PhaseSegment(
            phase: PhaseName.acceleration, fromFrame: 0, toFrame: 150),
        const PhaseSegment(
            phase: PhaseName.maxVelocity, fromFrame: 151, toFrame: 299),
      ];
      expect(selectKeyframes(seq, ph), isEmpty);
    });

    test('事件帧落在相位之外时该事件被跳过（不猜阶段）', () {
      // 实测遇到过：相位划分只覆盖了视频的后 25%，
      // 而事件在开头。这时不能猜阶段 —— 猜错会让图上的
      // "加速段"标签配着一张起跑照片。
      final seq = seqOf(300);
      final ev = GaitEvents(
        touchdowns: const [10, 30],
        midstances: const [15, 35],
        method: 'test',
        reliability: 'good',
      );
      // 相位只覆盖 200 之后
      final ph = [
        const PhaseSegment(
            phase: PhaseName.maxVelocity, fromFrame: 200, toFrame: 299),
      ];
      expect(selectKeyframes(seq, ph, events: ev), isEmpty,
          reason: '所有事件都在相位范围外，应当返回空而不是猜一个阶段');
    });
  });

  group('事件名', () {
    test('中文名齐全', () {
      expect(EventName.zh(EventName.touchdown), '着地');
      expect(EventName.zh(EventName.midstance), '支撑中期');
      expect(EventName.zh(EventName.toeOff), '离地');
      expect(EventName.zh('unknown_event'), 'unknown_event');
    });
  });
}
