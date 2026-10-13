import 'package:flutter/material.dart';

import '../data/auth_service.dart';
import '../data/theme_service.dart';
import '../domain/local_user.dart';
import '../widgets/user_avatar.dart';
import 'membership_page.dart';
import 'profile_edit_page.dart';
import 'server_settings_page.dart';
import 'training_plan_page.dart';
import '../widgets/app_colors.dart';

/// 我的：账号信息与设置。
///
/// 页面结构（从上到下按使用频率排）：
///     账号卡片（可点进编辑资料）
///     └ 会员等级徽标 —— 就在头像下方，一眼能看到
///     训练    → 训练计划（免费功能，独立成栏）
///     会员    → 会员中心（额度 / 兑换码）
///     分析服务
///     数据
///     关于
///     退出登录
///
/// ⚠️ 训练计划为什么**不**放在「会员」栏里：
///    它是对所有用户免费的功能。归类会改变用户的预期 ——
///    放在会员下面，免费用户会以为自己用不了，于是不敢点。
///    这不只是排版问题。
class ProfilePage extends StatefulWidget {
  const ProfilePage({
    super.key,
    required this.user,
    required this.onLogout,
    this.onUserChanged,
    this.themeService,
  });

  final LocalUser user;
  final Future<void> Function() onLogout;

  /// 资料被修改后通知外层刷新。
  ///
  /// 为什么需要：LocalUser 是不可变的，改完资料产生**新对象**，
  /// 而外层还持有旧对象 —— 不通知的话界面不会更新。
  final Future<void> Function()? onUserChanged;

  /// 主题服务。为 null 时不显示外观设置入口。
  final ThemeService? themeService;

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  /// 页面内维护一份用户副本。
  ///
  /// 为什么不直接用 widget.user：改完资料后外层会刷新并传下新的
  /// widget.user，但那要等一个异步往返。本地先更新一次，
  /// 界面立刻有反应，不用等外层。
  late LocalUser _user;

  @override
  void initState() {
    super.initState();
    _user = widget.user;
  }

  @override
  void didUpdateWidget(ProfilePage old) {
    super.didUpdateWidget(old);
    // 外层给了新的用户对象就跟随（例如换了账号）
    if (widget.user.userId != old.user.userId) {
      _user = widget.user;
    }
  }

  final _auth = AuthService();

  Future<void> _editProfile() async {
    final updated = await Navigator.of(context).push<LocalUser>(
      MaterialPageRoute(
        builder: (_) => ProfileEditPage(user: _user, auth: _auth),
      ),
    );
    if (!mounted || updated == null) return;
    setState(() => _user = updated);
    // 通知外层同步 —— 否则切到别的 Tab 再回来会看到旧昵称
    await widget.onUserChanged?.call();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('我的')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _AccountCard(user: _user, onTap: _editProfile),
          const SizedBox(height: 20),

          // 训练计划单独成栏，**不放在会员下面**。
          //
          // 为什么：它是所有人都能免费用的功能，放在「会员」栏里会让人
          // 以为这是会员权益 —— 用户不敢点，或者点了以为要付费。
          // 归类会改变用户对功能的预期，这不只是排版问题。
          _SectionTitle('训练'),
          _NavTile(
            icon: Icons.calendar_month_outlined,
            title: '训练计划',
            subtitle: '在日历上安排每天的训练，可查看当天的分析记录',
            badge: '免费',
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => TrainingPlanPage(user: _user),
              ),
            ),
          ),

          const SizedBox(height: 24),
          // 会员相关放这里 —— 用户关心"我还能用几次"
          _SectionTitle('会员'),
          _NavTile(
            icon: Icons.workspace_premium_outlined,
            title: '会员中心',
            subtitle: '查看额度、用兑换码升级',
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => MembershipPage(user: _user),
              ),
            ),
          ),

          const SizedBox(height: 24),
          _SectionTitle('设置'),
          if (widget.themeService != null) _AppearanceTile(
            service: widget.themeService!,
          ),

          const SizedBox(height: 24),
          _SectionTitle('分析服务'),
          // 分析跑在电脑上（手机算不动），所以需要配置那台电脑的地址。
          _ServerTile(user: _user),

          const SizedBox(height: 24),
          _SectionTitle('数据'),
          const _InfoTile(
            icon: Icons.storage_outlined,
            title: '数据存储位置',
            subtitle: '运动员与分析记录保存在本机，不上传服务器',
          ),
          const _InfoTile(
            icon: Icons.cloud_off_outlined,
            title: '离线可用',
            subtitle: '无网络时也能查看已有记录与分析报告',
          ),

          const SizedBox(height: 24),
          _SectionTitle('关于'),
          // 品牌形象也放在这里 —— 用户在「关于」里确认自己用的是哪个产品
          Center(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(18),
              child: Image.asset(
                'assets/branding/logo.png',
                width: 72,
                height: 72,
                filterQuality: FilterQuality.medium,
              ),
            ),
          ),
          const SizedBox(height: 14),
          const _InfoTile(
            icon: Icons.info_outline,
            title: '版本',
            subtitle: '1.0.0（开发版）',
          ),
          const _InfoTile(
            icon: Icons.science_outlined,
            title: '分析能力',
            subtitle: '二维视频分析，用于技术动作观察与趋势对比。\n'
                '不构成医学诊断，不可用于反推地面反作用力或关节负荷。',
          ),

          const SizedBox(height: 32),
          OutlinedButton.icon(
            onPressed: () => _confirmLogout(context),
            icon: const Icon(Icons.logout),
            label: const Text('退出登录'),
            style: OutlinedButton.styleFrom(
              padding: EdgeInsets.symmetric(vertical: 14),
              foregroundColor: context.errorText,
              side: const BorderSide(color: Color(0xFFEF9A9A)),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '退出后本地数据仍然保留，重新登录即可看到。',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 11, color: context.faintText),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Future<void> _confirmLogout(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('退出登录'),
        content: const Text('退出后需要重新输入手机号和密码。\n\n'
            '运动员信息与分析记录仍保存在本机，不会丢失。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('退出'),
          ),
        ],
      ),
    );
    if (ok == true) await widget.onLogout();
  }
}

