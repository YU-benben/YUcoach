/// 骨骼绘制的样式。
///
/// ## 为什么样式要"随画布缩放"
///
/// 电脑端生成关键帧图时用的是固定像素粗细（线宽 2、点半径 4），
/// 因为输出尺寸固定是 960×540。
///
/// 但手机端的画布尺寸**不确定**：
///   · 小屏手机竖屏 ≈ 360 逻辑像素宽
///   · 平板横屏 ≈ 1000 逻辑像素宽
///   · 用户还会双指缩放
///
/// 固定像素的结果是：小屏上线挤成一团，大屏上细得看不清。
///
/// 所以线宽和点半径都按**短边的比例**算，并设上下限 ——
/// 下限保证小屏可读，上限防止大屏上出现"粗得盖住关节"的线。
library;

import 'package:flutter/material.dart';

/// 骨骼的绘制样式。
class SkeletonStyle {
  const SkeletonStyle({
    required this.jointColor,
    required this.jointUncertainColor,
    required this.boneColor,
    required this.leftColor,
    required this.rightColor,
    required this.faceColor,
    required this.outlineColor,
    required this.arcColor,
    this.showFace = true,
    this.showLabels = false,
    this.lineWidthScale = 1.0,
    this.outlineWidth = 2.5,
  });

  /// 主干关节的颜色（非左右成对的点）。
  final Color jointColor;

  /// 低置信度关节的颜色。
  final Color jointUncertainColor;

  /// 躯干骨骼线的颜色。
  final Color boneColor;

  /// 身体左侧的颜色。
  final Color leftColor;

  /// 身体右侧的颜色。
  ///
  /// ⚠️ 左右**必须用不同颜色**。同色的话，
  ///    侧身跑动时两条腿叠在一起，教练分不清哪条在前。
  final Color rightColor;

  /// 面部点的颜色。
  final Color faceColor;

  /// 描边色。让骨骼在任意背景上都看得清。
  final Color outlineColor;

  /// 角度弧的颜色。
  final Color arcColor;

  /// 是否画面部点。
  final bool showFace;

  /// 是否显示关节名。调试与教学时用。
  final bool showLabels;

  /// 线宽的额外缩放。用户缩放画布时传进来。
  final double lineWidthScale;

  /// 描边相对线宽的倍数。
  final double outlineWidth;

  /// 浅色主题下的样式。
  ///
  /// 叠在视频画面上用 —— 视频画面通常偏亮（操场、跑道），
  /// 所以骨骼要用**深色描边 + 亮色填充**，在任意背景上都能看清。
  static const light = SkeletonStyle(
    jointColor: Color(0xFF00E5FF),        // 青
    jointUncertainColor: Color(0xFFFFAB40), // 橙（低置信度）
    boneColor: Color(0xFF00E5FF),
    leftColor: Color(0xFF00E676),          // 绿
    rightColor: Color(0xFF7C4DFF),         // 紫
    faceColor: Color(0xFFFFD54F),          // 琥珀
    outlineColor: Color(0xCC000000),       // 半透明黑
    arcColor: Color(0xFFFFD54F),
  );

  /// 深色主题下的样式。
  ///
  /// 深色背景上不需要那么重的描边，但颜色要更亮。
  static const dark = SkeletonStyle(
    jointColor: Color(0xFF40E0FF),
    jointUncertainColor: Color(0xFFFFB74D),
    boneColor: Color(0xFF40E0FF),
    leftColor: Color(0xFF69F0AE),
    rightColor: Color(0xFFB388FF),
    faceColor: Color(0xFFFFE082),
    outlineColor: Color(0x99000000),
    arcColor: Color(0xFFFFE082),
  );

