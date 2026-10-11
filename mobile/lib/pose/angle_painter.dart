/// 角度弧的绘制。
///
/// ## 为什么光写数字不够
///
/// 只写「152°」教练不知道量的是**哪个**角 —— 髋膝之间？膝踝之间？
/// 所以必须：
///
///   1. 在关节点上按两条边画一段**弧**
///   2. 弧的中点写数值
///   3. 两条边画**短刻度**，指明量的是哪两条线
///
/// 这与几何课本里标注角度的方式一致 —— 教练一看就懂。
///
/// ## 与电脑端关键帧图的关系
///
/// 电脑端的 `backend/analysis/keyframes.py` 用 OpenCV 画同样的东西。
/// 逻辑一致（弧 + 刻度 + 数值），但实现完全不同：
///
///   电脑端  cv2.ellipse / cv2.putText，输出成 JPEG
///   手机端  Canvas.drawArc / TextPainter，实时绘制
///
/// 所以**视觉细节会有差异**（字体、抗锯齿），但含义相同。
/// 这不是问题 —— 教练不会拿手机截图和电脑图片逐像素比对。
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'angle_catalog.dart';
import 'skeleton_style.dart';

/// 一个要绘制的角度。
class AngleToDraw {
  const AngleToDraw({
    required this.definition,
    required this.arc,
    required this.value,
    this.label,
  });

  final AngleDefinition definition;

  /// 弧的三个点（归一化坐标）。
  final AngleArcPoints arc;

  /// 角度值（度）。
  final double value;

  /// 自定义标签。为 null 时用角度值。
  ///
  /// 用于标注"推导值"这类附加信息。
  final String? label;
}

/// 角度弧绘制器。
class AngleArcPainter extends CustomPainter {
  const AngleArcPainter({
    required this.angles,
    required this.style,
    this.showValues = true,
  });

  final List<AngleToDraw> angles;
  final SkeletonStyle style;

  /// 是否在弧上写数值。
  ///
  /// 关掉的话只画弧和刻度 —— 角度太多时数值会互相遮挡，
  /// 那时只画弧反而更清楚。
  final bool showValues;

  @override
  void paint(Canvas canvas, Size size) {
    if (angles.isEmpty) return;

    final shortest = math.min(size.width, size.height);
    final baseR = style.arcRadius(shortest);
    final lw = style.lineWidth(shortest);

    // ---- 标签防重叠 ----
    //
    // ⚠️ 同一帧上可能标 3~4 个角度。不加处理的话它们的标签会
    //    叠在一起（实测发生过：两个标签都落在画面左上角）。
    //
    //    做法：每个角度的弧半径递增。半径不同，标签自然散开。
    final placed = <Rect>[];

    for (var i = 0; i < angles.length; i++) {
      final a = angles[i];
      // 半径逐个递增，避免标签重叠
      final r = baseR * (1.0 + i * 0.32);

      _drawOne(canvas, size, a, r, lw, placed);
    }
  }

