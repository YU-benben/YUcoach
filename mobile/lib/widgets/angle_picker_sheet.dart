import 'package:flutter/material.dart';

import '../pose/angle_catalog.dart';
import '../pose/angle_selection.dart';

/// 角度选择面板。
///
/// ## 交互设计
///
/// 底部弹出面板 + 复选框列表。只列出**当前视角适用**的角度 ——
/// 列出不适用的（比如在侧面视角下列"膝内扣"）会让用户选了一个
/// 永远不显示的角度，然后以为坏了。
///
/// 每一项都显示：
///   · 中文名
///   · 取值范围提示（"仅侧面"这类）
///   · 一句话说明这个角度看什么
///   · ⚠️ 用推导点的会标出来
///
/// ## 为什么标"推导值"
///
/// 踝角用到了脚尖，而脚尖是几何推导的（蹬离期误差最大）。
/// 不标的话教练会把它当成和别的角度同等可信。
class AnglePickerSheet extends StatefulWidget {
  const AnglePickerSheet({
    super.key,
    required this.selection,
    required this.view,
  });

  final AngleSelection selection;

  /// 当前视角。决定列出哪些角度、以及操作哪一组选择。
  final String view;

  @override
  State<AnglePickerSheet> createState() => _AnglePickerSheetState();
}

class _AnglePickerSheetState extends State<AnglePickerSheet> {
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final available = AngleSelection.availableForView(widget.view);
    final selected = widget.selection.activeForView(widget.view).length;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Text('选择要标注的角度',
                    style: TextStyle(
                        fontSize: 15.5, fontWeight: FontWeight.w600)),
                const SizedBox(width: 8),
                Text('（${_viewZh(widget.view)}视角）',
                    style: TextStyle(
                        fontSize: 12, color: theme.colorScheme.outline)),
                const Spacer(),
                Text('已选 $selected',
                    style: TextStyle(
                        fontSize: 12, color: theme.colorScheme.outline)),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '角度太多会互相遮挡。建议一次看 2~3 个。',
              style: TextStyle(
                  fontSize: 11.5, color: theme.colorScheme.outline),
            ),
            const SizedBox(height: 12),

            // 列表。用 Flexible + ListView 而不是 Column，
            // 因为角度多起来会超出面板高度。
            Flexible(
              child: ListView.builder(
                shrinkWrap: true,
                itemCount: available.length,
                itemBuilder: (context, i) {
                  final a = available[i];
                  final on = widget.selection.isSelected(
                      widget.view, a.metricId);
                  return _AngleTile(
                    def: a,
                    selected: on,
                    onChanged: () => widget.selection.toggle(
                        widget.view, a.metricId),
                  );
                },
              ),
            ),

            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => widget.selection.clear(widget.view),
                    child: const Text('全不选'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () =>
                        widget.selection.selectAll(widget.view),
                    child: const Text('全选'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('完成'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  static String _viewZh(String v) => switch (v) {
        'front' => '正面',
        'back' => '背面',
        _ => '侧面',
      };
}

class _AngleTile extends StatelessWidget {
  const _AngleTile({
    required this.def,
    required this.selected,
    required this.onChanged,
  });

  final AngleDefinition def;
  final bool selected;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return InkWell(
      onTap: onChanged,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 用 Checkbox 而不是 Switch：多个并列选项用勾选框更自然，
            // 开关给人的印象是"开/关某个功能"而不是"选/不选"。
            SizedBox(
              width: 34,
              child: Checkbox(
                value: selected,
                onChanged: (_) => onChanged(),
                visualDensity: VisualDensity.compact,
              ),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          def.nameZh,
                          style: const TextStyle(
                              fontSize: 13.5,
                              fontWeight: FontWeight.w500),
                        ),
                      ),
                      if (def.derived) ...[
                        const SizedBox(width: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 5, vertical: 1),
                          decoration: BoxDecoration(
                            color: theme.colorScheme.tertiaryContainer
                                .withValues(alpha: 0.6),
                            borderRadius: BorderRadius.circular(3),
                          ),
                          child: Text(
                            '推导值',
                            style: TextStyle(
                              fontSize: 9.5,
                              color: theme.colorScheme.tertiary,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    def.description,
                    style: TextStyle(
                      fontSize: 11.5,
                      color: theme.colorScheme.outline,
                      height: 1.4,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 一行摘要：显示当前选了哪些角度，点击可打开选择面板。
///
/// 放在播放器下方。让用户随时能看到"现在标了哪些"，
/// 而不用打开面板去数。
class AngleSummaryBar extends StatelessWidget {
  const AngleSummaryBar({
    super.key,
    required this.selection,
    required this.view,
    required this.onTap,
  });

  final AngleSelection selection;
  final String view;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AnimatedBuilder(
      animation: selection,
      builder: (context, _) {
        final active = selection.activeForView(view);

        return InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(6),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
            child: Row(
              children: [
                Icon(Icons.straighten,
                    size: 16, color: theme.colorScheme.outline),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    active.isEmpty
                        ? '未标注角度（点击选择）'
                        : active.map((a) => a.nameZh).join(' · '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 12.5,
                      color: active.isEmpty
                          ? theme.colorScheme.outline
                          : theme.colorScheme.onSurface,
                    ),
                  ),
                ),
                const Icon(Icons.chevron_right, size: 18),
              ],
            ),
          ),
        );
      },
    );
  }
}
