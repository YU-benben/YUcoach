import 'package:flutter/material.dart';

import '../pose/angle_catalog.dart';
import '../pose/angle_painter.dart';
import '../pose/angle_selection.dart';
import '../pose/foot_derivation.dart';
import '../pose/skeleton_painter.dart';
import '../pose/skeleton_style.dart';

/// 骨架视图。
///
/// ## 两种模式
///
/// | 模式 | 用途 |
/// |---|---|
/// | 叠加（overlay） | 骨骼叠在视频帧上。教练能看到跑道、起跑器、真实场地 |
/// | 纯骨架（standalone） | 只有骨骼 + 地面参考线。小屏上看关节关系清楚得多 |
///
/// 用户可切换 —— 两种都能用上，不是二选一。
///
/// ## 为什么自己做而不是用现成组件
///
/// 没有现成组件能画"带质量码的骨架 + 角度弧 + 竖直参考线"。
/// 而且自己画能完全控制样式（左右分色、低置信度空心点等）。
class SkeletonView extends StatefulWidget {
  const SkeletonView({
    super.key,
    required this.derived,
    this.aspectRatio = 16 / 9,
    this.background,
    this.angleSelection,
    this.view = 'side',
    this.initialMode = SkeletonMode.standalone,
  });

  /// 当前帧（含推导的足部点）。
  final DerivedFrame derived;

  final double aspectRatio;

  /// 背景（视频帧）。为 null 时自动用纯骨架模式。
  ///
  /// ⚠️ 目前传不了真视频帧 —— Flutter 侧还没有从视频取单帧的 API
  ///    （取帧通道给的是 JPEG 字节，需要解码成 ui.Image 再传进来）。
  ///    所以界面上的"叠加模式"暂时显示为"骨骼画在深色底上"。
  ///    这是**已知的未完成项**，不是 bug。
  final Widget? background;

  /// 角度选择。为 null 时不画角度弧。
  final AngleSelection? angleSelection;

  /// 当前视角。决定画哪些角度、以及左右判读。
  final String view;

  final SkeletonMode initialMode;

  @override
  State<SkeletonView> createState() => _SkeletonViewState();
}

enum SkeletonMode {
  /// 只看骨架。
  standalone,

  /// 叠加（有背景时才有意义）。
  overlay,
}

class _SkeletonViewState extends State<SkeletonView> {
  late SkeletonMode _mode = widget.background == null
      ? SkeletonMode.standalone
      : widget.initialMode;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final standalone = _mode == SkeletonMode.standalone;

    final style = SkeletonStyle.of(dark: dark, standalone: standalone);

    return Column(
      children: [
        AspectRatio(
          aspectRatio: widget.aspectRatio,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Container(
              // 纯骨架模式的底。叠加模式有背景图，这个色不生效。
              color: dark
                  ? const Color(0xFF121212)
                  : const Color(0xFFF7F7F7),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (_mode == SkeletonMode.overlay &&
                      widget.background != null)
                    widget.background!,

                  // ---- 纯骨架模式：地面参考线 ----
                  if (standalone)
                    CustomPaint(
                      painter: GroundReferencePainter(
                        frame: widget.derived.frame,
                        dark: dark,
                      ),
                    ),

                  // ---- 骨架 ----
                  CustomPaint(
                    painter: SkeletonPainter(
                      frame: widget.derived.frame,
                      style: style,
                    ),
                  ),

                  // ---- 角度弧 ----
                  if (widget.angleSelection != null)
                    _angleLayer(style, dark),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        _modeSwitcher(),
      ],
    );
  }

  /// 角度弧图层。
  ///
  /// 单独一个 `AnimatedBuilder` 监听选择变化 ——
  /// 用户勾选角度时只重建这一层，不重建整个骨架。
  Widget _angleLayer(SkeletonStyle style, bool dark) {
    final sel = widget.angleSelection!;
    return AnimatedBuilder(
      animation: sel,
      builder: (context, _) {
        final active = sel.activeForView(widget.view);
        if (active.isEmpty) return const SizedBox.shrink();

        final toDraw = <AngleToDraw>[];
        for (final def in active) {
          final arc = arcPointsFor(def, widget.derived);
          if (arc == null) continue;
          final v = computeAngle(def, widget.derived);
          if (v == null) continue;
          toDraw.add(AngleToDraw(
            definition: def,
            arc: arc,
            value: v,
            // 用推导点的角度标出来 —— 不让教练把它当成同等可信
            label: def.derived ? '${v.toStringAsFixed(0)}°*' : null,
          ));
        }
        if (toDraw.isEmpty) return const SizedBox.shrink();

        return CustomPaint(
          painter: AngleArcPainter(angles: toDraw, style: style),
        );
      },
    );
  }

  /// 模式切换。
  ///
  /// 没有背景时不给切换 —— 切了也看不出差别，
  /// 反而让用户以为功能坏了。
  Widget _modeSwitcher() {
    if (widget.background == null) {
      return const SizedBox.shrink();
    }

    return SegmentedButton<SkeletonMode>(
      showSelectedIcon: false,
      style: const ButtonStyle(
        visualDensity: VisualDensity.compact,
      ),
      segments: const [
        ButtonSegment(
          value: SkeletonMode.overlay,
          label: Text('叠加视频', style: TextStyle(fontSize: 11.5)),
          icon: Icon(Icons.video_settings_outlined, size: 14),
        ),
        ButtonSegment(
          value: SkeletonMode.standalone,
          label: Text('只看骨架', style: TextStyle(fontSize: 11.5)),
          icon: Icon(Icons.accessibility_new, size: 14),
        ),
      ],
      selected: {_mode},
      onSelectionChanged: (s) => setState(() => _mode = s.first),
    );
  }
}
