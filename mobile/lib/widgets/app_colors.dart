import 'package:flutter/material.dart';

/// 语义颜色。
///
/// ## 为什么需要这个文件
///
/// 整个 App 原来用了 130+ 处硬编码颜色（`Colors.black54`、
/// `Color(0xFFF1F8E9)` 这类）。它们在浅色主题下没问题，
/// 但在深色主题下会出两类问题：
///
///   1. **看不清**：`Colors.black54` 在深色背景上几乎不可见
///   2. **刺眼**：浅绿的卡片底色在深色界面上像一块发光的补丁
///
/// 逐个改会漏，而且以后写新代码还会继续用硬编码。
/// 所以统一走这里：**按语义取名**，由主题决定实际颜色。
///
/// ## 用法
///
/// ```dart
/// Text('说明', style: TextStyle(color: context.mutedText))
/// Container(decoration: BoxDecoration(color: context.okSurface))
/// ```
///
/// ⚠️ 取色用的是 `Theme.of(context)`，所以必须在 build 里调用 ——
///    不能在 initState 里调。
extension AppColors on BuildContext {
  ColorScheme get _scheme => Theme.of(this).colorScheme;

  /// 次要文字（原来是 Colors.black54）。
  ///
  /// 映射到 outline —— Material 3 里它就是"次要内容"的语义色，
  /// 深浅两套主题下都已调好对比度。
  Color get mutedText => _scheme.outline;

  /// 更弱的文字，用于"次要说明的次要说明"（原来是 Colors.black38/45）。
  ///
  /// 再弱一档不能直接用 outline 的透明版 —— 在深色下会糊掉。
  /// 用 onSurfaceVariant 并降一点不透明度，两套主题都还能读。
  Color get faintText => _scheme.onSurfaceVariant.withValues(alpha: 0.72);

  /// 分隔线 / 描边（原来是 Color(0xFFEEEEEE) 这类）。
  Color get hairline => _scheme.outlineVariant;

  /// 中性底色（原来是 Color(0xFFF5F5F5)）。
  Color get subtleSurface =>
      _scheme.surfaceContainerHighest.withValues(alpha: 0.6);

  /// 强调底色 —— 用于"提示/说明"类卡片（原来是浅绿 F1F8E9）。
  Color get okSurface => _scheme.primaryContainer.withValues(alpha: 0.45);

  /// 强调文字（原来自定义的那些深绿 2E7D32 / 33691E）。
  Color get okText => _scheme.primary;

  /// 警示底色（原来是浅黄 FFF8E1 / FFF3E0）。
  ///
  /// ⚠️ 用 tertiary 而不是 secondary：Material 3 的 secondary
  ///    是从主色派生的近邻色，和 primary 太像，做警示区分不出来。
  Color get warnSurface => _scheme.tertiaryContainer.withValues(alpha: 0.55);

  /// 警示文字（原来是 E65100 / F57F17）。
  Color get warnText => _scheme.tertiary;

  /// 错误底色（原来是 FFEBEE / FBE9E7）。
  Color get errorSurface => _scheme.errorContainer.withValues(alpha: 0.5);

  /// 错误文字（原来是 C62828 / E64A19）。
  Color get errorText => _scheme.error;

  /// 图表/标记用的高亮色（原来是 E64A19 那个橙点）。
  Color get accentMark => _scheme.tertiary;
}

/// 固定的品牌色。**不随主题变**。
///
/// 只在少数地方需要：品牌 logo 的背景、欢迎页的深绿底。
/// 这些是"无论深浅都要保持品牌识别"的元素，
/// 跟着主题变反而会失去识别度。
class BrandColors {
  const BrandColors._();

  static const green = Color(0xFF2E7D32);
  static const deepGreen = Color(0xFF0E4B3C);
  static const mint = Color(0xFF7FD1AE);
}
