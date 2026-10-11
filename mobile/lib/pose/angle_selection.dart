/// 角度标注的选择状态。
///
/// ## 为什么用户可以选
///
/// 一帧上标 9 个角度，画面上会挤成一团 —— 弧、刻度、数值互相遮挡，
/// 反而看不清任何一个。
///
/// 而不同的人关心的角度不同：
///   · 教练盯起跑 → 关心着地膝角、躯干前倾
///   · 康复师看膝内扣 → 关心额状面的几个
///   · 家长只想大概看看 → 一两个就够
///
/// 所以让用户选，而不是我们替他决定。
///
/// ## 为什么按视角分开存
///
/// 侧面和额状面的角度**不能混用**（几何量不同）。
/// 如果只存一个"选中的角度集合"，用户从侧面切到正面时，
/// 之前选的侧面角度在正面全都不适用 —— 画面会变成空的，
/// 而他不知道为什么。
///
/// 分成两个集合之后，切视角时各自保留各自的选择。
library;

import 'package:flutter/foundation.dart';

import 'angle_catalog.dart';

/// 角度选的持久化接口。
///
/// 抽成接口是为了让 [AngleSelection] 能在测试里不碰文件系统。
class AngleSelectionStore {
  const AngleSelectionStore();

  /// 读某组的已选 id。返回空表示用默认值。
  Future<List<String>?> read(String group) async => null;

  /// 写某组的已选 id。
  Future<void> write(String group, List<String> ids) async {}
}

/// 角度选择状态。
class AngleSelection extends ChangeNotifier {
  AngleSelection({AngleSelectionStore? store})
      : _store = store ?? const AngleSelectionStore();

  final AngleSelectionStore _store;

  /// 侧面选中的角度。
  final Set<String> _side = {};

  /// 额状面（正面/背面）选中的角度。
  final Set<String> _frontal = {};

  /// 是否已经读过持久化数据。
  bool _loaded = false;
  bool get loaded => _loaded;

  /// 默认选中的角度。
  ///
  /// ## 为什么默认不全选
  ///
  /// 全选的话第一次打开就是 9 个角度挤在一起，体验很差。
  /// 默认只选**最常看的两个**：
  ///   · 侧面：着地膝角 + 躯干前倾（起跑技术最关心的两个）
  ///   · 额状面：膝内扣（最常见的损伤风险因素）
  ///
  /// 用户可以随时加上别的。
  static const defaultSide = ['knee_angle_touchdown', 'trunk_lean'];
  static const defaultFrontal = ['knee_valgus_touchdown'];

  static const _sideGroup = 'angles_side';
  static const _frontalGroup = 'angles_frontal';

  /// 某一组当前选中的角度 id。
  Set<String> selectedFor(String group) =>
      group == 'frontal' ? _frontal : _side;

  /// 某个视角下当前选中的角度定义。
  ///
  /// 会自动过滤掉**不适用于该视角**的角度 ——
  /// 这是最后一道防线：即使数据里混进了别的视角的 id，
  /// 也不会画到画面上。
  List<AngleDefinition> activeForView(String view) {
    final group = groupForView(view);
    final ids = selectedFor(group);
    return anglesForView(view).where((a) => ids.contains(a.metricId)).toList();
  }

  /// 视角属于哪一组。
  static String groupForView(String view) =>
      view == 'front' || view == 'back' ? 'frontal' : 'side';

  /// 某个视角下**可以**选的角度。
  static List<AngleDefinition> availableForView(String view) =>
      anglesForView(view);

  bool isSelected(String view, String metricId) =>
      selectedFor(groupForView(view)).contains(metricId);

  /// 勾选 / 取消。
  Future<void> toggle(String view, String metricId) async {
    final group = groupForView(view);
    final set = group == 'frontal' ? _frontal : _side;

    if (set.contains(metricId)) {
      set.remove(metricId);
    } else {
      set.add(metricId);
    }
    notifyListeners();
    await _persist(group);
  }

  /// 全选某一组。
  Future<void> selectAll(String view) async {
    final group = groupForView(view);
    final set = group == 'frontal' ? _frontal : _side;
    set
      ..clear()
      ..addAll(availableForView(view).map((a) => a.metricId));
    notifyListeners();
    await _persist(group);
  }

  /// 清空某一组。
  ///
  /// 允许清空 —— 有时教练只想看骨架，不想让角度弧挡着。
  Future<void> clear(String view) async {
    final group = groupForView(view);
    final set = group == 'frontal' ? _frontal : _side;
    set.clear();
    notifyListeners();
    await _persist(group);
  }

  /// 从本地读回选择。App 启动或进入页面时调用一次。
  Future<void> load() async {
    final side = await _store.read(_sideGroup);
    final frontal = await _store.read(_frontalGroup);

    _side
      ..clear()
      ..addAll(side ?? defaultSide);
    _frontal
      ..clear()
      ..addAll(frontal ?? defaultFrontal);

    _loaded = true;
    notifyListeners();
  }

  Future<void> _persist(String group) async {
    final set = group == 'frontal' ? _frontal : _side;
    await _store.write(
      group == 'frontal' ? _frontalGroup : _sideGroup,
      set.toList(),
    );
  }

  /// 只保留**仍然存在**的角度 id。
  ///
  /// 用途：将来删掉某个角度定义后，用户本地存的 id 会指向不存在的角度。
  /// 不清掉的话，界面上"已选 3 个"但只显示 2 个，会让人困惑 ——
  /// 更糟的是用户无法取消那个看不见的选中项。
  ///
  /// 返回被清掉的 id。
  List<String> pruneUnknown() {
    final known = angleCatalog.map((a) => a.metricId).toSet();
    final removed = <String>[];
    for (final set in [_side, _frontal]) {
      final bad = set.where((id) => !known.contains(id)).toList();
      if (bad.isNotEmpty) {
        set.removeAll(bad);
        removed.addAll(bad);
      }
    }
    if (removed.isNotEmpty) notifyListeners();
    return removed;
  }
}
