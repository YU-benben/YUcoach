import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/athlete_repository.dart';
import 'package:yu_coach/data/auth_service.dart';
import 'package:yu_coach/data/local_store.dart';
import 'package:yu_coach/domain/local_user.dart';
import 'package:yu_coach/models/models.dart';
import 'package:yu_coach/pages/login_page.dart';

/// 账号与本地存储的测试。
///
/// 全部用临时目录注入，不碰真实用户数据 ——
/// 否则跑一次测试就会把开发机上的账号覆盖掉。
void main() {
  late Directory tmp;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('yucoach_test_');
  });

  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  AuthService newAuth() =>
      AuthService(store: LocalStore(fileName: 'users.json', baseDir: tmp));

  AthleteRepository newRepo(String teamId) => AthleteRepository(
        store: LocalStore(fileName: 'athletes.json', baseDir: tmp),
        teamId: teamId,
      );

  // -------------------------------------------------------------------------
  group('密码哈希', () {
    test('同一密码加盐后哈希稳定，不同盐得到不同哈希', () {
      const pwd = 'hunter2024';
      final s1 = PasswordHasher.newSalt();
      final s2 = PasswordHasher.newSalt();

      expect(s1, isNot(s2), reason: '盐必须随机，否则彩虹表可复用');
      expect(PasswordHasher.hash(pwd, s1), PasswordHasher.hash(pwd, s1),
          reason: '同盐同密码必须得到同一哈希，否则登录无法验证');
      expect(PasswordHasher.hash(pwd, s1), isNot(PasswordHasher.hash(pwd, s2)));
    });

    test('明文密码不会出现在校验结果里', () {
      const pwd = 'hunter2024';
      final salt = PasswordHasher.newSalt();
      final hash = PasswordHasher.hash(pwd, salt);
      expect(hash.contains(pwd), isFalse);
      expect(hash.length, 64, reason: 'SHA-256 十六进制应为 64 字符');
    });

    test('verify 正确接受与拒绝', () {
      const pwd = 'hunter2024';
      final salt = PasswordHasher.newSalt();
      final hash = PasswordHasher.hash(pwd, salt);

      expect(PasswordHasher.verify(pwd, salt, hash), isTrue);
      expect(PasswordHasher.verify('hunter2025', salt, hash), isFalse);
      expect(PasswordHasher.verify('', salt, hash), isFalse);
    });
  });

  // -------------------------------------------------------------------------
  group('注册', () {
    test('注册成功后自动登录', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138000',
        username: 'u13800138000',
        name: '张教练',
        password: 'abc123456',
        passwordConfirm: 'abc123456',
      );

      expect(r.ok, isTrue);
      expect(r.user!.name, '张教练');
      expect(r.user!.phone, '13800138000');
      expect(r.user!.teamId, isNotEmpty, reason: '多租户字段必须有值');

      final current = await auth.currentUser();
      expect(current?.userId, r.user!.userId);
    });

    test('手机号格式不对被拒绝', () async {
      final auth = newAuth();
      // ⚠️ 空串**不在**这个列表里：手机号现在是选填，
      //    不填是合法的（有些账号天生没有手机号）。见 register() 的说明。
      for (final bad in ['138', '23800138000', '1380013800a', '138001380001']) {
        final r = await auth.register(
          phone: bad,
          // 用户名给一个合法值：本测试要验证的是**手机号**格式校验，
          // 用户名跟着一起非法就会让两条规则混在一起，测不出是哪条拦的。
          username: 'u${bad.hashCode.abs()}',
          name: 'x',
          password: 'abc123456',
          passwordConfirm: 'abc123456',
        );
        expect(r.ok, isFalse, reason: '「$bad」不应通过');
        expect(r.error, AuthError.invalidPhone);
      }
    });

    test('不填手机号也能注册（用户名必填，手机号选填）', () async {
      // 手机号只用于日后找回账号，不是登录的必需条件 ——
      // 强制它会挡住没有手机号的用户（比如给管理员用的账号）。
      final auth = newAuth();
      final r = await auth.register(
        phone: '',
        username: 'nomobile',
        name: '无手机号',
        password: 'abc123456',
        passwordConfirm: 'abc123456',
      );
      expect(r.ok, isTrue, reason: '手机号留空时注册应当成功');
      expect(r.user!.username, 'nomobile');
      expect(r.user!.phone, '');
    });

    test('密码太短被拒绝', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138000',
        username: 'u13800138000',
        name: 'x',
        password: '12345',
        passwordConfirm: '12345',
      );
      expect(r.error, AuthError.weakPassword);
    });

    test('两次密码不一致被拒绝', () async {
      final auth = newAuth();
      final r = await auth.register(
        phone: '13800138000',
        username: 'u13800138000',
        name: 'x',
        password: 'abc123456',
        passwordConfirm: 'abc123457',
      );
      expect(r.error, AuthError.passwordMismatch);
    });

    test('同一手机号不能重复注册', () async {
      final auth = newAuth();
      await auth.register(
        phone: '13800138000',
        username: 'first_user',
        name: 'a',
        password: 'abc123456',
        passwordConfirm: 'abc123456',
      );
      // ⚠️ 第二次必须换一个**用户名** —— 若沿用同一个，
      //    拦下来的是用户名重复而不是手机号重复，这条测试就测偏了。
      final r = await auth.register(
        phone: '13800138000',
        username: 'second_user',
        name: 'b',
        password: 'abc123456',
        passwordConfirm: 'abc123456',
      );
      expect(r.error, AuthError.phoneTaken);
    });
  });

  // -------------------------------------------------------------------------
  group('登录与持久化', () {
    test('正确密码可登录，错误密码被拒', () async {
      final auth = newAuth();
      await auth.register(
        phone: '13800138000',
        username: 'u13800138000',
        name: '张教练',
        password: 'abc123456',
        passwordConfirm: 'abc123456',
      );
      await auth.logout();

      expect((await auth.login(loginId: '13800138000', password: 'wrongpass')).error,
          AuthError.wrongCredentials);
      expect((await auth.login(loginId: '13800138000', password: 'abc123456')).ok,
          isTrue);
    });

    test('未注册任何账号时给出明确原因', () async {
      final auth = newAuth();
      final r = await auth.login(loginId: '13800138000', password: 'abc123456');
      expect(r.error, AuthError.notRegistered);
    });

    test('重启 App 后登录状态与账号都还在（换新实例读同一目录）', () async {
      final first = newAuth();
      await first.register(
        phone: '13800138000',
        username: 'u13800138000',
        name: '张教练',
        password: 'abc123456',
        passwordConfirm: 'abc123456',
      );

      // 新实例 = 模拟重启：不共享任何内存状态，只读同一个目录
      final second = newAuth();
      final user = await second.currentUser();
      expect(user, isNotNull);
      expect(user!.name, '张教练');
      expect(await second.hasAnyAccount(), isTrue);

      // 而且还能用原密码登录
      await second.logout();
      expect(await second.currentUser(), isNull);
      expect((await second.login(loginId: '13800138000', password: 'abc123456')).ok,
          isTrue);
    });

    test('密码不会以明文写进文件', () async {
      final auth = newAuth();
      await auth.register(
        phone: '13800138000',
        username: 'u13800138000',
        name: '张教练',
        password: 'SuperSecret123',
        passwordConfirm: 'SuperSecret123',
      );

      final raw = File('${tmp.path}/users.json').readAsStringSync();
      expect(raw.contains('SuperSecret123'), isFalse,
          reason: '明文密码绝不能落盘');
      expect(raw.contains('password_hash'), isTrue);
    });

    test('数据文件损坏时不崩溃，且保留原文件便于排查', () async {
      File('${tmp.path}/users.json').writeAsStringSync('{ 这不是合法 JSON');

      final auth = newAuth();
      // 不抛异常
      expect(await auth.hasAnyAccount(), isFalse);
      expect(await auth.currentUser(), isNull);

      // 原文件被改名备份，而不是直接删掉
      final backups = tmp
          .listSync()
          .where((f) => f.path.contains('.corrupt-'))
          .toList();
      expect(backups, isNotEmpty, reason: '损坏文件应备份保留');
    });
  });

  // -------------------------------------------------------------------------
  group('运动员仓库', () {
    test('新增后能查到，字段完整', () async {
      final repo = newRepo('t_1');
      final a = await repo.create(
        name: '李四',
        gender: AthleteGender.male,
        event: '100m',
        level: AthleteLevel.college,
        heightCm: 178,
        weightKg: 70,
      );

      expect(a.athleteId, startsWith('at_'));
      expect(a.teamId, 't_1');
      expect(a.hasHeight, isTrue);

      final list = await repo.list();
      expect(list.length, 1);
      expect(list.first.name, '李四');
    });

    test('队伍隔离：看不到别的队的数据', () async {
      final a1 = newRepo('t_1');
      final a2 = newRepo('t_2');
      await a1.create(
        name: '队员甲',
        gender: AthleteGender.male,
        event: '100m',
        level: AthleteLevel.college,
      );

      expect((await a1.list()).length, 1);
      expect((await a2.list()), isEmpty,
          reason: '多租户隔离是最容易漏的一环');
    });

    test('软删除后不在列表里，但数据仍可恢复', () async {
      final repo = newRepo('t_1');
      final a = await repo.create(
        name: '王五',
        gender: AthleteGender.female,
        event: '200m',
        level: AthleteLevel.highSchool,
      );

      await repo.softDelete(a.athleteId);
      expect(await repo.list(), isEmpty);
      // 记录没被真删 —— 分析结果还挂在它上面
      expect((await repo.list(includeDeleted: true)).length, 1);

      await repo.restore(a.athleteId);
      expect((await repo.list()).length, 1);
    });

    test('未填身高时 hasHeight 为 false —— 界面据此提示', () async {
      final repo = newRepo('t_1');
      final a = await repo.create(
        name: '赵六',
        gender: AthleteGender.male,
        event: '100m',
        level: AthleteLevel.amateur,
      );
      expect(a.hasHeight, isFalse);
    });

    test('契约转换保留关键字段', () async {
      final repo = newRepo('t_1');
      final a = await repo.create(
        name: '孙七',
        gender: AthleteGender.male,
        event: '400m',
        level: AthleteLevel.subElite,
        heightCm: 182,
        weightKg: 75,
      );

      final contract = a.toContract();
      expect(contract.name, '孙七');
      expect(contract.heightCm, 182);
      expect(contract.event, '400m');
      expect(contract.level, AthleteLevel.subElite);
    });
  });

  // -------------------------------------------------------------------------
  group('登录页', () {
    testWidgets('没有账号时默认进入注册模式', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(
          auth: newAuth(),
          onLoggedIn: () {},
          initialRegisterMode: true,
        ),
      ));
      await tester.pump();

      expect(find.text('注册并进入'), findsOneWidget);
      expect(find.text('昵称'), findsOneWidget);
      expect(find.text('确认密码'), findsOneWidget);
      // 注册时三个字段一起问：用户名（必填）+ 昵称 + 手机号（选填）。
      // 用户名必填是因为它是提交分析时服务端认账号的依据 ——
      // 以前"手机号 / 用户名二选一"，用手机号注册的账号在服务端
      // 没有名字，提交分析只会收到「请先登录」。
      expect(find.text('用户名'), findsWidgets);
      expect(find.text('手机号（选填）'), findsWidgets);
    });

    testWidgets('有账号时默认是登录模式', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(auth: newAuth(), onLoggedIn: () {}),
      ));
      await tester.pump();

      expect(find.text('登录'), findsOneWidget);
      expect(find.text('昵称'), findsNothing);
      expect(find.text('还没有账号？去注册'), findsOneWidget);
    });

    testWidgets('可以切换到注册模式', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(auth: newAuth(), onLoggedIn: () {}),
      ));
      await tester.pump();

      await tester.tap(find.text('还没有账号？去注册'));
      await tester.pump();

      expect(find.text('注册并进入'), findsOneWidget);
      expect(find.text('已有账号？去登录'), findsOneWidget);
    });

    testWidgets('表单校验拦住非法输入', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(
          auth: newAuth(),
          onLoggedIn: () {},
          initialRegisterMode: true,
        ),
      ));
      await tester.pump();

      // 直接提交空表单。
      // ⚠️ 必须先滚动 —— 注册表单有三个字段，提交按钮在小屏测试环境里
      //    会被挤到屏幕外，tap 不中。
      await tester.ensureVisible(find.text('注册并进入'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('注册并进入'));
      await tester.pump();

      // 用户名现在是必填 —— 它是提交分析时服务端认账号的依据
      expect(find.text('请填写用户名'), findsOneWidget);
      expect(find.text('请填写昵称'), findsOneWidget);
      expect(find.text('密码至少 6 位'), findsOneWidget);
    });

    testWidgets('注册表单同时要用户名、昵称、手机号三项', (tester) async {
      // ⚠️ 这条守着真实缺陷：
      //    注册表单原本是"手机号 / 用户名"二选一。用手机号注册的账号
      //    在服务端没有名字，提交分析只会收到「请先登录」——
      //    而用户明明已经登录。一个身份分两种是问题的源头。
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(
          auth: newAuth(),
          onLoggedIn: () {},
          initialRegisterMode: true,
        ),
      ));
      await tester.pump();

      expect(find.text('用户名'), findsWidgets);
      expect(find.text('昵称'), findsWidgets);
      expect(find.text('手机号（选填）'), findsWidgets);
      // 二选一的切换器必须消失
      expect(find.text('手机号'), findsNothing);
      expect(find.byType(SegmentedButton<bool>), findsNothing);
    });

    testWidgets('手机号留空不拦，填了才校验', (tester) async {
      // 手机号是选填：留空应当放行（错误出现在别的字段上），
      // 填了非法值才报错。这两件事必须分开。
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(
          auth: newAuth(),
          onLoggedIn: () {},
          initialRegisterMode: true,
        ),
      ));
      await tester.pump();

      await tester.ensureVisible(find.text('注册并进入'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('注册并进入'));
      await tester.pump();

      expect(find.text('请输入 11 位手机号'), findsNothing,
          reason: '手机号留空不该报格式错');
    });

    testWidgets('登录框对字母用户名与手机号都不拦', (tester) async {
      // ⚠️ 这条守着真实缺陷：
      //    登录框原本只认 11 位手机号，导致字母用户名
      //    （如管理员 MazingLIU）完全无法登录。
      //
      // 登录模式下不做格式校验 —— 账号可能是手机号也可能是用户名，
      // 在这里猜类型只会把合法输入挡在门外。
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(
          auth: newAuth(),
          onLoggedIn: () {},
          initialRegisterMode: false,   // 登录模式
        ),
      ));
      await tester.pump();

      final field = find.byType(TextFormField).first;

      for (final id in ['MazingLIU', '13800138000']) {
        await tester.enterText(field, id);
        await tester.pump();
        expect(find.text('请输入 11 位手机号'), findsNothing,
            reason: '「$id」不该被格式校验拦住');
        expect(find.text('用户名需 2–24 位，可用字母、数字、下划线'), findsNothing,
            reason: '「$id」不该被格式校验拦住');
      }

      // 留空才提示，且提示要说清两种都认
      await tester.enterText(field, '');
      await tester.pump();
      await tester.ensureVisible(find.text('登录'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('登录'));
      await tester.pump();
      expect(find.text('请输入手机号或用户名'), findsOneWidget);
    });

    testWidgets('提示账号仅存本机', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: LoginPage(auth: newAuth(), onLoggedIn: () {}),
      ));
      await tester.pump();

      expect(find.textContaining('账号仅保存在本机'), findsOneWidget,
          reason: '必须说明，否则用户会以为换设备还能登录');
    });
  });
}
