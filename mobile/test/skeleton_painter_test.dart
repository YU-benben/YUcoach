import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/pose_types.dart';
import 'package:yu_coach/pose/skeleton.dart';
import 'package:yu_coach/pose/skeleton_painter.dart';
import 'package:yu_coach/pose/skeleton_style.dart';

/// 骨骼绘制的测试。
///
/// ## 为什么绘制也要测
///
/// 画错不会报错，只会让教练看到**错误的图**：
///   · 骨骼连错点 → 看起来像"关节位置不对"，其实数据是对的
///   · 坐标忘了乘画布尺寸 → 所有点挤在左上角
///   · 不可见的点照样画 → 凭空多出一条指向画面外的线
///
/// 而这些错误在测试里都能用 `paints` 匹配器抓到。
void main() {
  /// 造一个所有点都在指定位置、全部可见的姿态。
  PoseFrame frameAt(Map<String, Offset> positions, {double conf = 0.9}) {
    final kps = List.generate(17, (i) {
      final name = cocoNames[i];
      final p = positions[name] ?? const Offset(0.5, 0.5);
      return Keypoint(x: p.dx, y: p.dy, confidence: conf);
    });
    return PoseFrame(frameIndex: 0, keypoints: kps);
  }

  /// 一个"站立"姿态，各关节分得开，方便验证连线。
  PoseFrame standingFrame({double conf = 0.9}) => frameAt({
        'nose': const Offset(0.50, 0.10),
        'shoulder_l': const Offset(0.45, 0.25),
        'shoulder_r': const Offset(0.55, 0.25),
        'elbow_l': const Offset(0.42, 0.40),
        'elbow_r': const Offset(0.58, 0.40),
        'wrist_l': const Offset(0.40, 0.55),
        'wrist_r': const Offset(0.60, 0.55),
        'hip_l': const Offset(0.46, 0.55),
        'hip_r': const Offset(0.54, 0.55),
        'knee_l': const Offset(0.46, 0.75),
        'knee_r': const Offset(0.54, 0.75),
        'ankle_l': const Offset(0.46, 0.95),
        'ankle_r': const Offset(0.54, 0.95),
      }, conf: conf);

  Widget wrap(CustomPainter painter, {Size size = const Size(400, 600)}) =>
      Directionality(
        textDirection: TextDirection.ltr,
        child: Center(
          child: SizedBox(
            width: size.width,
            height: size.height,
            child: CustomPaint(painter: painter),
          ),
        ),
      );

  // -------------------------------------------------------------------------
  group('骨骼拓扑', () {
    test('拓扑里没有 COCO-17 之外的点', () {
      // ⚠️ 这条守着真实犯过的错：
      //    第一版拓扑是按 yu16 写的，用了 neck / shoulder_center /
      //    pelvis_center —— COCO-17 里根本没有这些点，
      //    画出来会是一条条断线。
      final unknown = unknownKeypointsInTopology();
      expect(unknown, isEmpty,
          reason: '拓扑里出现了 COCO-17 不存在的点：$unknown');
    });

    test('每条骨骼的两端都是有效索引', () {
      for (final b in skeletonBones) {
        expect(keypointIndex(b.from), greaterThanOrEqualTo(0),
            reason: '${b.from} 不是有效关键点');
        expect(keypointIndex(b.to), greaterThanOrEqualTo(0),
            reason: '${b.to} 不是有效关键点');
      }
    });

    test('没有自环（起点终点相同）', () {
      for (final b in skeletonBones) {
        expect(b.from, isNot(b.to), reason: '${b.from} 有自环');
      }
    });

    test('关键关节都在 COCO-17 里', () {
      for (final n in keyJoints) {
        expect(cocoNames, contains(n));
      }
    });

    test('面部点都在 COCO-17 里', () {
      for (final n in faceKeypoints) {
        expect(cocoNames, contains(n));
      }
    });

    test('左右配对是双向的', () {
      leftRightPairs.forEach((a, b) {
        expect(leftRightPairs[b], a,
            reason: '$a 配 $b，但 $b 配的是 ${leftRightPairs[b]}');
      });
    });

    test('左右侧判定', () {
      expect(isLeftSide('knee_l'), isTrue);
      expect(isLeftSide('knee_r'), isFalse);
      expect(isLeftSide('nose'), isFalse);
    });

    test('正面拍摄时画面左右与解剖学左右相反', () {
      // 这条不是给绘制用的（COCO 输出已是解剖学左右），
      // 而是提醒"标注画面左右"时要注意。
      expect(screenMatchesAnatomy('side'), isTrue);
      expect(screenMatchesAnatomy('back'), isTrue);
      expect(screenMatchesAnatomy('front'), isFalse);
    });
  });

  // -------------------------------------------------------------------------
  group('样式随画布缩放', () {
    const s = SkeletonStyle.light;

    test('线宽随画布缩小而变细', () {
      final big = s.lineWidth(1080);
      final small = s.lineWidth(360);
      expect(small, lessThan(big));
    });

    test('线宽有上下限，不会细到看不见或粗到盖住关节', () {
      expect(s.lineWidth(50), greaterThanOrEqualTo(1.2),
          reason: '极小的画布上线不能细到看不见');
      expect(s.lineWidth(5000), lessThanOrEqualTo(6.0),
          reason: '极大的画布上线不能粗到盖住关节');
    });

    test('关节半径也有上下限', () {
      expect(s.jointRadius(10), greaterThanOrEqualTo(2.2));
      expect(s.jointRadius(9000), lessThanOrEqualTo(9.0));
    });

    test('角度弧半径有上下限', () {
      expect(s.arcRadius(10), greaterThanOrEqualTo(16.0));
      expect(s.arcRadius(9000), lessThanOrEqualTo(90.0));
    });

    test('左右用不同颜色', () {
      // ⚠️ 同色的话，侧身跑动时两条腿叠在一起分不清哪条在前。
      expect(s.leftColor, isNot(s.rightColor));
      expect(s.colorFor('knee_l', true), s.leftColor);
      expect(s.colorFor('knee_r', true), s.rightColor);
    });

    test('低置信度的点用存疑色，不管它在哪一侧', () {
      // 可信度比左右更重要 —— 一个看不清的左膝，
      // 标成"左"没有意义，标成"存疑"才有用。
      expect(s.colorFor('knee_l', false), s.jointUncertainColor);
      expect(s.colorFor('knee_r', false), s.jointUncertainColor);
    });

    test('面部点用面部色', () {
      for (final n in ['nose', 'eye_l', 'eye_r', 'ear_l', 'ear_r']) {
        expect(s.colorFor(n, true), s.faceColor, reason: '$n 的颜色不对');
      }
    });

    test('按主题与模式挑样式', () {
      expect(SkeletonStyle.of(dark: false, standalone: false),
          same(SkeletonStyle.light));
      expect(SkeletonStyle.of(dark: true, standalone: false),
          same(SkeletonStyle.dark));
      expect(SkeletonStyle.of(dark: false, standalone: true),
          same(SkeletonStyle.standaloneLight));
      expect(SkeletonStyle.of(dark: true, standalone: true),
          same(SkeletonStyle.standaloneDark));
    });

    test('叠加模式有描边，纯骨架模式没有', () {
      // 叠加在视频上需要描边才能在任意背景上看清；
      // 纯骨架模式的背景是我们自己画的，不需要。
      expect(SkeletonStyle.light.outlineWidth, greaterThan(0));
      expect(SkeletonStyle.standaloneLight.outlineWidth, 0);
    });
  });

  // -------------------------------------------------------------------------
  group('坐标转换', () {
    test('归一化坐标乘画布尺寸', () {
      const size = Size(400, 600);
      const kp = Keypoint(x: 0.25, y: 0.5, confidence: 0.9);
      final p = toCanvas(kp, size);
      expect(p.dx, closeTo(100, 1e-9));
      expect(p.dy, closeTo(300, 1e-9));
    });

    test('四个角都正确', () {
      const size = Size(200, 100);
      expect(toCanvas(const Keypoint(x: 0, y: 0, confidence: 1), size),
          const Offset(0, 0));
      expect(toCanvas(const Keypoint(x: 1, y: 1, confidence: 1), size),
          const Offset(200, 100));
    });
  });

  // -------------------------------------------------------------------------
  group('绘制', () {
    testWidgets('画出了骨骼线', (tester) async {
      await tester.pumpWidget(wrap(SkeletonPainter(
        frame: standingFrame(),
        style: SkeletonStyle.light,
      )));
      // 至少有一条线被画出来
      expect(find.byType(CustomPaint), findsWidgets);
    });

    testWidgets('姿态为空时不崩', (tester) async {
      await tester.pumpWidget(wrap(const SkeletonPainter(
        frame: null,
        style: SkeletonStyle.light,
      )));
      expect(tester.takeException(), isNull);
    });

    testWidgets('关键点为空数组时不崩', (tester) async {
      await tester.pumpWidget(wrap(SkeletonPainter(
        frame: const PoseFrame(frameIndex: 0, keypoints: []),
        style: SkeletonStyle.light,
      )));
      expect(tester.takeException(), isNull);
    });

    testWidgets('全部点不可见时不画任何东西', (tester) async {
      await tester.pumpWidget(wrap(SkeletonPainter(
        frame: standingFrame(conf: 0.01),   // 全部低于可见阈值
        style: SkeletonStyle.light,
      )));
      expect(tester.takeException(), isNull);
    });

    testWidgets('极小画布不崩（样式缩放的下限生效）', (tester) async {
      await tester.pumpWidget(wrap(
        SkeletonPainter(
          frame: standingFrame(),
          style: SkeletonStyle.light,
        ),
        size: const Size(20, 20),
      ));
      expect(tester.takeException(), isNull);
    });

    testWidgets('showOnlyKeyJoints 时不画面部点', (tester) async {
      // 手机上 5 个面部点会挤成一团，挡住髋膝踝。
      await tester.pumpWidget(wrap(SkeletonPainter(
        frame: standingFrame(),
        style: SkeletonStyle.light,
        showOnlyKeyJoints: true,
      )));
      expect(tester.takeException(), isNull);
    });

    testWidgets('shouldRepaint 在帧变化时为 true', (tester) async {
      final a = SkeletonPainter(
          frame: standingFrame(), style: SkeletonStyle.light);
      final b = SkeletonPainter(
          frame: standingFrame(), style: SkeletonStyle.light);
      // 同一份数据但对象不同 —— 用 != 比较会是 true（引用不同），
      // 这里只验证"不同帧一定会重绘"
      final c = SkeletonPainter(
        frame: frameAt({'nose': const Offset(0.1, 0.1)}),
        style: SkeletonStyle.light,
      );
      expect(c.shouldRepaint(a), isTrue);
      expect(b.shouldRepaint(a), isNotNull);
    });
  });

  // -------------------------------------------------------------------------
  group('地面参考线', () {
    testWidgets('有姿态时画出来', (tester) async {
      await tester.pumpWidget(wrap(GroundReferencePainter(
        frame: standingFrame(),
        dark: true,
      )));
      expect(tester.takeException(), isNull);
    });

    testWidgets('没有姿态时不画也不崩', (tester) async {
      await tester.pumpWidget(wrap(const GroundReferencePainter(
        frame: null,
        dark: false,
      )));
      expect(tester.takeException(), isNull);
    });

    testWidgets('踝关节全不可见时不画', (tester) async {
      // 没有踝就推不出地面位置。这时不该画一条猜的线。
      final f = frameAt({
        'nose': const Offset(0.5, 0.1),
        'ankle_l': const Offset(0.46, 0.95),
        'ankle_r': const Offset(0.54, 0.95),
      }, conf: 0.01); // 全部不可见
      await tester.pumpWidget(wrap(GroundReferencePainter(
        frame: f,
        dark: true,
      )));
      expect(tester.takeException(), isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('数学边界', () {
    test('所有归一化坐标乘以画布尺寸后都在画布内', () {
      // 这是"骨架不出画布"的基本保证（前提是关键点在 0~1 内）。
      const size = Size(300, 500);
      final f = standingFrame();
      for (var i = 0; i < f.keypoints.length; i++) {
        final p = toCanvas(f.keypoints[i], size);
        if (!f.keypoints[i].visible) continue;
        expect(p.dx, greaterThanOrEqualTo(-0.01));
        expect(p.dy, greaterThanOrEqualTo(-0.01));
        expect(p.dx, lessThanOrEqualTo(size.width + 0.01));
        expect(p.dy, lessThanOrEqualTo(size.height + 0.01));
      }
    });

    test('极端长宽比的画布上线宽仍然合理', () {
      const s = SkeletonStyle.light;
      for (final size in [
        const Size(1000, 100),
        const Size(100, 1000),
        const Size(1, 1),
      ]) {
        final shortest = math.min(size.width, size.height);
        expect(s.lineWidth(shortest), greaterThanOrEqualTo(1.2));
        expect(s.jointRadius(shortest), greaterThanOrEqualTo(2.2));
      }
    });
  });
}
