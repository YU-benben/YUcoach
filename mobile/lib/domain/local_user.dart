import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';

/// 本地账号。
///
/// 之所以是「本地账号」而不是服务端账号：
///   现阶段没有后端，而训练场信号常常很差。本地账号让 App 立刻可用，
///   且天然离线。后端就绪后，此模型作为本地缓存保留，增加同步字段即可。
///
/// 密码处理：**绝不存明文**。
/// 用 加盐 + 多次迭代 SHA-256。这不是 PBKDF2/Argon2 那样的抗暴力破解方案，
/// 但对「数据只存在本机、攻击者已经拿到设备」这个威胁模型来说是相称的 ——
/// 目标是不让密码以任何可直接使用的形式落盘。
class LocalUser {
  const LocalUser({
    required this.userId,
    required this.phone,
    required this.name,
    required this.teamId,
    required this.passwordSalt,
    required this.passwordHash,
    required this.createdAt,
    this.username = '',
    this.avatarId = defaultAvatarId,
    this.role = '',
    this.gender = '',
    this.age,
    this.avatarFile = '',
  });

  /// 账号标识：手机号。用用户名注册时为空串。
  ///
  /// ⚠️ **不要假设它非空**。有些账号是用用户名注册的（例如管理员），
  ///    它们没有手机号。判断"能不能用手机号登录"要看 `phone.isNotEmpty`，
  ///    而不是看这个字段存不存在。
  final String phone;

  /// 账号标识：用户名。用手机号注册时为空串。
  ///
  /// 为什么需要两种标识：
  ///   教练用手机号注册最自然（记得住、能找回）；
  ///   但管理员账号是一串字母，而且**服务端的管理员就是用户名**。
  ///   只支持手机号会让这类账号完全无法登录 —— 这是真实发生过的缺陷。
  final String username;

  final String name;

  /// 所属队伍。多租户的第一天就带上 —— 事后补这一层要改所有数据和查询。
  final String teamId;

  final String userId;
  final String passwordSalt;
  final String passwordHash;
  final String createdAt;

  /// 头像标识（内置头像）。
  final String avatarId;

  /// 自定义头像的文件名。非空时**优先于** `avatarId`。
  ///
  /// 为什么存文件名而不是图片本身：
  ///   · 图片存进 JSON 会让账号文件膨胀到几 MB，每次读写都变慢
  ///   · 图片是二进制，base64 进 JSON 还要多占 33% 体积
  ///   所以图片单独存成文件，账号里只留一个引用。
  ///
  /// 为空表示没上传过自定义头像，用内置的 `avatarId`。
  final String avatarFile;

  /// 身份：家长 / 教练员 / 运动员。
  final String role;

  /// 性别：男 / 女 / 空（未设置）。
  final String gender;

  /// 年龄。null 表示未设置。
  ///
  /// 为什么用 int? 而不是 0：
  ///   0 岁是合法但不合理的值，用 null 才能区分"没填"和"填了 0"。
  ///   而且这类字段会参与统计，用 0 占位会把平均值拉低。
  final int? age;

  /// 默认头像标识。
  static const defaultAvatarId = 'fish';

  /// 身份可选值。空串表示未设置。
  static const roleOptions = ['家长', '教练员', '运动员'];

  /// 性别可选值。空串表示未设置。
  static const genderOptions = ['男', '女'];

  /// 账号标识，用于界面显示。
  ///
  /// 优先显示手机号 —— 它更具体，用户更容易确认"这是我的账号"。
  String get loginId => phone.isNotEmpty ? phone : username;

  /// 是否绑定了手机号。
  bool get hasPhone => phone.isNotEmpty;

  /// 是否设置了用户名。
  bool get hasUsername => username.isNotEmpty;

  /// 使用的头像：自定义优先，否则内置。
  bool get usesCustomAvatar => avatarFile.isNotEmpty;

