import 'package:flutter/material.dart';

import '../data/athlete_repository.dart';
import '../data/session_repository.dart';
import '../data/auth_service.dart';
import '../data/theme_service.dart';
import '../domain/local_user.dart';
import 'athlete_list_page.dart';
import 'data_page.dart';
import 'login_page.dart';
import 'profile_page.dart';
import 'refreshable.dart';
import 'upload_page.dart';
import 'welcome_page.dart';

/// 应用入口：根据登录状态决定去登录页还是主界面。
///
/// 启动时先读一次本地账号（很快，是本地文件），避免出现
/// 「先闪一下登录页再跳首页」的体验。
class AuthGate extends StatefulWidget {
  const AuthGate({super.key, this.themeService});

  /// 主题服务。为 null 时「我的」页面不显示外观设置入口。
  ///
  /// 为什么用可空参数而不是 required：
  ///   测试里直接构造 AuthGate 时不关心主题，
  ///   强制传会让每个测试都要造一个 ThemeService。
  final ThemeService? themeService;

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  final _auth = AuthService();

  LocalUser? _user;
  bool _ready = false;
  bool _hasAccount = false;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    // 内置管理员账号必须存在，否则 `MazingLIU` 登不进来 ——
    // 本地账号表里没有它，登录时会报"账号或密码错误"。
    //
    // 放在这里而不是注册时：管理员账号不经过注册流程，
    // 它是产品自带的。只创建一次，已存在则不动。
    await _auth.ensureAdminAccount().catchError((_) => false);

    // 读账号与"最短展示时长"**并行**，不是串行。
    //
    // 串行的话总耗时 = 读文件 + 900ms。并行则总耗时 = max(两者)，
    // 欢迎页那 900ms 就把读文件的时间吸收掉了。
    //
    // 用 catchError 而不是 try/catch 包 Future.wait：
    // 账号文件损坏时我们仍要进 App（AuthService 内部已经处理了坏数据），
    // 而不是卡在欢迎页。
    final results = await Future.wait([
      _auth.currentUser().catchError((_) => null),
      _auth.hasAnyAccount().catchError((_) => false),
      Future<void>.delayed(_minWelcome),
    ]);

    if (!mounted) return;
    setState(() {
      _user = results[0] as LocalUser?;
      _hasAccount = results[1] as bool;
      _ready = true;
    });
  }

  static const _minWelcome = Duration(milliseconds: 900);

  Future<void> _afterLogin() async {
    final user = await _auth.currentUser();
    if (!mounted) return;
    setState(() {
      _user = user;
      _hasAccount = true;
    });
  }

  /// 资料被修改后刷新当前用户。
  ///
  /// 为什么需要：LocalUser 是不可变的，修改后会产生**新对象**。
  /// 而 HomeShell 拿到的是旧对象 —— 不刷新的话，改完昵称
  /// 返回主界面还是显示旧名字。
  Future<void> _refreshUser() async {
    final user = await _auth.currentUser();
    if (!mounted) return;
    setState(() => _user = user);
  }

  Future<void> _logout() async {
    await _auth.logout();
    if (!mounted) return;
    setState(() => _user = null);
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) {
      return const WelcomePage();
    }

    final user = _user;
    if (user == null) {
      return LoginPage(
        auth: _auth,
        onLoggedIn: _afterLogin,
        // 装完首次打开，还没有任何账号 —— 直接进注册模式，少点一次
        initialRegisterMode: !_hasAccount,
      );
    }

    return HomeShell(
      user: user,
      athletes: AthleteRepository(teamId: user.teamId),
      sessions: SessionRepository(teamId: user.teamId),
      onLogout: _logout,
      onUserChanged: _refreshUser,
      themeService: widget.themeService,
    );
  }
}

/// 主界面骨架：底部 4 个 Tab。
///
/// Tab 顺序按使用频率排：运动员（最常看）→ 上传（每次训练都用）
/// → 数据（查看历史）→ 我的（最少）。
class HomeShell extends StatefulWidget {
  const HomeShell({
    super.key,
    required this.user,
    required this.athletes,
    required this.sessions,
    required this.onLogout,
    this.onUserChanged,
    this.themeService,
  });

  final LocalUser user;
  final AthleteRepository athletes;
  final SessionRepository sessions;
  final Future<void> Function() onLogout;

  /// 资料被修改后通知外层刷新当前用户。
  ///
  /// 为什么需要：LocalUser 是不可变的，改资料会产生新对象，
  /// 而外层还持有旧对象 —— 不通知的话改完昵称界面不变。
  final Future<void> Function()? onUserChanged;

  /// 主题服务。透传给「我的」页面，那里有外观切换入口。
  final ThemeService? themeService;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  // 用 GlobalKey 拿到子页面的 State，好在切 Tab 时让它重新读数据。
  //
  // 为什么必须这样：IndexedStack 会在启动时**一次性创建全部页面**，
  // 所以每个页面的 initState 只在 App 启动时跑一次。
  // 结果就是「先添加运动员，再切到上传页」时，上传页手里还是启动时读到的
  // 空列表 —— 它会一直显示「请先添加运动员」，而且没有任何办法刷新。
  //
  // 这不是「功能没做完」，是真实缺陷。修法是切 Tab 时显式刷新。
  final _uploadKey = GlobalKey<UploadPageState>();
  final _dataKey = GlobalKey<DataPageState>();

  void _onTabSelected(int i) {
    setState(() => _index = i);

    // 切到哪个页面就刷新哪个 —— 数据可能在别的页面被改过
    // （比如在「运动员」页新增了运动员，在「上传」页保存了记录）
    final state = switch (i) {
      1 => _uploadKey.currentState,
      2 => _dataKey.currentState,
      _ => null,
    };
    if (state is Refreshable) state.reload();
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      AthleteListPage(repository: widget.athletes),
      UploadPage(
        key: _uploadKey,
        athletes: widget.athletes,
        sessions: widget.sessions,
        // 提交分析要带 username 去服务端认账号、扣额度。
        // 服务端不认识 App 的本地账号，必须显式传身份过去。
        user: widget.user,
      ),
      DataPage(
        key: _dataKey,
        athletes: widget.athletes,
        sessions: widget.sessions,
      ),
      ProfilePage(
        user: widget.user,
        onLogout: widget.onLogout,
        onUserChanged: widget.onUserChanged,
        themeService: widget.themeService,
      ),
    ];

    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: _onTabSelected,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.groups_outlined),
            selectedIcon: Icon(Icons.groups),
            label: '运动员',
          ),
          NavigationDestination(
            icon: Icon(Icons.video_call_outlined),
            selectedIcon: Icon(Icons.video_call),
            label: '上传',
          ),
          NavigationDestination(
            icon: Icon(Icons.insights_outlined),
            selectedIcon: Icon(Icons.insights),
            label: '数据',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: '我的',
          ),
        ],
      ),
    );
  }
}
