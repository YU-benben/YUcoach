import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/local_store.dart';
import 'package:yu_coach/data/session_repository.dart';
import 'package:yu_coach/domain/session_record.dart';
import 'package:yu_coach/models/models.dart';

/// 采集记录仓库的测试。
///
/// ⚠️ 只用 test()，不要加 testWidgets()（原因见 widget_test.dart 顶部说明）。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tmp;

  setUp(() => tmp = Directory.systemTemp.createTempSync('yucoach_sess_'));
  tearDown(() {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  SessionRepository repo(String teamId) => SessionRepository(
        teamId: teamId,
        indexStore: LocalStore(fileName: 'sessions.json', baseDir: tmp),
        analysisStore:
            LocalStore(fileName: 'analyses_store.json', baseDir: tmp),
      );

  Future<SessionRecord> makeSession(
    SessionRepository r, {
    String athleteId = 'at_1',
    String name = '张三',
  }) =>
      r.create(
        athleteId: athleteId,
        athleteName: name,
        testType: SessionTestType.acceleration,
        view: SessionView.side,
        videoPath: 'content://video/1',
        videoFileName: 'run.mp4',
        fileSizeBytes: 12 * 1024 * 1024,
        durationMs: 10000,
        width: 1920,
        height: 1080,
        fpsDeclared: 240,
        frameCount: 2400,
        cameraDistanceM: 10,
        cameraHeightM: 1.2,
        hasLaneLine: true,
        cameraFollowed: false,
      );

  group('新建记录', () {
    test('字段完整落盘，初始状态为已上传', () async {
      final r = repo('t_1');
      final s = await makeSession(r);

      expect(s.sessionId, startsWith('s_'));
      expect(s.teamId, 't_1');
      expect(s.status, SessionStatus.uploaded);
      expect(s.fpsDeclared, 240);
      expect(s.frameCount, 2400);
      expect(s.cameraDistanceM, 10);
      expect(s.hasLaneLine, isTrue);
      expect(s.cameraFollowed, isFalse);

      final list = await r.list();
      expect(list.length, 1);
      expect(list.first.athleteName, '张三');
    });

    test('采集信息完整时 captureInfoComplete 为 true', () async {
      final r = repo('t_1');
      final s = await makeSession(r);
      expect(s.captureInfoComplete, isTrue);
    });

    test('队伍隔离', () async {
      final a = repo('t_1');
      final b = repo('t_2');
      await makeSession(a);
      expect((await a.list()).length, 1);
      expect(await b.list(), isEmpty);
    });

    test('按运动员筛选', () async {
      final r = repo('t_1');
      await makeSession(r, athleteId: 'at_1', name: '甲');
      await makeSession(r, athleteId: 'at_2', name: '乙');

      expect((await r.list()).length, 2);
      expect((await r.list(athleteId: 'at_1')).length, 1);
      expect((await r.countForAthlete('at_2')), 1);
      expect((await r.countForAthlete('at_3')), 0);
    });

    test('countByAthlete 汇总正确', () async {
      final r = repo('t_1');
      await makeSession(r, athleteId: 'at_1');
      await makeSession(r, athleteId: 'at_1');
      await makeSession(r, athleteId: 'at_2');

      final counts = await r.countByAthlete();
      expect(counts['at_1'], 2);
      expect(counts['at_2'], 1);
    });
  });

  group('状态流转', () {
    test('标记排队会记录任务 id', () async {
      final r = repo('t_1');
      final s = await makeSession(r);
      await r.markQueued(s.sessionId, 'task_abc');

      final after = await r.findById(s.sessionId);
      expect(after!.status, SessionStatus.queued);
      expect(after.taskId, 'task_abc');
    });

    test('分析完成：写入结果并回填帧率与质量分', () async {
      final r = repo('t_1');
      final s = await makeSession(r);

      final result = AnalysisResult.fromJson(
        _minimalAnalysis(fpsVerified: 240, qualityScore: 78),
      );
      await r.markAnalyzed(s.sessionId, 'a_1', result);

      final after = await r.findById(s.sessionId);
      expect(after!.status, SessionStatus.done);
      expect(after.analysisId, 'a_1');
      expect(after.qualityScore, 78);
      expect(after.fpsVerified, 240,
          reason: '服务端校验的帧率要回填 —— 之后所有时间换算以它为准');
      expect(after.isAnalyzed, isTrue);
      expect(after.analyzedAt, isNotNull);
    });

    test('分析结果可按 id 取回', () async {
      final r = repo('t_1');
      final s = await makeSession(r);
      await r.markAnalyzed(
        s.sessionId,
        'a_1',
        AnalysisResult.fromJson(_minimalAnalysis()),
      );

      final loaded = await r.loadAnalysis('a_1');
      expect(loaded, isNotNull);
      expect(loaded!.session.athlete.name, '张三');
    });

    test('取不存在的分析结果返回 null，不抛异常', () async {
      final r = repo('t_1');
      expect(await r.loadAnalysis('nope'), isNull);
    });

    test('分析失败必须记录原因', () async {
      final r = repo('t_1');
      final s = await makeSession(r);
      await r.markFailed(s.sessionId, '帧率校验未通过：声明 30fps，实际步频推算为 240fps');

      final after = await r.findById(s.sessionId);
      expect(after!.status, SessionStatus.failed);
      expect(after.isFailed, isTrue);
      // 只说「失败」是没用的，必须能告诉用户为什么
      expect(after.errorMessage, contains('帧率'));
    });

    test('软删除后不在列表，但数据仍在', () async {
      final r = repo('t_1');
      final s = await makeSession(r);
      await r.softDelete(s.sessionId);

      expect(await r.list(), isEmpty);
      expect((await r.list(includeDeleted: true)).length, 1);
      // 分析结果不受影响 —— 记录删了但结果还在，可恢复
    });
  });

  group('持久化健壮性', () {
    test('重启后记录仍在（换新实例读同一目录）', () async {
      await makeSession(repo('t_1'), name: '李四');

      final fresh = repo('t_1');
      final list = await fresh.list();
      expect(list.length, 1);
      expect(list.first.athleteName, '李四');
    });

    test('一条坏记录不会让整个列表打不开', () async {
      final r = repo('t_1');
      await makeSession(r);

      // 手工往文件里塞一条缺必需字段的记录
      final store = LocalStore(fileName: 'sessions.json', baseDir: tmp);
      final doc = await store.read();
      (doc['sessions'] as List).add({'session_id': 'broken'});
      await store.write(doc);

      final fresh = repo('t_1');
      final list = await fresh.list();
      expect(list.length, 1, reason: '坏记录应被跳过，好记录仍可读');
    });

    test('记录按拍摄时间倒序', () async {
      final r = repo('t_1');
      final a = await makeSession(r, name: '先');
      await Future<void>.delayed(const Duration(milliseconds: 5));
      final b = await makeSession(r, name: '后');

      final list = await r.list();
      expect(list.first.sessionId, b.sessionId);
      expect(list.last.sessionId, a.sessionId);
    });
  });
  group('契约解析的诊断能力', () {
    // 这一组测试锁定的是一个**开发者体验**特性，看似不重要，但代价真实：
    //
    // 生成代码原本对枚举失败只抛 "Null check operator used on a null value"，
    // 报错位置在模型内部某一行，既不说哪个字段，也不说收到了什么值。
    // 本项目的开发过程中，一个拼错的枚举值（写了 'none'，
    // 而合法值是 fixed/slight_pan/strong_pan）因此耗费了大量排查时间。
    //
    // 现在错误信息必须直接指出：字段名、收到的值、合法取值集合。
    // 这不是锦上添花 —— 契约有 28 个枚举、32 个模型，
    // 没有可定位的错误信息，联调成本会成倍上升。

    test('未知枚举值：报错要指出字段名、收到的值和合法取值', () {
      final bad = _minimalAnalysis();
      (bad['session'] as Map<String, dynamic>)['camera_motion'] = {
        'level': 'none', // 合法值是 fixed / slight_pan / strong_pan
        'is_tracking': false,
      };

      expect(
        () => AnalysisResult.fromJson(bad),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            // 报错包含字段名、实际收到的值、以及合法取值集合。
            // 有这三样就足以定位，不需要完整嵌套路径。
            allOf(
              contains('level'),
              contains('none'),
              contains('fixed'),
              contains('slight_pan'),
            ),
          ),
        ),
      );
    });

    test('缺字段：报错要说清是缺失而不是取值错误', () {
      final bad = _minimalAnalysis();
      (bad['session'] as Map<String, dynamic>).remove('view_detected');

      expect(
        () => AnalysisResult.fromJson(bad),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            contains('view_detected'),
          ),
        ),
      );
    });

    test('嵌套对象类型异常：报错要指出期望对象而不是空指针', () {
      final bad = _minimalAnalysis();
      (bad['session'] as Map<String, dynamic>)['camera_motion'] = 'not a map';

      expect(
        () => AnalysisResult.fromJson(bad),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            contains('期望 JSON 对象'),
          ),
        ),
      );
    });
  });
}

