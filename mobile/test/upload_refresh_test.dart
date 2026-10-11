import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/athlete_repository.dart';
import 'package:yu_coach/data/local_store.dart';
import 'package:yu_coach/data/session_repository.dart';
import 'package:yu_coach/models/models.dart';
import 'package:yu_coach/pages/data_page.dart';
import 'package:yu_coach/pages/refreshable.dart';
import 'package:yu_coach/pages/upload_page.dart';

/// 回归测试：上传页与数据页必须能在数据变化后刷新。
///
/// ⚠️ 只用 test()，不要加 testWidgets()。
///
/// 为什么不写成 widget 测试：本仓库的 Flutter 测试环境里，
/// `tester.pump()` 无法推进**真实文件 I/O** 的 future ——
/// 测试会一直挂在 await 上（30 秒超时能触发，但等满 30 秒毫无意义）。
/// 表现就是整个文件挂起。纯 test() 不受此限制。
/// 所以这类「数据流」验证一律用纯测试。
///
/// 锁定的是一个真实缺陷：
///   主界面用 IndexedStack 一次性创建全部页面，所以上传页的 initState
///   只在 App 启动时跑一次。用户先添加运动员、再切到上传页时，
///   上传页手里还是启动时的空列表，会一直显示「请先添加运动员」，
///   而且没有任何办法刷新 —— 上传流程就此断掉。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tmp;

  setUp(() => tmp = Directory.systemTemp.createTempSync('yucoach_refresh_'));
  tearDown(() {
    if (tmp.existsSync()) {
      try {
        tmp.deleteSync(recursive: true);
      } catch (_) {
        // 测试进程仍持有句柄时删不掉，不影响测试结论
      }
    }
  });

  AthleteRepository newRepo() => AthleteRepository(
        store: LocalStore(fileName: 'athletes.json', baseDir: tmp),
        teamId: 't_1',
      );

  group('数据变化后可被重新读取', () {
    test('新增运动员后，重新 list() 能读到 —— 这是 reload 的基础', () async {
      final repo = newRepo();

      // App 刚启动：没有运动员，上传页会显示「请先添加运动员」
      expect(await repo.list(), isEmpty);

      // 用户在「运动员」页添加
      await repo.create(
        name: '张三',
        gender: AthleteGender.male,
        event: '100m',
        level: AthleteLevel.college,
        heightCm: 178,
      );

      // 上传页 reload() 做的事情就是再 list() 一次。
      // 能读到，说明「切回上传页看到运动员」成立。
      final after = await repo.list();
      expect(after.length, 1,
          reason: 'reload 必须能看到新增的运动员，否则上传流程断掉');
      expect(after.first.name, '张三');
    });

    test('删除运动员后，重新 list() 不再返回 —— 避免停在无效档案上', () async {
      final repo = newRepo();
      final a = await repo.create(
        name: '李四',
        gender: AthleteGender.female,
        event: '200m',
        level: AthleteLevel.highSchool,
      );

      expect((await repo.list()).length, 1);
      await repo.softDelete(a.athleteId);
      expect(await repo.list(), isEmpty);
    });

    test('换新的仓库实例也能读到 —— reload 不依赖内存缓存', () async {
      await newRepo().create(
        name: '王五',
        gender: AthleteGender.male,
        event: '400m',
        level: AthleteLevel.subElite,
      );

      // 模拟「页面重新构造」：全新实例，只读同一个目录
      final fresh = newRepo();
      expect((await fresh.list()).length, 1);
    });
  });

  group('刷新后实例不同也不出错', () {
    // 锁定的真实崩溃（手机上出过）：
    //   'package:flutter/src/material/dropdown.dart': Failed assertion:
    //   There should be exactly one item with [DropdownButton]'s value:
    //   Instance of 'AthleteRecord'.
    //
    // 原因：DropdownButtonFormField 用 == 在 items 里找匹配项，
    // 而 AthleteRecord 原本走默认的**引用比较**。每次 reload() 都从文件
    // 反序列化出全新实例，内容一样但引用不同 —— 匹配不到，断言直接炸。
    //
    // 两道防线，这里各测一道：
    //   1. 记录类按 id 判定相等（本组测试）
    //   2. 上传页的下拉值用 id 字符串而不是对象（见 upload_page.dart）

    test('同一个运动员的两次反序列化结果相等', () async {
      final repo = newRepo();
      final created = await repo.create(
        name: '张三',
        gender: AthleteGender.male,
        event: '100m',
        level: AthleteLevel.college,
        heightCm: 178,
      );

      // 模拟 reload()：全新实例，只读同一个目录
      final reloaded = (await newRepo().list()).first;

      expect(identical(created, reloaded), isFalse,
          reason: '前提：确实是两个不同实例，否则这个测试没有意义');
      expect(reloaded, equals(created),
          reason: '内容相同就该判为相等，否则下拉框匹配会失败');
      expect(reloaded.hashCode, equals(created.hashCode),
          reason: 'hashCode 必须与 == 一致，否则 Set/Map 里行为异常');
    });

    test('改过字段之后仍判为同一个运动员', () async {
      final repo = newRepo();
      final a = await repo.create(
        name: '李四',
        gender: AthleteGender.female,
        event: '200m',
        level: AthleteLevel.highSchool,
      );

      await repo.update(a.copyWith(name: '李四（改名）', heightCm: 170));
      final after = (await newRepo().list()).first;

      // 只比 id，不比全部字段 —— 否则改个名字就会让"同一个人"变成两个
      expect(after, equals(a));
    });

    test('不同运动员不相等', () async {
      final repo = newRepo();
      final a = await repo.create(
        name: '甲',
        gender: AthleteGender.male,
        event: '100m',
        level: AthleteLevel.college,
      );
      final b = await repo.create(
        name: '乙',
        gender: AthleteGender.male,
        event: '100m',
        level: AthleteLevel.college,
      );

      expect(a, isNot(equals(b)));
    });

    test('采集记录同样按 id 判定，便于列表去重与查找', () async {
      final store = LocalStore(fileName: 'sessions.json', baseDir: tmp);
      final repo = SessionRepository(
        teamId: 't_1',
        indexStore: store,
        analysisStore:
            LocalStore(fileName: 'analyses_store.json', baseDir: tmp),
      );

      final s = await repo.create(
        athleteId: 'at_1',
        athleteName: '张三',
        testType: SessionTestType.acceleration,
        view: SessionView.side,
      );

      final again = (await SessionRepository(
        teamId: 't_1',
        indexStore: LocalStore(fileName: 'sessions.json', baseDir: tmp),
        analysisStore:
            LocalStore(fileName: 'analyses_store.json', baseDir: tmp),
      ).list())
          .first;

      expect(identical(s, again), isFalse);
      expect(again, equals(s));
    });
  });

  group('刷新接口已正确接上', () {
    // 这是**编译期**检查，不是运行期断言。
    //
    // 主界面靠 `GlobalKey<UploadPageState>` + `Refreshable` 才能实现
    // 「切 Tab 时刷新」。这条链路断了不会报错，只会表现为
    // 「上传页一直显示请先添加运动员」这种很难查的症状。
    //
    // 下面两行赋值要求类型关系成立：一旦有人去掉 implements Refreshable，
    // 或改了 reload() 的签名，这个文件就编译不过 —— 立刻暴露。
    test('UploadPageState 与 DataPageState 都实现 Refreshable', () {
      // 下面的函数声明让类型关系在**编译期**被检查：
      // 参数写死为具体的 State 类型，返回写死为 Refreshable。
      // 一旦有人去掉 implements Refreshable，或改了 reload() 的签名，
      // 这个文件立刻编译不过。
      Refreshable asRefreshableFromUpload(UploadPageState s) => s;
      Refreshable asRefreshableFromData(DataPageState s) => s;

      // 只用到函数本身（类型已检查过），不实际调用
      expect(asRefreshableFromUpload, isNotNull);
      expect(asRefreshableFromData, isNotNull);
    });
  });
}
