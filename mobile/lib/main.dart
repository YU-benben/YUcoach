import 'package:flutter/material.dart';

import 'data/theme_service.dart';
import 'pages/app_shell.dart';

void main() {
  runApp(const YuCoachApp());
}

/// 应用入口。
///
/// 启动后由 AuthGate 决定去登录页还是主界面 ——
/// 看本地有没有已登录的账号。
class YuCoachApp extends StatefulWidget {
  const YuCoachApp({super.key});

  @override
  State<YuCoachApp> createState() => _YuCoachAppState();
}

class _YuCoachAppState extends State<YuCoachApp> {
  final _theme = ThemeService();

  @override
  void initState() {
    super.initState();
    // 读一次本地保存的主题偏好。
    // 读完之后 notifyListeners 会让下面的 AnimatedBuilder 重建，
    // 主题随即生效。
    _theme.load();
  }

  @override
  void dispose() {
    _theme.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // 用 AnimatedBuilder 监听主题变化 —— 不引入状态管理库，
    // 一个偏好项不值得为它加依赖。
    return AnimatedBuilder(
      animation: _theme,
      builder: (context, _) => MaterialApp(
        // 显示在系统任务切换器里（Android 的"最近任务"）。
        // 启动器/桌面图标上的名称由平台资源决定，不走这里：
        //   Android -> android/app/src/main/AndroidManifest.xml 的 android:label
        //   Windows -> windows/runner/main.cpp 的窗口标题
        title: 'YUcoach',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: _theme.mode,
        home: AuthGate(themeService: _theme),
      ),
    );
  }
}