  /// 纯骨架模式（不叠视频画面）用的样式。
  ///
  /// 这种模式下背景是我们自己画的，所以用**深色骨架 + 浅色底**，
  /// 与视频叠加模式的配色逻辑相反 —— 因为底是我们控制的。
  static const standaloneLight = SkeletonStyle(
    jointColor: Color(0xFF00695C),
    jointUncertainColor: Color(0xFFE65100),
    boneColor: Color(0xFF37474F),
    leftColor: Color(0xFF2E7D32),
    rightColor: Color(0xFF6A1B9A),
    faceColor: Color(0xFF8D6E63),
    outlineColor: Color(0x00000000),   // 不需要描边
    arcColor: Color(0xFFE65100),
    outlineWidth: 0,
  );

  /// 纯骨架模式的深色版。
  static const standaloneDark = SkeletonStyle(
    jointColor: Color(0xFF80CBC4),
    jointUncertainColor: Color(0xFFFFB74D),
    boneColor: Color(0xFFB0BEC5),
    leftColor: Color(0xFF81C784),
    rightColor: Color(0xFFCE93D8),
    faceColor: Color(0xFFBCAAA4),
    outlineColor: Color(0x00000000),
    arcColor: Color(0xFFFFB74D),
    outlineWidth: 0,
  );

  /// 按主题与模式挑样式。
  static SkeletonStyle of({
    required bool dark,
    required bool standalone,
  }) {
    if (standalone) {
      return dark ? standaloneDark : standaloneLight;
    }
    return dark ? SkeletonStyle.dark : SkeletonStyle.light;
  }

  /// 按画布短边算线宽。
  ///
  /// 基准：短边 540（电脑端输出高度）时线宽 2.5。
  /// 下限 1.2 —— 再细在手机上看不见。
  /// 上限 6 —— 再粗会盖住关节，反而看不清位置。
  double lineWidth(double shortestSide) {
    final w = shortestSide / 540 * 2.5 * lineWidthScale;
    return w.clamp(1.2, 6.0);
  }

  /// 按画布短边算关节半径。
  ///
  /// 下限 2.2 —— 保证点还能被看到。
  double jointRadius(double shortestSide) {
    final r = shortestSide / 540 * 4.0 * lineWidthScale;
    return r.clamp(2.2, 9.0);
  }

  /// 按画布短边算角度弧半径。
  double arcRadius(double shortestSide) {
    final r = shortestSide / 540 * 48.0 * lineWidthScale;
    return r.clamp(16.0, 90.0);
  }

  /// 按画布短边算字号。
  double fontSize(double shortestSide) {
    final f = shortestSide / 540 * 15.0 * lineWidthScale;
    return f.clamp(9.0, 26.0);
  }

  SkeletonStyle copyWith({
    bool? showFace,
    bool? showLabels,
    double? lineWidthScale,
  }) =>
      SkeletonStyle(
        jointColor: jointColor,
        jointUncertainColor: jointUncertainColor,
        boneColor: boneColor,
        leftColor: leftColor,
        rightColor: rightColor,
        faceColor: faceColor,
        outlineColor: outlineColor,
        arcColor: arcColor,
        showFace: showFace ?? this.showFace,
        showLabels: showLabels ?? this.showLabels,
        lineWidthScale: lineWidthScale ?? this.lineWidthScale,
        outlineWidth: outlineWidth,
      );

  /// 取某个关键点该用的颜色。
  ///
  /// 规则：
  ///   1. 低置信度 → 用"存疑"色，**不管它在哪一侧** ——
  ///      可信度比左右更重要
  ///   2. 面部的点 → 面部色
  ///   3. 左右侧 → 各自的颜色
  Color colorFor(String name, bool visible) {
    if (!visible) return jointUncertainColor;
    if (faceKeypointsSet.contains(name)) return faceColor;
    if (name.endsWith('_l')) return leftColor;
    if (name.endsWith('_r')) return rightColor;
    return jointColor;
  }

  static const faceKeypointsSet = {
    'nose', 'eye_l', 'eye_r', 'ear_l', 'ear_r',
  };
}
