import 'package:flutter/material.dart';

import '../data/local_store.dart';

/// 主题模式：跟随系统 / 浅色 / 深色。
///
/// ## 为什么默认"跟随系统"
///
/// 手机上绝大多数 App 都跟随系统，用户也习惯了。
/// 默认给"浅色"的话，一个开了深色模式的用户打开 App 会被晃一下眼睛 ——
/// 而这个 App 常在傍晚的训练场用。
///
/// ## 为什么存本地而不是服务端
///
/// 这是显示偏好，和设备相关：同一个人可能在手机上调深色、
/// 在平板上用浅色。存服务端反而会让两边互相覆盖。
class ThemeService extends ChangeNotifier {
  ThemeService({LocalStore? store})
      : _store = store ?? LocalStore(fileName: 'settings.json');

  final LocalStore _store;

  static const _key = 'theme_mode';

  ThemeMode _mode = ThemeMode.system;
  ThemeMode get mode => _mode;

  /// 从本地读一次。App 启动时调用。
  ///
  /// ⚠️ 读失败时保持默认值（跟随系统），而不是抛异常 ——
  ///    一个存坏的主题偏好不该让 App 起不来。
  Future<void> load() async {
    try {
      final doc = await _store.read();
      final raw = doc[_key] as String?;
      _mode = _parse(raw);
      notifyListeners();
    } catch (_) {
      // 保持默认
    }
  }

  Future<void> setMode(ThemeMode mode) async {
    if (_mode == mode) return;
    _mode = mode;
    notifyListeners();
    try {
      final doc = await _store.read();
      doc[_key] = _name(mode);
      await _store.write(doc);
    } catch (_) {
      // 写失败只影响下次启动的默认值，当前这次切换仍然生效。
      // 不弹错误 —— 用户改个主题却看到报错会很困惑。
    }
  }

  static ThemeMode _parse(String? s) => switch (s) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };

  static String _name(ThemeMode m) => switch (m) {
        ThemeMode.light => 'light',
        ThemeMode.dark => 'dark',
        ThemeMode.system => 'system',
      };

  /// 界面显示用的名称。
  static String label(ThemeMode m) => switch (m) {
        ThemeMode.light => '浅色',
        ThemeMode.dark => '深色',
        ThemeMode.system => '跟随系统',
      };
}

/// 主题定义的唯一来源。
///
/// ⚠️ 浅色和深色**必须用同一个种子色**。
///    否则两套主题的配色关系不一致（同一个语义色在浅色下是绿、
///    在深色下变成蓝），用户切换时会觉得"这不是同一个 App"。
class AppTheme {
  const AppTheme._();

  /// 品牌主色。整个 App 的配色都从它派生。
  static const seed = Color(0xFF2E7D32);

  static ThemeData light() => _build(Brightness.light);

  static ThemeData dark() => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(
      seedColor: seed,
      brightness: brightness,
    );

    return ThemeData(
      colorScheme: scheme,
      useMaterial3: true,
      // 输入框统一用描边样式，表单看起来更整齐
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        isDense: true,
      ),
      // 卡片圆角统一。不设的话不同组件的默认圆角不一致，
      // 界面看起来像拼起来的。
      cardTheme: CardThemeData(
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
        ),
      ),
    );
  }
}