/// 一份最小的合法分析结果，供状态流转测试使用。
///
/// 注意 camera_motion / reference_scale 位于 **session 下**，不是根级 ——
/// 它们描述的是这次采集本身的条件，不是分析结论。
/// 放错层级会让 fromJson 静默拿到 null map，然后在 null check 处炸掉，
/// 报错信息完全指不到真正的原因。
Map<String, dynamic> minimalAnalysisForDebug({
  double fpsVerified = 240,
  double qualityScore = 78,
}) =>
    _minimalAnalysis(fpsVerified: fpsVerified, qualityScore: qualityScore);

Map<String, dynamic> _minimalAnalysis({
  double fpsVerified = 240,
  double qualityScore = 78,
}) =>
    {
      'schema_version': '1.0.0',
      'analysis_id': 'a_1',
      'session': {
        'schema_version': '1.0.0',
        'session_id': 's_1',
        'team_id': 't_1',
        'athlete': {
          'athlete_id': 'at_1',
          'name': '张三',
          'gender': 'male',
          'event': '100m',
          'level': 'college',
        },
        'recorded_at': '2026-03-14T10:00:00+08:00',
        'test_type': 'acceleration',
        'view': 'side',
        // 算法自动判定的方位。与用户声明的 view 比对，不一致要提示。
        'view_detected': 'side',
        'view_agreement': true,
        'capture': {
          'resolution': {'width': 1920, 'height': 1080},
          'frame_count': 2400,
          'duration_ms': 10000,
          'fps_declared': 240,
          'fps_verified': fpsVerified,
          'fps_verify': {
            // 合法取值只有 verified / warning / rejected
            'status': 'verified',
            'methods': ['container_metadata', 'frame_count_duration'],
            'agreement_pct': 100.0,
            'method_results': <String, dynamic>{},
          },
        },
        'camera_motion': {
          // 合法取值只有 fixed / slight_pan / strong_pan
          'level': 'fixed',
          'is_tracking': false,
        },
        'reference_scale': {
          'method': 'lane_line',
          'valid_per_frame': false,
        },
        'quality_score': qualityScore,
        'status': 'done',
      },
      'summary': {
        'headline': '整体良好',
        'major_count': 0,
        'minor_count': 0,
        'insufficient_count': 0,
      },
      'quality_score': qualityScore,
      'versions': {
        'algo_version': '1.0.0',
        'model_version': '1.0.0',
        'rule_version': '1.0.0',
        'std_version': '1.0.0',
      },
      'metrics': [],
      'phases_detected': [],
      'keyframes': [],
      'findings': [],
    };
