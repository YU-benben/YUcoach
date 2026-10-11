import '../data/local_store.dart';
import '../domain/local_user.dart';

/// 认证失败的原因。用枚举而不是异常消息 —— 界面需要据此显示不同提示。
enum AuthError {
  /// 手机号格式不对
  invalidPhone,

  /// 用户名格式不对
  invalidUsername,

  /// 密码太短
  weakPassword,

  /// 两次输入的密码不一致
  passwordMismatch,

  /// 该手机号已注册
  phoneTaken,

  /// 该用户名已被占用
  usernameTaken,

  /// 手机号或密码错误
  wrongCredentials,

  /// 还没有注册过任何账号
  notRegistered,
}

extension AuthErrorText on AuthError {
  String get message => switch (this) {
        AuthError.invalidPhone => '请输入 11 位手机号',
        AuthError.invalidUsername => '用户名需 2–24 位，可用字母、数字、下划线',
        AuthError.weakPassword => '密码至少 6 位',
        AuthError.passwordMismatch => '两次输入的密码不一致',
        AuthError.phoneTaken => '该手机号已注册，请直接登录',
        AuthError.usernameTaken => '该用户名已被占用，换一个试试',
        AuthError.wrongCredentials => '账号或密码错误',
        AuthError.notRegistered => '还没有账号，请先注册',
      };
}

class AuthResult {
  const AuthResult.success(this.user) : error = null;
  const AuthResult.failure(this.error) : user = null;

  final LocalUser? user;
  final AuthError? error;

  bool get ok => user != null;
}

/// 本地账号服务。
///
/// 对外只暴露「注册 / 登录 / 当前用户 / 退出」四件事，
/// 界面不关心它背后是本地文件还是服务端接口。
/// 后端就绪后换实现即可，界面不动。
class AuthService {
  AuthService({LocalStore? store})
      : _store = store ?? LocalStore(fileName: 'users.json');

  final LocalStore _store;

  static const _currentUserKey = 'current_user_id';

  // -- 校验 ---------------------------------------------------------------

  /// 手机号规则：11 位数字，1 开头。够用即可，不做运营商号段校验 ——
  /// 那会把一些真实号码挡在门外，得不偿失。
  static bool isValidPhone(String phone) =>
      RegExp(r'^1\d{10}$').hasMatch(phone.trim());

  /// 用户名规则：2–24 位，字母 / 数字 / 下划线 / 连字符。
  ///
  /// 为什么允许字母开头的纯字母用户名：
  ///   服务端的管理员账号就是这种形式（例如 `MazingLIU`）。
  ///   只允许数字或强制字母开头会让这类账号无法在 App 里登录 ——
  ///   这是真实发生过的缺陷。
  static bool isValidUsername(String name) =>
      RegExp(r'^[A-Za-z0-9_-]{2,24}$').hasMatch(name.trim());

  /// 判断用户输入的是手机号还是用户名。
  ///
  /// 登录框只有一个输入框 —— 让用户先选"用手机号还是用户名"是多余的：
  /// 输入内容本身已经说明了类型。
  static bool looksLikePhone(String s) =>
      RegExp(r'^\d+$').hasMatch(s.trim());

  // -- 注册 ---------------------------------------------------------------

