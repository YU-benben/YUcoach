import '../data/local_store.dart';
import '../domain/athlete_record.dart';
import '../models/models.dart';

/// 运动员档案仓库。
///
/// 界面只依赖这个类，不关心数据存在文件、SQLite 还是服务端。
/// 后端就绪后换实现，界面不动 —— 与报告页的数据源同一套思路。
class AthleteRepository {
  AthleteRepository({LocalStore? store, required this.teamId})
      : _store = store ?? LocalStore(fileName: 'athletes.json');

  final LocalStore _store;

  /// 队伍隔离。所有查询都必须带上它 —— 多租户最容易漏的一环，
  /// 在这里统一收口，而不是让每个调用方自己记得过滤。
  final String teamId;

  static const _key = 'athletes';

  // -- 查询 ---------------------------------------------------------------

  /// 当前队伍的运动员，按创建时间倒序（最近添加的在最上面）。
  Future<List<AthleteRecord>> list({bool includeDeleted = false}) async {
    final all = await _loadAll();
    final mine = all.where((a) => a.teamId == teamId);
    final visible =
        includeDeleted ? mine : mine.where((a) => !a.isDeleted);
    final list = visible.toList()
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return list;
  }

  Future<AthleteRecord?> findById(String athleteId) async {
    final all = await _loadAll();
    for (final a in all) {
      if (a.athleteId == athleteId && a.teamId == teamId) return a;
    }
    return null;
  }

  Future<int> count() async => (await list()).length;

  // -- 写入 ---------------------------------------------------------------

  Future<AthleteRecord> create({
    required String name,
    required AthleteGender gender,
    required String event,
    required AthleteLevel level,
    double? heightCm,
    double? weightKg,
    String? note,
  }) async {
    final now = DateTime.now().toIso8601String();
    final record = AthleteRecord(
      athleteId: 'at_${DateTime.now().microsecondsSinceEpoch}',
      teamId: teamId,
      name: name.trim(),
      gender: gender,
      event: event,
      level: level,
      heightCm: heightCm,
      weightKg: weightKg,
      note: note?.trim().isEmpty ?? true ? null : note!.trim(),
      createdAt: now,
      updatedAt: now,
    );
    await _upsert(record);
    return record;
  }

  Future<void> update(AthleteRecord record) async {
    await _upsert(record.copyWith(
      updatedAt: DateTime.now().toIso8601String(),
    ));
  }

  /// 软删除。档案关联着历史记录，硬删除会让记录变孤儿。
  Future<void> softDelete(String athleteId) async {
    final a = await findById(athleteId);
    if (a == null) return;
    await _upsert(a.copyWith(
      deletedAt: DateTime.now().toIso8601String(),
      updatedAt: DateTime.now().toIso8601String(),
    ));
  }

  Future<void> restore(String athleteId) async {
    final all = await _loadAll();
    final idx = all.indexWhere(
        (a) => a.athleteId == athleteId && a.teamId == teamId);
    if (idx < 0) return;

    final a = all[idx];
    all[idx] = AthleteRecord(
      athleteId: a.athleteId,
      teamId: a.teamId,
      name: a.name,
      gender: a.gender,
      event: a.event,
      level: a.level,
      heightCm: a.heightCm,
      weightKg: a.weightKg,
      note: a.note,
      createdAt: a.createdAt,
      updatedAt: DateTime.now().toIso8601String(),
    );
    await _saveAll(all);
  }

  // -- 内部 ---------------------------------------------------------------

  Future<List<AthleteRecord>> _loadAll() async {
    final doc = await _store.read();
    final raw = doc[_key];
    if (raw is! List) return [];

    final out = <AthleteRecord>[];
    for (final item in raw) {
      if (item is! Map<String, dynamic>) continue;
      final r = AthleteRecord.fromJson(item);
      if (r != null) out.add(r);
    }
    return out;
  }

  Future<void> _saveAll(List<AthleteRecord> list) async {
    final doc = await _store.read();
    doc[_key] = list.map((a) => a.toJson()).toList();
    await _store.write(doc);
  }

  Future<void> _upsert(AthleteRecord record) async {
    final all = await _loadAll();
    final idx = all.indexWhere((a) => a.athleteId == record.athleteId);
    if (idx >= 0) {
      all[idx] = record;
    } else {
      all.add(record);
    }
    await _saveAll(all);
  }
}
