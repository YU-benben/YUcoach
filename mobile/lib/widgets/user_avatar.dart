import 'package:flutter/material.dart';

/// 内置头像。
///
/// ## 为什么用内置图标而不是让用户传图片
///
/// 三个理由，都是实际会踩到的：
///
///   1. 手机上选图片要处理**存储权限**、裁剪框、压缩、EXIF 旋转 ——
///      是几百行代码，而且每个安卓版本行为都不一样。
///
///   2. 图片存在本地，换手机就丢了；存服务端又要做文件上传接口、
///      容量限制、清理策略。而这些工作量换来的只是"头像能自定义"。
///
///   3. 教练在训练场用头像的目的是**快速认出是谁** ——
///      一组颜色鲜明的示意图标完全够用，甚至比一张模糊自拍更快认。
///
/// 如果将来确实需要自定义头像，加一个 `avatar_file` 字段即可，
/// 不影响已有数据（`avatarId` 继续作为回退）。
///
/// ## 为什么用 Material 图标而不是打包 PNG
///
/// 一张 PNG 要处理 1x/2x/3x 三套分辨率；矢量图标是字体，
/// 自动适配所有屏幕密度，而且不额外占包体积。
class AvatarCatalog {
  const AvatarCatalog._();

  /// 全部可选头像。id 会存进账号文件，**不要随意改已有 id** ——
  /// 改了老用户就会显示成默认头像。
  static const items = <AvatarOption>[
    AvatarOption('fish', '小鱼', Icons.set_meal_outlined, Color(0xFF00897B)),
    AvatarOption('runner', '跑者', Icons.directions_run, Color(0xFFE64A19)),
    AvatarOption('bolt', '闪电', Icons.bolt, Color(0xFFF9A825)),
    AvatarOption('medal', '奖牌', Icons.emoji_events_outlined,
        Color(0xFF6A1B9A)),
    AvatarOption('stopwatch', '秒表', Icons.timer_outlined,
        Color(0xFF1565C0)),
    AvatarOption('mountain', '山峰', Icons.landscape_outlined,
        Color(0xFF2E7D32)),
    AvatarOption('star', '星标', Icons.star_outline, Color(0xFF00838F)),
    AvatarOption('whistle', '哨子', Icons.sports_outlined,
        Color(0xFF4E342E)),
  ];

  /// 按 id 取头像。找不到时返回默认的 ——
  /// 不抛异常，因为一个存坏的 id 不该让整个页面崩掉。
  static AvatarOption byId(String? id) {
    for (final a in items) {
      if (a.id == id) return a;
    }
    return items.first;
  }

  static const defaultId = 'fish';
}

/// 一个可选头像。
class AvatarOption {
  const AvatarOption(this.id, this.label, this.icon, this.color);

  final String id;
  final String label;
  final IconData icon;
  final Color color;
}

/// 头像显示组件。
///
/// 统一走这个组件，而不是各处自己画 CircleAvatar ——
/// 否则"有的地方显示图标、有的地方显示首字"这种不一致迟早出现。
class UserAvatar extends StatelessWidget {
  const UserAvatar({
    super.key,
    required this.avatarId,
    this.radius = 26,
    this.onTap,
  });

  final String avatarId;
  final double radius;

  /// 传入则可点击（用于跳转到资料编辑）。
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final opt = AvatarCatalog.byId(avatarId);

    final circle = Container(
      width: radius * 2,
      height: radius * 2,
      decoration: BoxDecoration(
        // 用头像主色的浅色版做底，深色版做图标 ——
        // 保证任何头像在浅色和深色主题下都有足够对比度。
        color: opt.color.withValues(alpha: 0.14),
        shape: BoxShape.circle,
        border: Border.all(color: opt.color.withValues(alpha: 0.35), width: 1.5),
      ),
      child: Icon(opt.icon, size: radius * 1.05, color: opt.color),
    );

    if (onTap == null) return circle;
    return InkWell(
      onTap: onTap,
      customBorder: const CircleBorder(),
      child: circle,
    );
  }
}

/// 头像选择器。用于资料编辑页。
class AvatarPicker extends StatelessWidget {
  const AvatarPicker({
    super.key,
    required this.selectedId,
    required this.onSelected,
  });

  final String selectedId;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 14,
      runSpacing: 14,
      children: [
        for (final opt in AvatarCatalog.items)
          _AvatarChoice(
            option: opt,
            selected: opt.id == selectedId,
            onTap: () => onSelected(opt.id),
          ),
      ],
    );
  }
}

class _AvatarChoice extends StatelessWidget {
  const _AvatarChoice({
    required this.option,
    required this.selected,
    required this.onTap,
  });

  final AvatarOption option;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      // 无障碍标签 —— 头像只有图标，读屏软件读不出它是什么。
      label: '头像：${option.label}${selected ? "（已选）" : ""}',
      selected: selected,
      button: true,
      child: InkWell(
        onTap: onTap,
        customBorder: const CircleBorder(),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 54,
              height: 54,
              decoration: BoxDecoration(
                color: option.color.withValues(alpha: selected ? 0.22 : 0.10),
                shape: BoxShape.circle,
                border: Border.all(
                  color: selected
                      ? option.color
                      : option.color.withValues(alpha: 0.22),
                  width: selected ? 2.5 : 1.2,
                ),
              ),
              child: Icon(option.icon, size: 27, color: option.color),
            ),
            const SizedBox(height: 4),
            Text(
              option.label,
              style: TextStyle(
                fontSize: 10.5,
                color: selected ? option.color : Colors.black45,
                fontWeight: selected ? FontWeight.w600 : FontWeight.normal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
