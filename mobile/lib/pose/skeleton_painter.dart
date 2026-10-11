/// 骨骼绘制。
///
/// ## 两种模式
///
/// ```
/// 叠加模式（overlay）    骨骼画在视频帧上
/// 纯骨架模式（standalone） 只有骨骼，背景我们自己画
/// ```
///
/// **两种都要**，因为它们的用途不同：
///
///   叠加模式 —— 教练能看到真实场地、跑道线、起跑器。
///               判断"脚离地多远""身体和跑道什么关系"必须看这个。
///   纯骨架模式 —— 小屏上看骨架清楚得多。17 个点在手机上本来就挤，
///               去掉背景杂色能一眼看清关节关系。
///
/// ## 为什么自己做而不是用现成库
///
/// 没有现成的库能画"带质量码的骨架 + 角度弧 + 尺度条"。
/// 而且自己画能完全控制样式（左右分色、低置信度用空心点等），
/// 这些都是本项目的特有需求。
///
/// ## ⚠️ 坐标是归一化的
///
/// 关键点坐标是 **0~1** 的归一化值（相对原图）。
/// 绘制时乘上画布尺寸即可 —— 这是坐标**唯一**的转换点。
/// 如果这里再引入别的缩放，会出现"骨架和画面对不上"的问题，
/// 而且很难查（因为看起来只是"稍微偏一点"）。
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'pose_types.dart';
import 'skeleton.dart';
import 'skeleton_style.dart';

/// 把归一化坐标转成画布坐标。
///
/// ⚠️ 这是坐标转换的**唯一入口**。所有绘制都必须走它，
///    否则很容易在某处忘了乘画布尺寸，导致骨架整体偏移。
Offset toCanvas(Keypoint kp, Size size) =>
    Offset(kp.x * size.width, kp.y * size.height);

/// 骨骼绘制器。
class SkeletonPainter extends CustomPainter {
  const SkeletonPainter({
    required this.frame,
    required this.style,
    this.showOnlyKeyJoints = false,
  });

  /// 要画的姿态。为 null 时不画任何东西（用于空白帧）。
  final PoseFrame? frame;

  final SkeletonStyle style;

  /// 只画关键关节（去掉面部点）。
  ///
  /// 手机上点太多会挤成一团，反而挡住真正重要的髋、膝、踝。
  final bool showOnlyKeyJoints;

  @override
  void paint(Canvas canvas, Size size) {
    final f = frame;
    if (f == null) return;

    final shortest = math.min(size.width, size.height);
    final lw = style.lineWidth(shortest);
    final radius = style.jointRadius(shortest);
    final showFace = style.showFace && !showOnlyKeyJoints;

    // ---- 1. 先画骨骼线，再画点 ----
    //
    // 顺序很重要：点画在线上面，关节位置才清楚。
    // 反过来的话线会盖住点，看起来像"关节缺了一块"。
    for (final bone in skeletonBones) {
      final a = f.byName(bone.from);
      final b = f.byName(bone.to);
      if (a == null || b == null) continue;

      // 不可见的点不画线。画出来会是一条指向垃圾坐标的线。
      if (!a.visible || !b.visible) continue;

      // 面部相关的线在精简模式下跳过
      if (!showFace &&
          (SkeletonStyle.faceKeypointsSet.contains(bone.from) ||
              SkeletonStyle.faceKeypointsSet.contains(bone.to))) {
        continue;
      }

      final p1 = toCanvas(a, size);
      final p2 = toCanvas(b, size);

      // 躯干用 boneColor，四肢按左右分色
      final color = _boneColor(bone, a, b);

      _drawLine(canvas, p1, p2, color, lw);
    }

    // ---- 2. 关节 ----
    for (var i = 0; i < f.keypoints.length; i++) {
      final name = cocoNames[i];
      final kp = f.keypoints[i];

      if (!kp.visible) continue;
      if (!showFace && SkeletonStyle.faceKeypointsSet.contains(name)) {
        continue;
      }
      if (showOnlyKeyJoints && !keyJoints.contains(name)) continue;

      final p = toCanvas(kp, size);
      _drawJoint(canvas, p, style.colorFor(name, kp.visible), radius,
          uncertain: kp.quality == QualityCode.uncertain);

      if (style.showLabels) {
        _drawLabel(canvas, p, name, size, radius);
      }
    }
  }

  /// 一条骨骼线用什么颜色。
  Color _boneColor(Bone bone, Keypoint a, Keypoint b) {
    // 面部相关的线用面部色
    if (SkeletonStyle.faceKeypointsSet.contains(bone.from) ||
        SkeletonStyle.faceKeypointsSet.contains(bone.to)) {
      return style.faceColor;
    }
    // 只要有一端是左侧就用左色，两端都是右侧才用右色。
    //
    // 为什么"一端是左就用左色"：跨左右的线（肩到肩、髋到髋）
    // 本来就不属于任何一侧，用左色只是给个稳定结果 ——
    // 关键是**不要**让同一条线在不同帧里变色。
    if (isLeftSide(bone.from) || isLeftSide(bone.to)) {
      return style.leftColor;
    }
    if (bone.from.endsWith('_r') || bone.to.endsWith('_r')) {
      return style.rightColor;
    }
    return style.boneColor;
  }