  void _drawOne(
    Canvas canvas,
    Size size,
    AngleToDraw a,
    double radius,
    double lw,
    List<Rect> placed,
  ) {
    final vx = a.arc.vertex.$1 * size.width;
    final vy = a.arc.vertex.$2 * size.height;
    final v = Offset(vx, vy);

    final fx = a.arc.from.$1 * size.width;
    final fy = a.arc.from.$2 * size.height;

    final tx = a.arc.to.$1 * size.width;
    final ty = a.arc.to.$2 * size.height;

    final angFrom = math.atan2(fy - vy, fx - vx);
    final angTo = math.atan2(ty - vy, tx - vx);

    // ---- 1. 两条边的短刻度 ----
    //
    // 刻度画在 vertex 到 from/to 的方向上，长度略超过弧半径。
    // 它们的作用是"指明量的是哪两条线"。
    _tick(canvas, v, angFrom, radius * 1.2, lw);
    if (a.arc.referenceEdgeIsEnd) {
      _tick(canvas, v, angTo, radius * 1.2, lw, dashed: true);
    } else {
      _tick(canvas, v, angTo, radius * 1.2, lw);
    }

    // ---- 2. 弧 ----
    //
    // 取**劣弧**：从 angFrom 扫到 angTo，跨过的角度绝对值 ≤ 180。
    // 用劣弧是因为夹角定义就是 ≤180°（见 angleAt 的返回值范围）。
    var sweep = angTo - angFrom;
    // 归一化到 (-π, π]
    while (sweep > math.pi) {
      sweep -= 2 * math.pi;
    }
    while (sweep <= -math.pi) {
      sweep += 2 * math.pi;
    }

    final rect = Rect.fromCircle(center: v, radius: radius);

    // 描边 + 亮色两层，保证在任意背景上都看得清
    if (style.outlineWidth > 0) {
      canvas.drawArc(
        rect,
        angFrom,
        sweep,
        false,
        Paint()
          ..color = style.outlineColor
          ..style = PaintingStyle.stroke
          ..strokeWidth = lw + style.outlineWidth
          ..strokeCap = StrokeCap.round,
      );
    }
    canvas.drawArc(
      rect,
      angFrom,
      sweep,
      false,
      Paint()
        ..color = style.arcColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = lw
        ..strokeCap = StrokeCap.round,
    );

    // ---- 3. 数值 ----
    if (!showValues) return;

    final text = a.label ?? '${a.value.toStringAsFixed(0)}°';
    final mid = angFrom + sweep / 2;
    var lx = vx + (radius + 22) * math.cos(mid);
    var ly = vy + (radius + 22) * math.sin(mid);

    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(
          fontSize: style.fontSize(math.min(size.width, size.height)),
          fontWeight: FontWeight.w600,
          color: style.arcColor,
          shadows: style.outlineWidth > 0
              ? const [
                  Shadow(color: Colors.black, blurRadius: 3),
                  Shadow(color: Colors.black, blurRadius: 3),
                ]
              : null,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();

    // 夹进画布内 —— 运动员常出现在画面边缘，
    // 不夹的话标签会跑到画面外，教练看不到数字。
    lx = lx.clamp(2.0, math.max(2.0, size.width - tp.width - 2));
    ly = ly.clamp(tp.height + 2,
        math.max(tp.height + 2, size.height - 2));

    final rect2 = Rect.fromLTWH(lx, ly - tp.height, tp.width, tp.height);

    // ---- 4. 重叠检测 ----
    //
    // 半径递增能解决大部分重叠，但角度接近时仍可能撞上。
    // 撞了就往下挪，最多试 5 次。
    var placedRect = rect2;
    for (var attempt = 0; attempt < 5; attempt++) {
      final hit = placed.any((r) => r.overlaps(placedRect));
      if (!hit) break;
      placedRect = placedRect.translate(0, tp.height + 2);
    }
    placed.add(placedRect);

    tp.paint(canvas, Offset(placedRect.left, placedRect.top));

    // ---- 5. 半径小的时候补一条引线 ----
    //
    // 标签被挪远之后，和弧之间的联系会变弱。
    // 画一条细引线把标签指回弧上。
    final moved = (placedRect.left - lx).abs() > 1 ||
        (placedRect.top - (ly - tp.height)).abs() > 1;
    if (moved) {
      canvas.drawLine(
        Offset(vx + radius * math.cos(mid), vy + radius * math.sin(mid)),
        Offset(placedRect.center.dx, placedRect.top),
        Paint()
          ..color = style.arcColor.withValues(alpha: 0.5)
          ..strokeWidth = 1,
      );
    }
  }

  /// 画一条从顶点指向某个方向的短刻度。
  void _tick(Canvas canvas, Offset v, double angle, double len, double lw,
      {bool dashed = false}) {
    final ex = v.dx + len * math.cos(angle);
    final ey = v.dy + len * math.sin(angle);

    if (!dashed) {
      if (style.outlineWidth > 0) {
        canvas.drawLine(
          v,
          Offset(ex, ey),
          Paint()
            ..color = style.outlineColor
            ..strokeWidth = lw + style.outlineWidth
            ..strokeCap = StrokeCap.round,
        );
      }
      canvas.drawLine(
        v,
        Offset(ex, ey),
        Paint()
          ..color = style.arcColor
          ..strokeWidth = lw
          ..strokeCap = StrokeCap.round,
      );
      return;
    }

    // 虚线：参考线用它。提示"这条不是身体的一部分"。
    const dash = 5.0;
    const gap = 4.0;
    final total = math.sqrt(math.pow(ex - v.dx, 2) + math.pow(ey - v.dy, 2));
    if (total < 1) return;
    final ux = (ex - v.dx) / total;
    final uy = (ey - v.dy) / total;

    final paint = Paint()
      ..color = style.arcColor.withValues(alpha: 0.75)
      ..strokeWidth = math.max(1.0, lw * 0.6)
      ..strokeCap = StrokeCap.round;

    var d = 0.0;
    while (d < total) {
      final d2 = math.min(d + dash, total);
      canvas.drawLine(
        Offset(v.dx + ux * d, v.dy + uy * d),
        Offset(v.dx + ux * d2, v.dy + uy * d2),
        paint,
      );
      d += dash + gap;
    }
  }

  @override
  bool shouldRepaint(AngleArcPainter old) =>
      old.angles != angles ||
      old.style != style ||
      old.showValues != showValues;
}
