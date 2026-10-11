import 'package:flutter/material.dart';

import '../data/report_view_model.dart';
// Summary 与 Flutter 的 diagnostic Summary 重名，本文件用不到它
import '../models/models.dart' hide Summary;
import '../widgets/app_colors.dart';

/// 指导解析卡片。
///
/// 结构固定且顺序不可变：标题 → 实测值与标准 → 机制解释 → 处方。
/// 见 docs/09-报告与指导解析规范.md §3.5。
///
/// explanation 必须写「机制」而不是重复现象 —— 教练知道为什么是问题，
/// 才会去改。处方块里的 cue（口令）是最重要的一行：教练在跑道边只有 3 秒，
/// 他只会喊一句口令，不会念动作要领。
class FindingCard extends StatelessWidget {
  const FindingCard({
    super.key,
    required this.finding,
    this.isInsuffcient = false,
  });

  final Finding finding;
  final bool isInsuffcient;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isMajor = finding.severity == FindingSeverity.major;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(
          left: BorderSide(
            color: isInsuffcient
                ? const Color(0xFF9E9E9E)
                : (isMajor ? context.errorText : Color(0xFFF57C00)),
            width: 4,
          ),
        ),
        boxShadow: const [
          BoxShadow(
            color: Color(0x14000000),
            blurRadius: 4,
            offset: Offset(0, 2),
          ),
        ],
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  finding.title,
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              if (!isInsuffcient)
                _SeverityTag(severity: finding.severity)
              else
                const _Tag(text: '未评估', color: Color(0xFF9E9E9E)),
            ],
          ),

          // 实测值 + 标准区间
          if (finding.evidence.isNotEmpty) ...[
            const SizedBox(height: 10),
            ...finding.evidence.map((e) => _EvidenceLine(evidence: e)),
          ],

          // 机制解释
          if (finding.explanation.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              finding.explanation,
              style: theme.textTheme.bodyMedium?.copyWith(height: 1.5),
            ),
          ],

          // 数据不足型：给出原因与建议
          if (isInsuffcient) ...[
            const SizedBox(height: 10),
            if (finding.reason != null)
              _Labeled('原因', reasonLabel(finding.reason)),
            if (finding.required != null)
              _Labeled('要求', finding.required!),
            if (finding.actual != null)
              _Labeled('实际', finding.actual!),
            if (finding.suggestion != null)
              _Labeled('建议', finding.suggestion!, emphasize: true),
          ],

          // 低置信度的明确提示
          if (finding.caveat != null) ...[
            SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: context.warnSurface,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                finding.caveat!,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: context.warnText,
                  height: 1.5,
                ),
              ),
            ),
          ],

          // 处方
          if (finding.drills.isNotEmpty) ...[
            SizedBox(height: 12),
            Text(
              '建议练习',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: context.faintText),
            ),
            const SizedBox(height: 6),
            ...finding.drills.map((d) => _DrillBlock(drill: d)),
          ],
        ],
      ),
    );
  }
}

class _EvidenceLine extends StatelessWidget {
  const _EvidenceLine({required this.evidence});

  final Evidence evidence;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final value = evidence.value;
    final unit = '';

    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Text(
        '实测 ${value is num ? value.toStringAsFixed(1) : value}$unit'
        '${evidence.refLow != null && evidence.refHigh != null ? "，该阶段应有 ${evidence.refLow!.toStringAsFixed(0)}–${evidence.refHigh!.toStringAsFixed(0)}$unit" : ""}'
        '${evidence.deviationText != null ? "（${evidence.deviationText}）" : ""}',
        style: theme.textTheme.bodyMedium?.copyWith(color: Colors.black87),
      ),
    );
  }
}

class _DrillBlock extends StatelessWidget {
  const _DrillBlock({required this.drill});

  final Drill drill;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dose = [
      if (drill.sets != null) drill.sets!,
      if (drill.reps != null) '× ${drill.reps!}',
      if (drill.duration != null) drill.duration!,
    ].join(' ');

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.okSurface,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            drill.name,
            style: theme.textTheme.bodyLarge
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          if (dose.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(dose, style: theme.textTheme.bodySmall),
          ],
          const SizedBox(height: 6),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('口令：',
                  style: TextStyle(fontSize: 14, color: context.mutedText)),
              Expanded(
                child: Text(
                  drill.cue,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w500,
                    height: 1.4,
                  ),
                ),
              ),
            ],
          ),
          if (drill.mechanism != null) ...[
            SizedBox(height: 6),
            Text(
              drill.mechanism!,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: context.mutedText, height: 1.4),
            ),
          ],
        ],
      ),
    );
  }
}

class _Labeled extends StatelessWidget {
  const _Labeled(this.label, this.value, {this.emphasize = false});

  final String label;
  final String value;
  final bool emphasize;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 3),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 40,
              child: Text(label,
                  style: TextStyle(fontSize: 13, color: context.faintText)),
            ),
            Expanded(
              child: Text(
                value,
                style: TextStyle(
                  fontSize: emphasize ? 14 : 13,
                  fontWeight: emphasize ? FontWeight.w500 : FontWeight.normal,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ),
      );
}

class _SeverityTag extends StatelessWidget {
  const _SeverityTag({required this.severity});

  final FindingSeverity severity;

  @override
  Widget build(BuildContext context) => switch (severity) {
        FindingSeverity.major => const _Tag(text: '优先纠正', color: Color(0xFFC62828)),
        FindingSeverity.minor => const _Tag(text: '可改进', color: Color(0xFFF57C00)),
        FindingSeverity.info => const _Tag(text: '观察', color: Color(0xFF616161)),
        FindingSeverity.insufficientData =>
          const _Tag(text: '未评估', color: Color(0xFF9E9E9E)),
      };
}

class _Tag extends StatelessWidget {
  const _Tag({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          border: Border.all(color: color),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Text(
          text,
          style: TextStyle(fontSize: 12, color: color),
        ),
      );
}
