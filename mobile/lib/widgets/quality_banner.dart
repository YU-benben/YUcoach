import 'package:flutter/material.dart';

import '../data/report_view_model.dart';
import '../widgets/app_colors.dart';

/// 报告顶部横幅。
///
/// 拍摄质量分决定免责强度：
///   ≥75  无横幅，附录里说明方法学局限
///   55–74 提示部分指标精度受限
///   <55  明确说明不建议用于训练决策
///
/// 见 docs/09-报告与指导解析规范.md §6.1。
///
/// 为什么必须做这个：教练看到一份数字齐全的报告，会默认它可信。
/// 质量不够时必须显式告知，否则等于用一份不可靠的数据误导训练决策。
class QualityBannerBar extends StatelessWidget {
  const QualityBannerBar({super.key, required this.banner});

  final QualityBanner banner;

  @override
  Widget build(BuildContext context) {
    final (bg, fg, icon) = switch (banner) {
      QualityBanner.referenceOnly => (
          context.errorSurface,
          context.errorText,
          Icons.error_outline,
        ),
      QualityBanner.partial => (
          context.warnSurface,
          context.warnText,
          Icons.warning_amber_outlined,
        ),
      QualityBanner.none => (
          Colors.transparent,
          Colors.transparent,
          Icons.info_outline,
        ),
    };

    if (banner == QualityBanner.none) return const SizedBox.shrink();

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(icon, color: fg, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              qualityBannerText(banner),
              style: TextStyle(
                color: fg,
                fontWeight: FontWeight.w500,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
