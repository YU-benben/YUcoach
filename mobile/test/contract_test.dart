import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/analysis_repository.dart';
import 'package:yu_coach/data/report_view_model.dart';
import 'package:yu_coach/models/models.dart';

/// 契约 → 生成的模型 → 界面模型 的一致性验证（**纯逻辑，不含 widget**）。
///
/// ⚠️ 本文件只允许用 test()，不要加 testWidgets()。
///
/// 原因：testWidgets 运行在 FakeAsync 时间域里，而 test() 是真异步。
/// 两者在同一个文件里交叉时，rootBundle 的加载 future 永远等不到时间推进，
/// 表现为**整个文件挂起**（不报错、不超时，极难定位）。
/// 界面渲染相关的测试放在 widget_test.dart，两者分开跑。
///
/// 这个测试存在的意义：证明「契约、生成的 Dart 代码、界面模型」三者对同一份
/// 数据的理解是一致的。任何一环改了字段名或语义，这里都会立刻失败。
///
/// 三种数据状态都必须覆盖 —— 尤其 empty 那份：
/// 教练第一次用普通视频拍，得到的就是这个结果。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('契约与模型一致性', () {
    test('analysis_normal.json 可解析且关键字段正确', () async {
      final r = await FixtureDataSource.loadScenario('normal');

      expect(r.session.athlete.name, '张三');
      expect(r.session.view, SessionView.side);
      expect(r.session.capture.fpsDeclared, 30.0);
      expect(r.session.capture.fpsVerified, 240.0);
      expect(r.qualityScore, 78.0);

      final trunk = r.metrics.firstWhere((m) => m.metricId == 'trunk_lean');
      expect(trunk.view, SessionView.side);
      expect(trunk.phase, MetricPhase.acceleration);
      expect(trunk.reliable, isTrue);
      expect(trunk.ref!.applicablePhase, MetricPhase.acceleration);
      expect(trunk.ref!.source, ReferenceRangeRefSource.literature);

      // 一条 major、一条 minor、一条 insufficient_data
      expect(r.findings.length, 3);
      expect(r.findings[0].severity, FindingSeverity.major);
      expect(r.findings[0].drills.first.cue, isNotEmpty);
      expect(r.findings[2].severity, FindingSeverity.insufficientData);

      expect(r.keyframes.length, 3);
      expect(r.keyframes.first.pixelsPerMeter, isNotNull);
    });

    test('analysis_low_confidence.json 解析出低置信状态', () async {
      final r = await FixtureDataSource.loadScenario('lowConfidence');

      final contact =
          r.metrics.firstWhere((m) => m.metricId == 'ground_contact_time');
      expect(contact.reliable, isFalse);
      expect(contact.reliabilityNote, isNotNull);
      expect(contact.confidence!, lessThan(0.5));

      expect(r.session.capture.fpsVerify.status, FpsVerifyStatus.warning);

      final major =
          r.findings.firstWhere((f) => f.severity == FindingSeverity.major);
      expect(major.caveat, isNotNull);
      expect(major.basis, FindingBasis.lowReliability);
      // 契约规定：依据的指标 reliable=false 时，结论置信度必须 ≤ 0.5
      expect(major.confidence!, lessThanOrEqualTo(0.5));
    });

    test('analysis_empty.json 解析出全部不可测', () async {
      final r = await FixtureDataSource.loadScenario('empty');

      expect(r.metrics.every((m) => m.insufficient != null), isTrue);
      expect(r.metrics.every((m) => m.value == null), isTrue);
      expect(r.keyframes, isEmpty);
      expect(r.phasesDetected, isEmpty);

      // 覆盖多种不足原因 —— 它们对应的建议完全不同
      final reasons = r.metrics.map((m) => m.insufficient!.reason).toSet();
      expect(reasons.length, greaterThanOrEqualTo(4));
      expect(reasons, contains(InsufficientReason.frameRateUnverified));
      expect(reasons, contains(InsufficientReason.viewMismatch));
      expect(reasons, contains(InsufficientReason.noReferenceScale));

      // 建议必须可操作，不得为空
      for (final m in r.metrics) {
        expect(m.insufficient!.suggestion, isNotEmpty,
            reason: '${m.metricId} 缺少可操作建议');
      }
    });

    test('资产确实被打包：三份 fixture 都能通过 rootBundle 加载', () async {
      // 走真实资产路径。若 pubspec 的 assets 配置错了（例如写了包外路径
      // `../samples/fixtures/`，Flutter 会静默忽略），这里会失败。
      expect(FixtureDataSource.availableScenarios.length, 3);
      for (final scenario in FixtureDataSource.availableScenarios) {
        final r = await FixtureDataSource.loadScenario(scenario);
        expect(r.metrics, isNotEmpty, reason: '$scenario 加载成功但没有指标');
      }
    });
  });

  group('界面模型归约', () {
    test('三种数据状态分别归约正确', () async {
      final normal = await FixtureDataSource.loadScenario('normal');
      final low = await FixtureDataSource.loadScenario('lowConfidence');
      final empty = await FixtureDataSource.loadScenario('empty');

      final okMetric =
          normal.metrics.firstWhere((m) => m.metricId == 'trunk_lean');
      expect(toMetricView(okMetric).state, MetricState.normal);
      expect(toMetricView(okMetric).hasReference, isTrue);

      final lowMetric =
          low.metrics.firstWhere((m) => m.metricId == 'ground_contact_time');
      final lowView = toMetricView(lowMetric);
      expect(lowView.state, MetricState.lowConfidence);
      expect(lowView.valueText, isNot('——'),
          reason: '低置信仍要显示数值，隐藏会让教练怀疑数据被挑选');
      expect(lowView.note, isNotNull);

      final emptyView = toMetricView(empty.metrics.first);
      expect(emptyView.state, MetricState.insufficient);
      expect(emptyView.valueText, '——');
      expect(emptyView.insufficientSuggestion, isNotEmpty);
    });

    test('质量分决定免责强度', () {
      expect(qualityBannerFor(86), QualityBanner.none);
      expect(qualityBannerFor(60), QualityBanner.partial);
      expect(qualityBannerFor(18), QualityBanner.referenceOnly);
    });

    test('数据不足原因有用户化措辞，不暴露英文枚举', () {
      final label = reasonLabel(InsufficientReason.noReferenceScale);
      expect(label, '缺少参考尺度');
      expect(label, isNot(contains('_')));
    });

    test('界面模型不丢失指标：三份 fixture 的指标都能归约', () async {
      for (final scenario in FixtureDataSource.availableScenarios) {
        final r = await FixtureDataSource.loadScenario(scenario);
        final views = r.metrics.map(toMetricView).toList();
        expect(views.length, r.metrics.length);
        for (final v in views) {
          expect(v.nameZh, isNotEmpty, reason: '$scenario 有指标名称为空');
        }
      }
    });
  });
}
