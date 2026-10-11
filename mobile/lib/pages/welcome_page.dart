import 'package:flutter/material.dart';

/// 开机欢迎页。
///
/// ## 为什么需要它
///
/// 启动时 App 要先读本地账号文件，才知道该去登录页还是首页。
/// 这个读取虽然快（本地文件），但不是零耗时 —— 原来的实现是
/// 显示一个转圈的空页面，用户看到的是"白屏 + 转圈"。
///
/// 改成欢迎页之后，这段等待时间变成了**有意义的一屏**：
/// 用户知道这是 YUcoach，也知道它在做什么。
///
/// ## 为什么要显示昵称
///
/// 「笨笨鱼，你的专属田径教练」比「YUcoach」更像在对人说话。
/// 已登录用户会看到自己的昵称，未登录或未设昵称时用默认称呼。
///
/// ⚠️ 品牌文案放在这里而不是散落在各页面：
///    将来要改只改一处。品牌名多次重复且不一致是很常见的问题。
class WelcomePage extends StatefulWidget {
  const WelcomePage({
    super.key,
    this.name,
    this.minDuration = const Duration(milliseconds: 900),
  });

  /// 用户昵称。为空时用默认称呼。
  final String? name;

  /// 最短展示时长。
  ///
  /// 为什么要"最短"而不是"读完就切"：
  ///   本地读文件只要几十毫秒，欢迎页会一闪而过 ——
  ///   比白屏更难受，像闪屏故障。
  ///   给一个下限让它稳定地停留一下。
  final Duration minDuration;

  /// 默认称呼。用户没设昵称时用它。
  static const defaultName = '笨笨鱼';

  /// 副标题。这是产品的定位说明。
  static const tagline = '你的专属田径教练';

  @override
  State<WelcomePage> createState() => _WelcomePageState();
}

class _WelcomePageState extends State<WelcomePage>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 700),
    );
    _c.forward();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final name = (widget.name == null || widget.name!.trim().isEmpty)
        ? WelcomePage.defaultName
        : widget.name!.trim();

    // 淡入 + 轻微上浮。幅度刻意做小 ——
    // 训练场的手机可能性能一般，动画太重会掉帧，
    // 而掉帧的欢迎页比不做动画更显廉价。
    final fade = CurvedAnimation(parent: _c, curve: Curves.easeOut);
    final slide = Tween<double>(begin: 12, end: 0).animate(fade);

    return Scaffold(
      backgroundColor: const Color(0xFF0E4B3C),
      body: Center(
        child: FadeTransition(
          opacity: fade,
          child: AnimatedBuilder(
            animation: slide,
            builder: (context, child) => Transform.translate(
              offset: Offset(0, slide.value),
              child: child,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // 图标用内置的，不额外打包图片资源 ——
                // 一张图要处理多分辨率适配，而这里一个矢量图标就够。
                Container(
                  width: 92,
                  height: 92,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.12),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.directions_run,
                    size: 52,
                    color: Color(0xFF7FD1AE),
                  ),
                ),
                const SizedBox(height: 26),

                // 主标题：昵称 + 身份定位
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 32),
                  child: Text(
                    '$name，${WelcomePage.tagline}',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 22,
                      height: 1.45,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
                const SizedBox(height: 10),

                Text(
                  'YUcoach 跑姿分析',
                  style: TextStyle(
                    fontSize: 13,
                    color: Colors.white.withValues(alpha: 0.62),
                    letterSpacing: 1.2,
                  ),
                ),
                const SizedBox(height: 46),

                // 进度指示。做得很细，是为了"说明在加载"而不是抢注意力。
                SizedBox(
                  width: 96,
                  child: LinearProgressIndicator(
                    minHeight: 2,
                    backgroundColor: Colors.white.withValues(alpha: 0.14),
                    valueColor: const AlwaysStoppedAnimation(
                      Color(0xFF7FD1AE),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