  /// 注册。手机号与用户名**二选一**（至少填一个）。
  ///
  /// 为什么保留两种：教练用手机号最自然（记得住）；
  /// 但有些账号天生没有手机号（比如给管理员用的账号），
  /// 强制手机号会把它们挡在门外。
  Future<AuthResult> register({
    String phone = '',
    String username = '',
    required String name,
    required String password,
    required String passwordConfirm,
  }) async {
    final p = phone.trim();
    final u = username.trim();

    if (p.isEmpty && u.isEmpty) {
      return const AuthResult.failure(AuthError.invalidPhone);
    }
    if (p.isNotEmpty && !isValidPhone(p)) {
      return const AuthResult.failure(AuthError.invalidPhone);
    }
    if (u.isNotEmpty && !isValidUsername(u)) {
      return const AuthResult.failure(AuthError.invalidUsername);
    }
    if (password.length < 6) {
      return const AuthResult.failure(AuthError.weakPassword);
    }
    if (password != passwordConfirm) {
      return const AuthResult.failure(AuthError.passwordMismatch);
    }

    final users = await _loadUsers();
    if (p.isNotEmpty && users.any((x) => x.phone == p)) {
      return const AuthResult.failure(AuthError.phoneTaken);
    }
    if (u.isNotEmpty && users.any((x) => x.username == u)) {
      return const AuthResult.failure(AuthError.usernameTaken);
    }

    final salt = PasswordHasher.newSalt();
    final stamp = DateTime.now().millisecondsSinceEpoch;
    final user = LocalUser(
      userId: 'u_$stamp',
      phone: p,
      username: u,
      name: name.trim().isEmpty ? (p.isNotEmpty ? p : u) : name.trim(),
      // 队伍 id 用注册时间生成。目前一人一队；将来支持「加入已有队伍」时
      // 这个字段改为由邀请码决定，不影响其他逻辑。
      teamId: 't_$stamp',
      passwordSalt: salt,
      passwordHash: PasswordHasher.hash(password, salt),
      createdAt: DateTime.now().toIso8601String(),
    );

    users.add(user);
    await _saveUsers(users);
    await _setCurrentUser(user.userId);

    return AuthResult.success(user);
  }

  // -- 登录 ---------------------------------------------------------------

  /// 登录。`loginId` 可以是手机号**或**用户名。
  ///
  /// 为什么不分成两个参数：登录框只有一个输入框。
  /// 让用户先选"用手机号还是用户名"是多余的 —— 输入内容本身就说明了类型。
  Future<AuthResult> login({
    required String loginId,
    required String password,
  }) async {
    final id = loginId.trim();
    if (id.isEmpty) {
      return const AuthResult.failure(AuthError.wrongCredentials);
    }

    final users = await _loadUsers();
    if (users.isEmpty) {
      return const AuthResult.failure(AuthError.notRegistered);
    }

    for (final u in users) {
      final match = u.phone == id || u.username == id;
      if (!match) continue;
      if (PasswordHasher.verify(password, u.passwordSalt, u.passwordHash)) {
        await _setCurrentUser(u.userId);
        return AuthResult.success(u);
      }
    }
    // ⚠️ 不区分"账号不存在"和"密码错误" —— 分开说等于告诉别人
    //    哪些账号是存在的，可以被用来枚举用户名。
    return const AuthResult.failure(AuthError.wrongCredentials);
  }

  // -- 资料 ---------------------------------------------------------------

  /// 修改资料。
  ///
  /// 为什么单独一个方法而不是让界面直接改 LocalUser：
  ///   LocalUser 是**不可变**的（const 构造 + final 字段）。
  ///   这是刻意的 —— 密码哈希一旦被就地修改，很容易出现"界面改了但没落盘"
  ///   或"落盘了但当前会话还是旧对象"这类不一致。
  ///   所以统一走这里：copy → 替换 → 落盘，一步不少。
  ///
  /// 参数为 null 表示该项不改。
  /// [clearAge] / [clearAvatarFile] 用于**取消**填写（null 无法表达"清空"）。
  Future<LocalUser?> updateProfile({
    required String userId,
    String? name,
    String? avatarId,
    String? role,
    String? gender,
    int? age,
    String? avatarFile,
    String? phone,
    bool clearAge = false,
    bool clearAvatarFile = false,
  }) async {
    final users = await _loadUsers();
    final i = users.indexWhere((u) => u.userId == userId);
    if (i < 0) return null;

    // 手机号要校验，而且不能和别人撞 —— 它是登录凭据之一。
    String? newPhone;
    if (phone != null) {
      final p = phone.trim();
      if (p.isNotEmpty) {
        if (!isValidPhone(p)) {
          throw ArgumentError(AuthError.invalidPhone.message);
        }
        if (users.any((x) => x.userId != userId && x.phone == p)) {
          throw ArgumentError('该手机号已被其他账号绑定');
        }
      }
      newPhone = p;
    }

    final trimmed = name?.trim();
    final updated = users[i].copyWith(
      // 昵称不允许改成空 —— 空昵称在界面上会显示成一片空白，
      // 教练分不清是谁的记录。
      name: (trimmed == null || trimmed.isEmpty) ? null : trimmed,
      avatarId: avatarId,
      role: role,
      gender: gender,
      age: age,
      avatarFile: avatarFile,
      phone: newPhone,
      clearAge: clearAge,
      clearAvatarFile: clearAvatarFile,
    );
    users[i] = updated;
    await _saveUsers(users);
    return updated;
  }

