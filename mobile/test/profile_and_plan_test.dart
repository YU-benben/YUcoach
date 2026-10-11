import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/auth_service.dart';
import 'package:yu_coach/data/local_store.dart';
import 'package:yu_coach/data/training_plan_repository.dart';
import 'package:yu_coach/domain/local_user.dart';
import 'package:yu_coach/domain/training_plan_entry.dart';
import 'package:yu_coach/pages/welcome_page.dart';
import 'package:yu_coach/widgets/user_avatar.dart';

/// 阶段②新增功能的测试：资料编辑、训练计划、欢迎页。
///
/// 全部用临时目录注入，不碰真实用户数据。
void main() {
  late Directory tmp;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('yucoach_p2_');
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  AuthService newAuth() =>
      AuthService(store: LocalStore(fileName: 'users.json', baseDir: tmp));

  TrainingPlanRepository newPlans(String userId) => TrainingPlanRepository(
        userId: userId,
        store: LocalStore(fileName: 'plans.json', baseDir: tmp),
      );

  // -------------------------------------------------------------------------
  group('账号资料', () {
    test('注册的账号有默认头像，身份为空', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138000',
        name: '小明',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      expect(r.ok, isTrue);
      expect(r.user!.avatarId, LocalUser.defaultAvatarId);
      expect(r.user!.role, '');
    });

    test('改昵称会落盘，重新读出来是新值', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138001',
        name: '小明',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      final uid = r.user!.userId;

      final updated = await auth.updateProfile(userId: uid, name: '笨笨鱼');
      expect(updated, isNotNull);
      expect(updated!.name, '笨笨鱼');

      // 关键：重新从文件读，而不是信任返回值 ——
      // 返回值正确但没落盘是最常见的缺陷。
      final reread = await auth.currentUser();
      expect(reread!.name, '笨笨鱼');
    });

    test('改头像与身份会落盘', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138002',
        name: '教练',
        password: 'password123',
        passwordConfirm: 'password123',
      );

      await auth.updateProfile(
        userId: r.user!.userId,
        avatarId: 'medal',
        role: '教练员',
      );

      final u = await auth.currentUser();
      expect(u!.avatarId, 'medal');
      expect(u.role, '教练员');
    });

    test('昵称改成空串会被忽略，不会存成空昵称', () async {
      // 空昵称在报告和记录里显示成一片空白，教练分不清是谁。
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138003',
        name: '原名',
        password: 'password123',
        passwordConfirm: 'password123',
      );

      await auth.updateProfile(userId: r.user!.userId, name: '   ');

      final u = await auth.currentUser();
      expect(u!.name, '原名', reason: '空昵称应当被忽略，而不是存进去');
    });

    test('只改一项时其他项不受影响', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138004',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      final uid = r.user!.userId;

      await auth.updateProfile(userId: uid, avatarId: 'bolt', role: '运动员');
      await auth.updateProfile(userId: uid, name: 'B');

      final u = await auth.currentUser();
      expect(u!.name, 'B');
      expect(u.avatarId, 'bolt', reason: '只改名字不该把头像重置');
      expect(u.role, '运动员');
    });

    test('密码哈希在改资料后不变', () async {
      // 改资料绝对不能碰密码 —— 碰了用户就登不进来了。
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138005',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      final before = r.user!.passwordHash;

      await auth.updateProfile(userId: r.user!.userId, name: 'B');

      final u = await auth.currentUser();
      expect(u!.passwordHash, before);

      // 密码仍然能用来登录
      final login = await auth.login(
          loginId: '13800138005', password: 'password123');
      expect(login.ok, isTrue);
    });

    test('改不存在的用户返回 null，不抛异常', () async {
      final auth = newAuth();
      final r = await auth.updateProfile(userId: 'nope', name: 'X');
      expect(r, isNull);
    });

    test('老账号数据缺少新字段时仍能读入（向后兼容）', () async {
      // 这一步很重要：升级 App 不该让已有用户掉登录。
      final store = LocalStore(fileName: 'users.json', baseDir: tmp);
      await store.write({
        'users': [
          {
            'user_id': 'u_old',
            'phone': '13800138009',
            'name': '老用户',
            'team_id': 't_old',
            'password_salt': 'salt',
            'password_hash': 'hash',
            'created_at': '2025-01-01T00:00:00.000',
            // 注意：没有 avatar_id 和 role
          }
        ],
        'current_user_id': 'u_old',
      });

      final auth = AuthService(store: store);
      final u = await auth.currentUser();
      expect(u, isNotNull, reason: '老数据必须能读出来');
      expect(u!.name, '老用户');
      expect(u.avatarId, LocalUser.defaultAvatarId);
      expect(u.role, '');
    });
  });

  // -------------------------------------------------------------------------
  group('管理员账号与用户名登录', () {
    test('内置管理员账号能创建，且能用用户名登录', () async {
      // ⚠️ 这条守着真实缺陷：
      //    管理员账号原本只建在**服务端**，而 App 的登录校验走的是
      //    本地账号表。加上登录框只认 11 位手机号 ——
      //    结果管理员完全登不进去。
      final auth = newAuth();
      final created = await auth.ensureAdminAccount();
      expect(created, isTrue, reason: '首次应当创建');

      final r = await auth.login(
        loginId: AuthService.adminUsername,
        password: AuthService.adminInitialPassword,
      );
      expect(r.ok, isTrue, reason: '管理员必须能用字母用户名登录');
      expect(r.user!.username, AuthService.adminUsername);
      expect(r.user!.phone, '', reason: '管理员不绑手机号');
    });

    test('ensureAdminAccount 只创建一次，不重置已有账号', () async {
      final auth = newAuth();
      await auth.ensureAdminAccount();
      final again = await auth.ensureAdminAccount();
      expect(again, isFalse, reason: '第二次应当发现已存在');

      // 账号表里只有一个管理员，没有重复
      final users = await auth.hasAnyAccount();
      expect(users, isTrue);
      final r = await auth.login(
        loginId: AuthService.adminUsername,
        password: AuthService.adminInitialPassword,
      );
      expect(r.ok, isTrue);
    });

    test('用用户名注册的账号能登录', () async {
      final auth = newAuth();
      final r = await auth.register(
        username: 'coach_wang',
        name: '王教练',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      expect(r.ok, isTrue);
      expect(r.user!.username, 'coach_wang');
      expect(r.user!.phone, '');

      final login = await auth.login(
          loginId: 'coach_wang', password: 'password123');
      expect(login.ok, isTrue);
    });

    test('手机号注册的账号，用手机号或用户名都能登录', () async {
      final auth = newAuth();
      await auth.register(
        phone: '13800138000',
        username: 'both_id',
        name: '双标识',
        password: 'password123',
        passwordConfirm: 'password123',
      );

      expect(
        (await auth.login(loginId: '13800138000', password: 'password123')).ok,
        isTrue,
      );
      expect(
        (await auth.login(loginId: 'both_id', password: 'password123')).ok,
        isTrue,
      );
    });

    test('用户名格式校验：合法与非法', () {
      // 合法的：字母、数字、下划线、连字符，2–24 位
      expect(AuthService.isValidUsername('MazingLIU'), isTrue);
      expect(AuthService.isValidUsername('coach_wang'), isTrue);
      expect(AuthService.isValidUsername('a1'), isTrue);
      expect(AuthService.isValidUsername('user-name'), isTrue);

      // 非法的
      expect(AuthService.isValidUsername('a'), isFalse, reason: '太短');
      expect(AuthService.isValidUsername(''), isFalse);
      expect(AuthService.isValidUsername('a' * 25), isFalse, reason: '太长');
      expect(AuthService.isValidUsername('有中文'), isFalse);
      expect(AuthService.isValidUsername('has space'), isFalse);
      expect(AuthService.isValidUsername('a@b'), isFalse);
    });

    test('用户名重复会被拒绝', () async {
      final auth = newAuth();
      await auth.register(
        username: 'taken',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      final r = await auth.register(
        username: 'taken',
        name: 'B',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      expect(r.error, AuthError.usernameTaken);
    });

    test('手机号和用户名都没有时拒绝注册', () async {
      final auth = newAuth();
      final r = await auth.register(
        name: 'X',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      expect(r.ok, isFalse);
    });

    test('账号不存在与密码错误返回同一个原因（防账号枚举）', () async {
      final auth = newAuth();
      await auth.register(
        phone: '13800138000',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );

      final wrongPw = await auth.login(
          loginId: '13800138000', password: 'wrongpass');
      final noUser = await auth.login(
          loginId: 'nobody_at_all', password: 'password123');

      expect(wrongPw.error, noUser.error,
          reason: '两种失败的原因必须相同，否则能被用来枚举账号');
      expect(wrongPw.error, AuthError.wrongCredentials);
    });

    test('looksLikePhone 能区分手机号与用户名', () {
      expect(AuthService.looksLikePhone('13800138000'), isTrue);
      expect(AuthService.looksLikePhone('MazingLIU'), isFalse);
      expect(AuthService.looksLikePhone('coach_wang'), isFalse);
      expect(AuthService.looksLikePhone(''), isFalse);
    });
  });

  // -------------------------------------------------------------------------
  group('资料字段：性别、年龄、手机号', () {
    test('能设置性别与年龄', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138010',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );

      await auth.updateProfile(
        userId: r.user!.userId,
        gender: '女',
        age: 17,
      );

      final u = await auth.currentUser();
      expect(u!.gender, '女');
      expect(u.age, 17);
    });

    test('年龄可以被清空（clearAge）', () async {
      // 只用 age ?? this.age 的话传 null 会被当成"不改"，
      // 用户填错了就再也改不回空。
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138011',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );

      await auth.updateProfile(userId: r.user!.userId, age: 20);
      expect((await auth.currentUser())!.age, 20);

      await auth.updateProfile(userId: r.user!.userId, clearAge: true);
      expect((await auth.currentUser())!.age, isNull,
          reason: '年龄必须能被清空');
    });

    test('能给用户名账号绑定手机号', () async {
      final auth = newAuth();
      final r = await auth.register(
        username: 'nobind',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      expect(r.user!.hasPhone, isFalse);

      await auth.updateProfile(
          userId: r.user!.userId, phone: '13900139000');

      final u = await auth.currentUser();
      expect(u!.phone, '13900139000');
      expect(u.hasPhone, isTrue);
      // 绑定后两种标识都能登录
      expect(
        (await auth.login(loginId: '13900139000', password: 'password123')).ok,
        isTrue,
      );
      expect(
        (await auth.login(loginId: 'nobind', password: 'password123')).ok,
        isTrue,
      );
    });

    test('绑定别人的手机号会被拒绝', () async {
      final auth = newAuth();
      await auth.register(
        phone: '13800138012',
        name: 'A',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      final b = await auth.register(
        username: 'user_b',
        name: 'B',
        password: 'password123',
        passwordConfirm: 'password123',
      );

      expect(
        () => auth.updateProfile(
            userId: b.user!.userId, phone: '13800138012'),
        throwsA(isA<ArgumentError>()),
        reason: '手机号是登录凭据，不能和别人重复',
      );
    });

    test('绑定格式错误的手机号会被拒绝', () async {
      final auth = newAuth();
      final r = await auth.register(
        username: 'user_c',
        name: 'C',
        password: 'password123',
        passwordConfirm: 'password123',
      );
      expect(
        () => auth.updateProfile(userId: r.user!.userId, phone: '123'),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('老账号缺少 gender/age 字段时仍能读入', () async {
      final store = LocalStore(fileName: 'users.json', baseDir: tmp);
      await store.write({
        'users': [
          {
            'user_id': 'u_old2',
            'phone': '13800138013',
            'name': '老用户',
            'team_id': 't_old',
            'password_salt': 'salt',
            'password_hash': 'hash',
            'created_at': '2025-01-01T00:00:00.000',
          }
        ],
        'current_user_id': 'u_old2',
      });

      final auth = AuthService(store: store);
      final u = await auth.currentUser();
      expect(u, isNotNull);
      expect(u!.gender, '');
      expect(u.age, isNull);
      expect(u.username, '');
    });

    test('age 存成字符串时也能读入（兼容早期格式）', () async {
      final store = LocalStore(fileName: 'users.json', baseDir: tmp);
      await store.write({
        'users': [
          {
            'user_id': 'u_old3',
            'phone': '13800138014',
            'name': '老用户',
            'team_id': 't_old',
            'password_salt': 'salt',
            'password_hash': 'hash',
            'created_at': '2025-01-01T00:00:00.000',
            'age': '16',
          }
        ],
        'current_user_id': 'u_old3',
      });

      final auth = AuthService(store: store);
      final u = await auth.currentUser();
      expect(u!.age, 16, reason: '字符串形式的年龄应当被解析，而不是抛异常');
    });

    test('两种标识都为空的老数据被当作坏数据跳过', () async {
      final store = LocalStore(fileName: 'users.json', baseDir: tmp);
      await store.write({
        'users': [
          {
            'user_id': 'u_bad',
            // 既没有 phone 也没有 username —— 这个账号无法登录
            'name': '坏数据',
            'team_id': 't',
            'password_salt': 's',
            'password_hash': 'h',
            'created_at': '',
          }
        ],
        'current_user_id': 'u_bad',
      });

      final auth = AuthService(store: store);
      expect(await auth.currentUser(), isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('头像目录', () {
    test('按 id 取头像；未知 id 回退到默认而不是抛异常', () {
      expect(AvatarCatalog.byId('medal').label, '奖牌');
      expect(AvatarCatalog.byId('不存在').id, AvatarCatalog.defaultId);
      expect(AvatarCatalog.byId(null).id, AvatarCatalog.defaultId);
      expect(AvatarCatalog.byId('').id, AvatarCatalog.defaultId);
    });

    test('头像 id 唯一', () {
      final ids = AvatarCatalog.items.map((a) => a.id).toList();
      expect(ids.toSet().length, ids.length, reason: '头像 id 有重复');
    });
  });

  // -------------------------------------------------------------------------
  group('训练计划', () {
    test('保存后能读回来', () async {
      final plans = newPlans('u_1');
      final day = DateTime(2026, 3, 15);

      await plans.save(day, '起跑器练习 6 组');
      final e = await plans.get(day);
      expect(e, isNotNull);
      expect(e!.content, '起跑器练习 6 组');
    });

    test('内容留空则删除该条目，而不是存一条空记录', () async {
      final plans = newPlans('u_1');
      final day = DateTime(2026, 3, 15);

      await plans.save(day, '有内容');
      expect(await plans.get(day), isNotNull);

      await plans.save(day, '   ');
      expect(await plans.get(day), isNull,
          reason: '"清空"和"从没记过"应当是同一个状态');
    });

    test('日期字符串格式补零', () {
      // 不补零的话 '2026-3-5' 和 '2026-03-05' 会同时存在，
      // 而字符串比较排序会出错 —— 日历就会串行。
      expect(dateKey(DateTime(2026, 3, 5)), '2026-03-05');
      expect(dateKey(DateTime(2026, 12, 25)), '2026-12-25');
    });

    test('日期字符串的字典序就是时间序', () {
      final a = dateKey(DateTime(2026, 3, 5));
      final b = dateKey(DateTime(2026, 3, 15));
      final c = dateKey(DateTime(2026, 10, 1));
      expect(a.compareTo(b) < 0, isTrue);
      expect(b.compareTo(c) < 0, isTrue,
          reason: '3 月必须排在 10 月之前 —— 补零保证了这一点');
    });

    test('range 只返回区间内的条目', () async {
      final plans = newPlans('u_1');
      await plans.save(DateTime(2026, 2, 28), '二月');
      await plans.save(DateTime(2026, 3, 1), '三月初');
      await plans.save(DateTime(2026, 3, 31), '三月末');
      await plans.save(DateTime(2026, 4, 1), '四月');

      final r = await plans.range(
          DateTime(2026, 3, 1), DateTime(2026, 3, 31));
      expect(r.length, 2);
      expect(r.keys, containsAll(['2026-03-01', '2026-03-31']));
    });

    test('remove 能删掉条目', () async {
      final plans = newPlans('u_1');
      final day = DateTime(2026, 3, 20);
      await plans.save(day, '内容');
      await plans.remove(day);
      expect(await plans.get(day), isNull);
    });

    test('解析非法的日期字符串返回 null，不抛异常', () {
      expect(parseDateKey('乱写'), isNull);
      expect(parseDateKey('2026-13-01'), isNull);
      expect(parseDateKey('2026-00-01'), isNull);
      expect(parseDateKey(''), isNull);
      expect(parseDateKey('2026-03-05'), isNotNull);
    });

    test('摘要取第一行并截断', () {
      const e = TrainingPlanEntry(
        date: '2026-03-15',
        content: '第一行内容\n第二行\n第三行',
        updatedAt: '',
      );
      expect(e.summary, '第一行内容');
      expect(e.hasContent, isTrue);

      final long = TrainingPlanEntry(
        date: '2026-03-15',
        content: '这是一段很长的训练安排说明文字需要被截断处理掉多余部分',
        updatedAt: '',
      );
      expect(long.summary.length, lessThanOrEqualTo(19));
      expect(long.summary.endsWith('…'), isTrue);
    });

    test('空内容的条目 hasContent 为 false', () {
      const e = TrainingPlanEntry(
          date: '2026-03-15', content: '   ', updatedAt: '');
      expect(e.hasContent, isFalse);
      expect(e.summary, '');
    });

    test('一条坏数据不影响其他条目读入', () async {
      final store = LocalStore(fileName: 'plans.json', baseDir: tmp);
      await store.write({
        'plans': {
          '2026-03-01': {'date': '2026-03-01', 'content': '好的'},
          '2026-03-02': {'content': '缺少 date 字段'},   // 坏数据
          '2026-03-03': '这不是一个对象',                 // 坏数据
        }
      });

      final plans = TrainingPlanRepository(userId: 'u_1', store: store);
      final r = await plans.range(
          DateTime(2026, 3, 1), DateTime(2026, 3, 31));
      expect(r.length, 1, reason: '坏数据应当被跳过，而不是让整个日历打不开');
      expect(r['2026-03-01']!.content, '好的');
    });
  });

  // -------------------------------------------------------------------------
  group('欢迎页', () {
    testWidgets('显示昵称与定位语', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: WelcomePage(name: '笨笨鱼'),
      ));
      // 动画进行中也要能读到文字
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('笨笨鱼，你的专属田径教练'), findsOneWidget);
      expect(find.text('YUcoach 跑姿分析'), findsOneWidget);
    });

    testWidgets('没设昵称时用默认称呼', (tester) async {
      await tester.pumpWidget(const MaterialApp(home: WelcomePage()));
      await tester.pump(const Duration(milliseconds: 100));

      expect(
        find.text('${WelcomePage.defaultName}，${WelcomePage.tagline}'),
        findsOneWidget,
      );
    });

    testWidgets('昵称是空白时也用默认称呼', (tester) async {
      // 只有空格或空串时要当作"没设昵称"，
      // 否则会显示成" ，你的专属田径教练"。
      await tester.pumpWidget(const MaterialApp(
        home: WelcomePage(name: '   '),
      ));
      await tester.pump(const Duration(milliseconds: 100));

      expect(
        find.text('${WelcomePage.defaultName}，${WelcomePage.tagline}'),
        findsOneWidget,
      );
    });
  });

  // -------------------------------------------------------------------------
  group('用户头像组件', () {
    testWidgets('显示对应头像的图标', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: UserAvatar(avatarId: 'medal')),
      ));
      expect(find.byIcon(Icons.emoji_events_outlined), findsOneWidget);
    });

    testWidgets('未知头像 id 显示默认头像，不崩', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: UserAvatar(avatarId: '不存在的id')),
      ));
      expect(find.byIcon(Icons.set_meal_outlined), findsOneWidget);
    });
  });
}
