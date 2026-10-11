import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/angle_catalog.dart';
import 'package:yu_coach/pose/angle_selection.dart';
import 'package:yu_coach/widgets/angle_picker_sheet.dart';

/// 角度选择状态的测试。
/// 内存里的持久化，测试用。
///
/// ⚠️ 必须定义在 main() **外面** —— Dart 不允许在函数体内声明类。
class MemStore extends AngleSelectionStore {
  MemStore();
  final data = <String, List<String>>{};

  @override
  Future<List<String>?> read(String group) async => data[group];

  @override
  Future<void> write(String group, List<String> ids) async {
    data[group] = List<String>.from(ids);
  }
}

void main() {
  group('选择状态', () {
    test('默认选中侧面 2 个、额状面 1 个', () async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      expect(sel.activeForView('side').length, 2);
      expect(sel.activeForView('front').length, 1);
      expect(sel.activeForView('back').length, 1);
    });

    test('默认不是全选（全选会挤成一团）', () async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();
      final total = AngleSelection.availableForView('side').length;
      expect(sel.activeForView('side').length, lessThan(total),
          reason: '默认全选的话第一次打开就是一堆角度挤在一起');
    });

    test('勾选与取消', () async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      expect(sel.isSelected('side', 'hip_angle_toeoff'), isFalse);
      await sel.toggle('side', 'hip_angle_toeoff');
      expect(sel.isSelected('side', 'hip_angle_toeoff'), isTrue);
      await sel.toggle('side', 'hip_angle_toeoff');
      expect(sel.isSelected('side', 'hip_angle_toeoff'), isFalse);
    });

    test('全选与全不选', () async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await sel.selectAll('side');
      expect(sel.activeForView('side').length,
          AngleSelection.availableForView('side').length);

      await sel.clear('side');
      expect(sel.activeForView('side'), isEmpty);
    });

    test('允许全不选（只想看骨架）', () async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();
      await sel.clear('side');
      expect(sel.isSelected('side', 'trunk_lean'), isFalse);
    });

    test('⚠️ 侧面与额状面的选择互不影响', () async {
      // 这是核心设计：侧面和额状面的角度不能混用。
      // 共用一个集合的话，切视角时选中的角度会全都不适用，
      // 画面变成空的，而用户不知道为什么。
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await sel.clear('side');
      expect(sel.activeForView('side'), isEmpty);
      expect(sel.activeForView('front').length, 1,
          reason: '清空侧面不该影响正面');

      await sel.selectAll('front');
      expect(sel.activeForView('side'), isEmpty,
          reason: '全选正面不该影响侧面');
    });

    test('正面与背面共用一组选择', () async {
      // 它们测的是同一类指标，让用户选两次很啰嗦。
      final sel = AngleSelection(store: MemStore());
      await sel.load();
      await sel.toggle('front', 'pelvis_tilt');

      expect(sel.isSelected('back', 'pelvis_tilt'), isTrue,
          reason: '正面选上的，背面也应当选上');
    });

    test('activeForView 会过滤掉不适用于该视角的角度', () async {
      // ⚠️ 最后一道防线：即使数据里混进了别的视角的 id，
      //    也不会画到画面上。
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      // 强行往侧面组里塞一个只适用于正面的角度
      await sel.toggle('front', 'pelvis_tilt');
      await sel.toggle('side', 'pelvis_tilt');

      for (final a in sel.activeForView('side')) {
        expect(a.views, contains('side'),
            reason: '${a.metricId} 不适用于侧面却被选中了');
      }
      expect(sel.activeForView('side').any((a) => a.metricId == 'pelvis_tilt'),
          isFalse);
    });

    test('选择会持久化', () async {
      final store = MemStore();
      final a = AngleSelection(store: store);
      await a.load();
      await a.toggle('side', 'shank_angle_touchdown');

      // 换一个实例读同一份存储
      final b = AngleSelection(store: store);
      await b.load();
      expect(b.isSelected('side', 'shank_angle_touchdown'), isTrue);
    });

    test('通知监听者', () async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();
      var n = 0;
      sel.addListener(() => n++);

      await sel.toggle('side', 'hip_angle_toeoff');
      expect(n, 1);
      await sel.selectAll('side');
      expect(n, 2);
    });

    test('pruneUnknown 清掉已不存在的角度 id', () async {
      // 场景：将来删掉某个角度定义后，用户本地还存着它的 id。
      // 不清的话界面上"已选 3 个"但只显示 2 个，而且那个看不见的
      // 选中项无法取消。
      final store = MemStore();
      store.data['angles_side'] = ['trunk_lean', '已删除的角度', '也不存在'];
      final sel = AngleSelection(store: store);
      await sel.load();

      final removed = sel.pruneUnknown();
      expect(removed, containsAll(['已删除的角度', '也不存在']));
      expect(sel.isSelected('side', 'trunk_lean'), isTrue,
          reason: '存在的角度不该被清掉');
      expect(sel.activeForView('side').length, 1);
    });

    test('本地存了空列表时不套用默认值', () async {
      // 用户主动"全不选"之后，下次打开不该又冒出默认角度。
      final store = MemStore();
      store.data['angles_side'] = [];
      final sel = AngleSelection(store: store);
      await sel.load();
      expect(sel.activeForView('side'), isEmpty,
          reason: '用户清空过，不该恢复默认');
    });
  });

  group('角度目录', () {
    test('侧面与额状面的角度不重叠', () {
      final side = anglesForView('side').map((a) => a.metricId).toSet();
      final frontal = anglesForView('front').map((a) => a.metricId).toSet();
      expect(side.intersection(frontal), isEmpty,
          reason: '同一个角度不能同时属于两个视角 —— 几何量不同');
    });

    test('正面与背面可用的角度相同', () {
      final front = anglesForView('front').map((a) => a.metricId).toSet();
      final back = anglesForView('back').map((a) => a.metricId).toSet();
      expect(front, back);
    });

    test('metric_id 唯一', () {
      final ids = angleCatalog.map((a) => a.metricId).toList();
      expect(ids.toSet().length, ids.length, reason: '有重复的 metric_id');
    });

    test('每个角度都有中文名与说明', () {
      for (final a in angleCatalog) {
        expect(a.nameZh.trim(), isNotEmpty, reason: '${a.metricId} 缺中文名');
        expect(a.description.trim(), isNotEmpty,
            reason: '${a.metricId} 缺说明');
      }
    });

    test('三点点角的 vertexIndex 指向中间那个点', () {
      for (final a in angleCatalog) {
        if (a.kind != AngleKind.threePoint) continue;
        expect(a.points.length, 3,
            reason: '${a.metricId} 是三点点角但点数不是 3');
        expect(a.vertexIndex, 1,
            reason: '${a.metricId} 的顶点下标不是 1 —— '
                'angleAt 约定第二个参数是顶点');
      }
    });

    test('线段角只有两个点', () {
      for (final a in angleCatalog) {
        if (a.kind != AngleKind.segmentFromVertical) continue;
        expect(a.points.length, 2,
            reason: '${a.metricId} 是线段角但点数不是 2');
      }
    });

    test('用到足部点的角度标了 derived', () {
      // ⚠️ 不标的话教练会把它当成和别的角度同等可信。
      for (final a in angleCatalog) {
        final usesFoot = a.points.any((p) =>
            p.startsWith('toe_') || p.startsWith('heel_'));
        if (usesFoot) {
          expect(a.derived, isTrue,
              reason: '${a.metricId} 用到了推导的足部点，但没有标记');
        }
      }
    });
  });

  group('选择面板', () {
    testWidgets('只列出当前视角适用的角度', (tester) async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: AnglePickerSheet(selection: sel, view: 'side'),
        ),
      ));
      await tester.pumpAndSettle();

      // 侧面的角度在
      expect(find.text('躯干前倾'), findsOneWidget);
      expect(find.text('着地膝角'), findsOneWidget);
      // 额状面的角度不在
      expect(find.text('骨盆倾斜'), findsNothing);
      expect(find.text('着地膝内扣'), findsNothing);
    });

    testWidgets('正面视角列出额状面角度', (tester) async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: AnglePickerSheet(selection: sel, view: 'front'),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('骨盆倾斜'), findsOneWidget);
      expect(find.text('躯干前倾'), findsNothing);
    });

    testWidgets('用推导点的角度标出「推导值」', (tester) async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: AnglePickerSheet(selection: sel, view: 'side'),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('推导值'), findsWidgets,
          reason: '踝角用到了推导的脚尖，必须标出来');
    });

    testWidgets('点击能切换选中状态', (tester) async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: AnglePickerSheet(selection: sel, view: 'side'),
        ),
      ));
      await tester.pumpAndSettle();

      expect(sel.isSelected('side', 'knee_angle_midstance'), isFalse);
      await tester.tap(find.text('支撑中期膝角'));
      await tester.pumpAndSettle();
      expect(sel.isSelected('side', 'knee_angle_midstance'), isTrue);
    });

    testWidgets('全选按钮生效', (tester) async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: AnglePickerSheet(selection: sel, view: 'side'),
        ),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.text('全选'));
      await tester.pumpAndSettle();
      expect(sel.activeForView('side').length,
          AngleSelection.availableForView('side').length);
    });
  });

  group('摘要栏', () {
    testWidgets('显示已选角度的中文名', (tester) async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: AngleSummaryBar(
            selection: sel,
            view: 'side',
            onTap: () {},
          ),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.textContaining('着地膝角'), findsOneWidget);
      expect(find.textContaining('躯干前倾'), findsOneWidget);
    });

    testWidgets('全不选时提示可点击选择', (tester) async {
      final sel = AngleSelection(store: MemStore());
      await sel.load();
      await sel.clear('side');

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: AngleSummaryBar(
            selection: sel,
            view: 'side',
            onTap: () {},
          ),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.textContaining('未标注角度'), findsOneWidget);
    });
  });
}
