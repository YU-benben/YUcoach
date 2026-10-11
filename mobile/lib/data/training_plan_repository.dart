import 'local_store.dart';
import '../domain/training_plan_entry.dart';

/// 训练计划的本地仓库。
///
/// ## 存储格式
///
/// ```json
/// { "plans": { "2026-03-15": { "date": "...", "content": "...", ... } } }
/// ```
///
/// 用**日期字符串作字典键**而不是数组：
///   · 查某一天是 O(1)，不用遍历
///   · 天然去重 —— 同一天不会出现两条（数组就得靠代码保证）
///   · 日历渲染一个月时要查 31 天，数组遍历 31 次 vs 字典查 31 次，
///     数据量大时差别明显
///
/// ## 为什么不按队伍分文件
///
/// 训练计划跟着用户走，一个用户一份。当前一个用户一个队伍，
/// 所以按 userId 分即可。将来支持多人共用一个队伍时，
/// 需要把 key 改成 `teamId/date` ——那时改这一处即可。
class TrainingPlanRepository {
  TrainingPlanRepository({required this.userId, LocalStore? store})
      : _store = store ?? LocalStore(fileName: 'training_plans.json');

  final String userId;
  final LocalStore _store;

  static const _plansKey = 'plans';

  // -- 读 -----------------------------------------------------------------

  /// 取某个日期区间的计划。用于日历渲染某个月。
  ///
  /// 返回的字典只含**有内容的**条目 —— 空条目不入库，
  /// 所以不用过滤。
  Future<Map<String, TrainingPlanEntry>> range(
    DateTime from,
    DateTime to,
  ) async {
    final all = await _loadAll();
    final out = <String, TrainingPlanEntry>{};
    final a = dateKey(from);
    final b = dateKey(to);
    for (final e in all.values) {
      // 字符串比较即可 —— YYYY-MM-DD 的字典序就是时间序
      if (e.date.compareTo(a) >= 0 && e.date.compareTo(b) <= 0) {
        out[e.date] = e;
      }
    }
    return out;
  }

  /// 取某一天的计划。没有则返回 null。
  Future<TrainingPlanEntry?> get(DateTime day) async {
    final all = await _loadAll();
    return all[dateKey(day)];
  }

  // -- 写 -----------------------------------------------------------------

  /// 保存某一天的计划。
  ///
  /// 内容为空时**删除该条目**，而不是存一条空记录。
  /// 这样"清空日程"和"从没记过"是同一个状态，
  /// 日历上不会因为存在空条目而显示出多余的东西。
  Future<void> save(DateTime day, String content) async {
    final key = dateKey(day);
    final doc = await _store.read();

    final raw = doc[_plansKey];
    final plans = <String, dynamic>{};
    if (raw is Map) {
      raw.forEach((k, v) {
        if (k is String && v is Map) {
          plans[k] = Map<String, dynamic>.from(v);
        }
      });
    }

    final trimmed = content.trim();
    if (trimmed.isEmpty) {
      plans.remove(key);
    } else {
      plans[key] = TrainingPlanEntry(
        date: key,
        content: trimmed,
        updatedAt: DateTime.now().toIso8601String(),
      ).toJson();
    }

    doc[_plansKey] = plans;
    await _store.write(doc);
  }

  /// 删除某一天的计划。与 `save(day, '')` 等价，
  /// 但调用处语义更清楚。
  Future<void> remove(DateTime day) async {
    final doc = await _store.read();
    final raw = doc[_plansKey];
    if (raw is Map) {
      raw.remove(dateKey(day));
      doc[_plansKey] = raw;
      await _store.write(doc);
    }
  }

  // -- 内部 ---------------------------------------------------------------

  Future<Map<String, TrainingPlanEntry>> _loadAll() async {
    final doc = await _store.read();
    final raw = doc[_plansKey];
    if (raw is! Map) return {};

    final out = <String, TrainingPlanEntry>{};
    raw.forEach((k, v) {
      if (k is! String || v is! Map) return;
      final e = TrainingPlanEntry.fromJson(Map<String, dynamic>.from(v));
      // 一条坏数据不该让整个日历打不开
      if (e != null) out[k] = e;
    });
    return out;
  }
}