/// 账号卡片：头像 + 昵称 + 手机号 + 会员徽标。
class _AccountCard extends StatelessWidget {
  const _AccountCard({required this.user, required this.onTap});

  final LocalUser user;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Container(
        padding: EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: context.subtleSurface,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            UserAvatar(avatarId: user.avatarId, radius: 28),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          user.name.isEmpty ? '未命名' : user.name,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 17, fontWeight: FontWeight.w600),
                        ),
                      ),
                      if (user.role.isNotEmpty) ...[
                        const SizedBox(width: 8),
                        _RoleBadge(role: user.role),
                      ],
                    ],
                  ),
                  const SizedBox(height: 3),
                  Text(
                    user.phone,
                    style: TextStyle(
                        fontSize: 13, color: context.mutedText),
                  ),
                  const SizedBox(height: 7),
                  // 会员等级就在头像下方 —— 用户一眼能看到自己的身份
                  _TierBadge(),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: context.hairline),
          ],
        ),
      ),
    );
  }
}

/// 身份徽标（家长 / 教练员 / 运动员）。
class _RoleBadge extends StatelessWidget {
  const _RoleBadge({required this.role});
  final String role;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: 7, vertical: 1.5),
      decoration: BoxDecoration(
        color: context.okSurface,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        role,
        style: const TextStyle(fontSize: 10.5, color: Color(0xFF2E7D32)),
      ),
    );
  }
}

/// 会员等级徽标。
///
/// ⚠️ 现在固定显示「普通用户」。
///    等会员体系接进 App 后改成读服务端返回的等级 —— 那时这个组件
///    只需要换一个入参，不用改布局。
class _TierBadge extends StatelessWidget {
  const _TierBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 2.5),
      decoration: BoxDecoration(
        color: context.warnSurface,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: context.hairline),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.person_outline, size: 12, color: Color(0xFFF57F17)),
          SizedBox(width: 4),
          Text(
            '普通用户',
            style: TextStyle(fontSize: 10.5, color: Color(0xFFF57F17)),
          ),
        ],
      ),
    );
  }
}

/// 外观（主题）切换。
///
/// 做成三个单选项而不是一个开关：开关只能表达"浅色/深色"，
/// 无法回到"跟随系统" —— 而那是默认状态，用户改完想回去就找不到了。
class _AppearanceTile extends StatefulWidget {
  const _AppearanceTile({required this.service});

  final ThemeService service;