  /// 画一条带描边的线。
  ///
  /// ## 为什么必须描边
  ///
  /// 叠加在视频画面上时，背景可能是浅色跑道、深色树荫、白色跑道线 ——
  /// 任何单一颜色的线都会在某些位置看不清。
  ///
  /// 先画一条更粗的深色线，再把亮色线画在上面，
  /// 这样在任意背景上都有对比度。电脑端的关键帧图用了同样的做法。
  void _drawLine(Canvas canvas, Offset p1, Offset p2, Color color, double lw) {
    if (style.outlineWidth > 0) {
      canvas.drawLine(
        p1,
        p2,
        Paint()
          ..color = style.outlineColor
          ..strokeWidth = lw + style.outlineWidth
          ..strokeCap = StrokeCap.round,
      );
    }
    canvas.drawLine(
      p1,
      p2,
      Paint()
        ..color = color
        ..strokeWidth = lw
        ..strokeCap = StrokeCap.round,
    );
  }

  /// 画一个关节。
  ///
  /// ## 质量码的视觉表达
  ///
  /// ```
  /// 清晰（q=2）   → 实心圆点
  /// 存疑（q=1）   → 空心圆点
  /// 不可见（q=0） → 不画
  /// ```
  ///
  /// 空心点是有意义的：教练一眼就能看出"这个关节的数据别全信"。
  /// 电脑端的关键帧图用了同样的约定，两边看到的一致。
  void _drawJoint(Canvas canvas, Offset p, Color color, double radius,
      {required bool uncertain}) {
    if (style.outlineWidth > 0) {
      canvas.drawCircle(
        p,
        radius + style.outlineWidth * 0.6,
        Paint()..color = style.outlineColor,
      );
    }
    if (uncertain) {
      // 空心：只描边不填充
      canvas.drawCircle(
        p,
        radius,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = math.max(1.2, radius * 0.42),
      );
    } else {
      canvas.drawCircle(p, radius, Paint()..color = color);
    }
  }

  /// 画关节名。
  ///
  /// 名字是英文的（`knee_l`），因为中文名要靠查表，
  /// 而这个模式本来就是给开发者/教学用的，英文名够用且不会歧义。
  void _drawLabel(Canvas canvas, Offset p, String name, Size size,
      double radius) {
    final tp = TextPainter(
      text: TextSpan(
        text: name,
        style: TextStyle(
          fontSize: style.fontSize(math.min(size.width, size.height)) * 0.8,
          color: Colors.white,
          fontWeight: FontWeight.w500,
          shadows: const [
            Shadow(color: Colors.black, blurRadius: 3),
            Shadow(color: Colors.black, blurRadius: 3),
          ],
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();

    tp.paint(canvas, p + Offset(radius + 3, -tp.height / 2));
  }

  @override
  bool shouldRepaint(SkeletonPainter old) =>
      old.frame != frame ||
      old.style != style ||
      old.showOnlyKeyJoints != showOnlyKeyJoints;
}

/// 纯骨架模式的背景。
///
/// 画一个渐变的深色/浅色底 + 一条**地面线**。
///
/// ## 为什么必须有地面线
///
/// 教练看跑姿时，一个核心判断是"脚离地多远""身体和地面什么角度"。
/// 去掉视频背景之后，如果连地面参照都没有，这些判断就做不了了 ——
/// 骨架会像悬在空中。
///
/// 地面位置从姿态推：所有踝关节里最低的那个。
/// 这不是精确的地面，但作为视觉参照足够了。
class GroundReferencePainter extends CustomPainter {
  const GroundReferencePainter({
    required this.frame,
    required this.dark,
    this.lineColor,
  });

  final PoseFrame? frame;
  final bool dark;
  final Color? lineColor;

  @override
  void paint(Canvas canvas, Size size) {
    final f = frame;
    if (f == null) return;

    // 取最低的踝
    double? groundY;
    for (final name in ['ankle_l', 'ankle_r']) {
      final kp = f.byName(name);
      if (kp == null || !kp.visible) continue;
      groundY = groundY == null ? kp.y : math.max(groundY, kp.y);
    }
    if (groundY == null) return;

    final y = groundY * size.height;
    final color = lineColor ??
        (dark ? const Color(0x33FFFFFF) : const Color(0x33000000));

    // 虚线：提示这是"参考线"而不是真实地面
    const dash = 8.0;
    const gap = 6.0;
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1.2;

    var x = 0.0;
    while (x < size.width) {
      canvas.drawLine(
        Offset(x, y),
        Offset(math.min(x + dash, size.width), y),
        paint,
      );
      x += dash + gap;
    }

    // 标一下"地面"
    final tp = TextPainter(
      text: TextSpan(
        text: '足部最低点（参考）',
        style: TextStyle(
          fontSize: 10,
          color: color,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset(size.width - tp.width - 8, y + 4));
  }

  @override
  bool shouldRepaint(GroundReferencePainter old) =>
      old.frame != frame || old.dark != dark || old.lineColor != lineColor;
}