  LocalUser copyWith({
    String? name,
    String? avatarId,
    String? role,
    String? gender,
    int? age,
    String? avatarFile,
    String? phone,
    String? username,
    bool clearAge = false,
    bool clearAvatarFile = false,
  }) =>
      LocalUser(
        userId: userId,
        phone: phone ?? this.phone,
        // 用户名可以被**补上**（老账号用手机号注册，username 是空的），
        // 所以这里要能改 —— 它是提交分析时服务端认账号的依据。
        username: username ?? this.username,
        name: name ?? this.name,
        teamId: teamId,
        passwordSalt: passwordSalt,
        passwordHash: passwordHash,
        createdAt: createdAt,
        avatarId: avatarId ?? this.avatarId,
        role: role ?? this.role,
        gender: gender ?? this.gender,
        // clearAge 是为了能"取消填写年龄"。
        // 只用 age ?? this.age 的话，传 null 会被当成"不改"，
        // 于是用户填错了就再也改不回空。
        age: clearAge ? null : (age ?? this.age),
        avatarFile:
            clearAvatarFile ? '' : (avatarFile ?? this.avatarFile),
      );

  Map<String, dynamic> toJson() => {
        'user_id': userId,
        'phone': phone,
        'username': username,
        'name': name,
        'team_id': teamId,
        'password_salt': passwordSalt,
        'password_hash': passwordHash,
        'created_at': createdAt,
        'avatar_id': avatarId,
        'avatar_file': avatarFile,
        'role': role,
        'gender': gender,
        'age': age,
      };

  static LocalUser? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    String? s(String k) => json[k] as String?;
    final phone = s('phone') ?? '';
    final username = s('username') ?? '';
    final hash = s('password_hash');
    final salt = s('password_salt');

    // 两种标识至少要有一种，否则这个账号无法登录 ——
    // 读进来也没用，不如当作坏数据跳过。
    if ((phone.isEmpty && username.isEmpty) || hash == null || salt == null) {
      return null;
    }

    // 老数据里 age 可能是字符串或数字，两种都接受。
    // 早期版本可能把它存成过 '18'，直接 as int? 会抛异常。
    final rawAge = json['age'];
    int? age;
    if (rawAge is int) {
      age = rawAge;
    } else if (rawAge is String) {
      age = int.tryParse(rawAge);
    }

    return LocalUser(
      userId: s('user_id') ?? '',
      phone: phone,
      username: username,
      name: s('name') ?? '',
      teamId: s('team_id') ?? '',
      passwordSalt: salt,
      passwordHash: hash,
      createdAt: s('created_at') ?? '',
      // 老账号没有这些字段 —— 用默认值读进来，
      // 而不是让整个账号反序列化失败。这样升级 App 不会让用户掉登录。
      avatarId: s('avatar_id') ?? defaultAvatarId,
      avatarFile: s('avatar_file') ?? '',
      role: s('role') ?? '',
      gender: s('gender') ?? '',
      age: age,
    );
  }
}

/// 密码哈希工具。加盐 + 迭代。
class PasswordHasher {
  static const _iterations = 10000;

  static String newSalt() {
    final rnd = Random.secure();
    final bytes = List<int>.generate(16, (_) => rnd.nextInt(256));
    return base64Url.encode(bytes);
  }

  static String hash(String password, String salt) {
    var digest = sha256.convert(utf8.encode('$salt:$password'));
    for (var i = 1; i < _iterations; i++) {
      digest = sha256.convert(digest.bytes);
    }
    return digest.toString();
  }

  /// 定长比较，避免通过响应时间推测密码。
  static bool verify(String password, String salt, String expected) {
    final actual = hash(password, salt);
    if (actual.length != expected.length) return false;
    var diff = 0;
    for (var i = 0; i < actual.length; i++) {
      diff |= actual.codeUnitAt(i) ^ expected.codeUnitAt(i);
    }
    return diff == 0;
  }
}
