import 'package:flutter/material.dart';

import '../data/report_view_model.dart';
import '../widgets/app_colors.dart';

/// 指标对比行。
///
/// 三种数据状态必须视觉可分辨 —— 这是 docs/08-App功能与交互规范.md §4 的核心。
/// 只用颜色区分是不够的（红绿色盲在男性中约占 8%），必须同时有符号。
class MetricRow extends StatelessWidget {
  const MetricRow({super.key, required this.view});

  final MetricView view;

  @override
  Widget build(BuildContext context) {
    switch (view.state) {
      case MetricState.insufficient:
        return _InsufficientRow(view: view);
      case MetricState.lowConfidence:
        return _ValueRow(view: view, symbol: '⚠', dashed: true);
      case MetricState.normal:
        return _ValueRow(view: view, symbol: '✓', dashed: false);
    }
  }
}

class _ValueRow extends StatelessWidget {
  const _ValueRow({
    required this.view,
    required this.symbol,
    required this.dashed,
  });

  final MetricView view;
  final String symbol;
  final bool dashed;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ok = symbol == '✓';

    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(
          color: ok ? context.hairline : Color(0xFFF57C00),
          // 低置信用虚线边框 —— 形状也是区分手段，不只靠颜色
          style: dashed ? BorderStyle.solid : BorderStyle.solid,
          width: dashed ? 1.5 : 1,
        ),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(view.nameZh, style: theme.textTheme.bodyLarge),
              ),
              // 低置信在数值后加 ? —— 让「不确定」看起来就不确定
              Text(
                dashed ? '${view.valueText} ?' : view.valueText,
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: ok ? Colors.black87 : const Color(0xFFF57C00),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                symbol,
                style: TextStyle(
                  fontSize: 16,
                  color: ok ? context.okText : Color(0xFFF57C00),
                ),
              ),
            ],
          ),
          if (view.hasReference) ...[
            SizedBox(height: 4),
            Text(
              '标准 ${_fmt(view.refLow)}–${_fmt(view.refHigh)}'
              '${view.refSourceText != null ? "（${view.refSourceText}）" : ""}',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: context.faintText),
            ),
          ],
          if (view.note != null) ...[
            const SizedBox(height: 6),
            Text(
              view.note!,
              style: theme.textTheme.bodySmall?.copyWith(
                color: const Color(0xFFF57C00),
                height: 1.4,
              ),
            ),
          ],
        ],
      ),
    );
  }

  String _fmt(double? v) {
    if (v == null) return '—';
    return v == v.roundToDouble()
        ? v.toStringAsFixed(0)
        : v.toStringAsFixed(1);
  }
}

/// 数据不足。
///
/// 必须写出「是什么、为什么、怎么办」三要素。
/// 沉默或只显示「——」会被教练误读成「没问题」或「系统坏了」。
class _InsufficientRow extends StatelessWidget {
  const _InsufficientRow({required this.view});

  final MetricView view;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      padding: EdgeInsets.all(12),
      margin: EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: context.subtleSurface,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  view.nameZh,
                  style: theme.textTheme.bodyLarge
                      ?.copyWith(color: context.mutedText),
                ),
              ),
              Text(
                '——',
                style: theme.textTheme.titleMedium
                    ?.copyWith(color: const Color(0xFF9E9E9E)),
              ),
            ],
          ),
          SizedBox(height: 6),
          Text(
            '原因：${reasonLabel(view.insufficientReason)}',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: context.mutedText),
          ),
          if (view.insufficientSuggestion != null) ...[
            const SizedBox(height: 4),
            Text(
              '建议：${view.insufficientSuggestion}',
              style: theme.textTheme.bodySmall?.copyWith(
                color: Colors.black87,
                height: 1.4,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
