import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/analysis_repository.dart';
import 'package:yu_coach/data/report_view_model.dart';
import 'package:yu_coach/widgets/metric_row.dart';

/// 界面渲染冒烟测试（**只用 testWidgets，且每个测试只渲染一次**）。
///
/// 本文件刻意保持最小。原因记录如下，避免后人"顺手加测试"把构建搞挂：
///
///   · 不要加 test()。testWidgets 跑在 FakeAsync 时间域里，test() 是真异步，
///     两者在同一文件交叉时 rootBundle 的加载 future 永远等不到时间推进，
///     表现为**整个文件挂起**（不报错、不超时，极难定位）。
///
///   · 不要在一个 testWidgets 里循环多轮 pumpWidget。多次挂载/卸载的累积
///     会让后续测试挂起。
///
///   · 断言保持简单。复杂的文本匹配（大量 findsWidgets）+ 多测试组合
///     也观察到过挂起。
///
/// 需要覆盖更多数据组合时，放 contract_test.dart 用纯 test() 做 ——
/// 那里测的是数据与归约逻辑，本来就该是纯逻辑测试，跑得快也稳定。
///
/// 本文件的价值：证明真实 MetricRow 组件三种状态都能渲染出来。
/// 渲染的是真组件，不是在测试里重抄一遍 UI —— 重抄的话改坏了组件也发现不了。
void main() {
  Future<List<MetricView>> viewsOf(String scenario) async {
    final r = await FixtureDataSource.loadScenario(scenario);
    return r.metrics.map(toMetricView).toList();
  }

  Future<void> pumpMetrics(WidgetTester tester, List<MetricView> views) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ListView(
          children: [for (final v in views) MetricRow(view: v)],
        ),
      ),
    ));
    await tester.pump();
  }

  testWidgets('正常指标能渲染', (tester) async {
    final views = await viewsOf('normal');
    final ok = views.where((v) => v.state == MetricState.normal).toList();
    expect(ok, isNotEmpty);

    await pumpMetrics(tester, ok);
    expect(find.text(ok.first.nameZh), findsOneWidget);
  });

  testWidgets('低置信指标能渲染', (tester) async {
    final views = await viewsOf('lowConfidence');
    final low =
        views.where((v) => v.state == MetricState.lowConfidence).toList();
    expect(low, isNotEmpty, reason: '这份 fixture 必须有低置信指标');

    await pumpMetrics(tester, low);
    expect(find.text(low.first.nameZh), findsOneWidget);
  });

  testWidgets('数据不足指标能渲染', (tester) async {
    final views = await viewsOf('empty');
    expect(views.every((v) => v.state == MetricState.insufficient), isTrue);

    await pumpMetrics(tester, views);
    expect(find.text(views.first.nameZh), findsOneWidget);
  });
}