  @override
  State<_AppearanceTile> createState() => _AppearanceTileState();
}

class _AppearanceTileState extends State<_AppearanceTile> {
  @override
  Widget build(BuildContext context) {
    // 监听服务：主题可能在别处被改（将来可能加"日落自动切深色"）
    return AnimatedBuilder(
      animation: widget.service,
      builder: (context, _) => Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.brightness_6_outlined,
                    size: 20, color: context.faintText),
                const SizedBox(width: 12),
                const Text('外观', style: TextStyle(fontSize: 14)),
                const Spacer(),
                Text(
                  ThemeService.label(widget.service.mode),
                  style: TextStyle(
                    fontSize: 12,
                    color: Theme.of(context).colorScheme.outline,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Padding(
              padding: const EdgeInsets.only(left: 32),
              child: SegmentedButton<ThemeMode>(
                showSelectedIcon: false,
                segments: const [
                  ButtonSegment(
                    value: ThemeMode.system,
                    label: Text('跟随系统'),
                    icon: Icon(Icons.brightness_auto_outlined, size: 15),
                  ),
                  ButtonSegment(
                    value: ThemeMode.light,
                    label: Text('浅色'),
                    icon: Icon(Icons.light_mode_outlined, size: 15),
                  ),
                  ButtonSegment(
                    value: ThemeMode.dark,
                    label: Text('深色'),
                    icon: Icon(Icons.dark_mode_outlined, size: 15),
                  ),
                ],
                selected: {widget.service.mode},
                onSelectionChanged: (s) =>
                    widget.service.setMode(s.first),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 可点击的导航行。
class _NavTile extends StatelessWidget {
  const _NavTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
    this.badge,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  /// 徽标文字。目前用于标「免费」——
  /// 明确告诉用户这个功能不需要会员，他才敢点。
  final String? badge;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: 10, horizontal: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 20, color: context.okText),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(title,
                            style: const TextStyle(fontSize: 14)),
                      ),
                      if (badge != null) ...[
                        SizedBox(width: 7),
                        Container(
                          padding: EdgeInsets.symmetric(
                              horizontal: 6, vertical: 1),
                          decoration: BoxDecoration(
                            color: context.okSurface,
                            borderRadius: BorderRadius.circular(3),
                            border:
                                Border.all(color: context.hairline),
                          ),
                          child: Text(
                            badge!,
                            style: const TextStyle(
                                fontSize: 10, color: Color(0xFF2E7D32)),
                          ),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: TextStyle(
                        fontSize: 12, color: context.mutedText, height: 1.4),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: context.hairline),
          ],
        ),
      ),
    );
  }
}

/// 分析服务的连接入口。
///
/// 做成可点击的一行而不是只读信息：它是 App 里唯一需要手工配置的项，
/// 放在设置页最容易被找到的位置。
class _ServerTile extends StatefulWidget {
  const _ServerTile({required this.user});

  final LocalUser user;

  @override
  State<_ServerTile> createState() => _ServerTileState();
}

class _ServerTileState extends State<_ServerTile> {
  final _settings = ServerSettings();
  String? _url;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final u = await _settings.baseUrl();
    if (!mounted) return;
    setState(() => _url = u);
  }

  @override
  Widget build(BuildContext context) {
    final configured = _url != null && _url!.isNotEmpty;

    return InkWell(
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ServerSettingsPage(settings: _settings),
          ),
        );
        await _load();
      },
      child: Padding(
        padding: EdgeInsets.only(bottom: 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              configured ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
              size: 20,
              color: configured
                  ? context.okText
                  : context.warnText,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('连接分析服务',
                      style: TextStyle(fontSize: 14)),
                  SizedBox(height: 2),
                  Text(
                    configured
                        ? _url!
                        : '未设置。分析在电脑上运行，需要填写它的地址。',
                    style: TextStyle(
                      fontSize: 12,
                      color: configured
                          ? context.mutedText
                          : context.warnText,
                      height: 1.5,
                    ),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: context.hairline),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(
          text,
          style: TextStyle(fontSize: 13, color: context.faintText),
        ),
      );
}

class _InfoTile extends StatelessWidget {
  const _InfoTile({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 20, color: context.faintText),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: const TextStyle(fontSize: 14)),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: TextStyle(
                      fontSize: 12,
                      color: context.mutedText,
                      height: 1.5,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
}