  // -- 会话 ---------------------------------------------------------------

  /// 取当前登录用户。App 启动时用它决定去登录页还是首页。
  Future<LocalUser?> currentUser() async {
    final doc = await _store.read();
    final id = doc[_currentUserKey] as String?;
    if (id == null) return null;

    final users = await _loadUsers();
    for (final u in users) {
      if (u.userId == id) return u;
    }
    // 记录了当前用户但用户不存在（数据被外部改动）：清掉记录，回到登录页
    doc.remove(_currentUserKey);
    await _store.write(doc);
    return null;
  }

  Future<void> logout() async {
    final doc = await _store.read();
    doc.remove(_currentUserKey);
    await _store.write(doc);
  }

  /// 是否已有注册过的账号。用于登录页决定显示「注册」还是「去登录」引导。
  Future<bool> hasAnyAccount() async => (await _loadUsers()).isNotEmpty;

  // -- 管理员账号 ---------------------------------------------------------

  /// 内置管理员账号的用户名。
  ///
  /// ⚠️ 与服务端 `backend/server/app.py` 的 `ADMIN_USERNAME` 保持一致。
  ///    服务端那份用于**记账与额度**，App 这份用于**登录进入界面**。
  ///    两边都存在才能完整使用管理员权限。
  ///
  /// 为什么不从服务端拉：登录发生在**配置服务地址之前** ——
  /// 那时还不知道服务在哪，没法拉。所以本地必须有一份。
  static const adminUsername = 'MazingLIU';

  /// App 内管理员账号的初始密码。
  ///
  /// ⚠️ 这是**本地账号**的密码，与服务端那份相互独立。
  ///    改密码是两件事，目前都没做（没有改密码界面）。
  static const adminInitialPassword = 'Lmyiuinu20061212';

  /// 确保管理员账号存在。已存在则不动它。
  ///
  /// 为什么需要这个函数（真实缺陷）：
  ///   管理员账号原本只建在**服务端**，而 App 的登录校验走的是
  ///   **本地账号表**。结果就是：用户名是字母，App 却只认 11 位手机号，
  ///   而且本地根本没有这个账号 —— 管理员完全登不进去。
  ///
  /// 只创建一次：已存在就返回，否则每次启动都会把密码重置回去，
  /// 用户改了密码也白改。
  ///
  /// 返回是否新建了账号。
  Future<bool> ensureAdminAccount() async {
    final users = await _loadUsers();
    if (users.any((u) => u.username == adminUsername)) return false;

    final salt = PasswordHasher.newSalt();
    final admin = LocalUser(
      // 固定的 userId —— 管理员账号是产品自带的，不是注册出来的。
      // 用 'u_admin' 而不是时间戳，这样即使账号文件被删掉重建，
      // 引用它的历史数据（例如 teamId）也不会错位。
      userId: 'u_admin',
      // 管理员不绑手机号 —— 用用户名登录。
      phone: '',
      username: adminUsername,
      name: '管理员',
      teamId: 't_admin',
      passwordSalt: salt,
      passwordHash: PasswordHasher.hash(adminInitialPassword, salt),
      createdAt: DateTime.now().toIso8601String(),
      avatarId: 'medal',
      role: '教练员',
    );

    users.add(admin);
    await _saveUsers(users);
    return true;
  }

  // -- 内部 ---------------------------------------------------------------

  Future<List<LocalUser>> _loadUsers() async {
    final doc = await _store.read();
    final raw = doc['users'];
    if (raw is! List) return [];

    final out = <LocalUser>[];
    for (final item in raw) {
      if (item is! Map<String, dynamic>) continue;
      final u = LocalUser.fromJson(item);
      // 解析不出来的条目跳过而不是整体失败 —— 一条坏数据不该让所有人登不进来
      if (u != null) out.add(u);
    }
    return out;
  }

  Future<void> _saveUsers(List<LocalUser> users) async {
    final doc = await _store.read();
    doc['users'] = users.map((u) => u.toJson()).toList();
    await _store.write(doc);
  }

  Future<void> _setCurrentUser(String userId) async {
    final doc = await _store.read();
    doc[_currentUserKey] = userId;
    await _store.write(doc);
  }
}
