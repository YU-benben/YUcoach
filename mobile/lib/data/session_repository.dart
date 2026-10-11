import '../data/local_store.dart';
import '../domain/session_record.dart';
import '../models/models.dart';

/// 采集场次与分析结果的本地仓库。
///
/// 存储分两层，这是刻意的设计：
///
///   `sessions.json`      —— 索引：每条记录几百字节，全量加载很快
///   `analyses_store.json` —— 结果：含全部指标与结论，可能几十到几百 KB
///
/// 为什么分开：数据页要列出历史记录，如果每次都把所有分析结果读进内存，
/// 记录一多就会卡。索引与内容分离后，列表页只读索引，
/// 点进某条记录才加载对应的分析结果。
class SessionRepository {
  SessionRepository({
    required this.teamId,
    LocalStore? indexStore,
    LocalStore? analysisStore,
  })  : _index = indexStore ?? LocalStore(fileName: 'sessions.json'),
        _analysis =
            analysisStore ?? LocalStore(fileName: 'analyses_store.json');

  final String teamId;
  final LocalStore _index;
  final LocalStore _analysis;

  static const _sessionsKey = 'sessions';
  static const _analysesKey = 'analyses';

  // -- 查询 ---------------------------------------------------------------

  /// 当前队伍的全部记录，按拍摄时间倒序（最近的在前）。
  Future<List<SessionRecord>> list({
    String? athleteId,
    bool includeDeleted = false,
  }) async {
    final all = await _loadAll();
    var mine = all.where((s) => s.teamId == teamId);
    if (athleteId != null) {
      mine = mine.where((s) => s.athleteId == athleteId);
    }
    if (!includeDeleted) {
      mine = mine.where((s) => !s.isDeleted);
    }
    final list = mine.toList()
      ..sort((a, b) => b.recordedAt.compareTo(a.recordedAt));
    return list;
  }

  Future<SessionRecord?> findById(String sessionId) async {
    final all = await _loadAll();
    for (final s in all) {
      if (s.sessionId == sessionId && s.teamId == teamId) return s;
    }
    return null;
  }

  /// 某运动员的记录数。列表页用它显示「N 次分析」。
  Future<int> countForAthlete(String athleteId) async =>
      (await list(athleteId: athleteId)).length;

  Future<Map<String, int>> countByAthlete() async {
    final out = <String, int>{};
    for (final s in await list()) {
      out[s.athleteId] = (out[s.athleteId] ?? 0) + 1;
    }
    return out;
  }

  // -- 写入 ---------------------------------------------------------------

  /// 新建一条采集记录。此时视频已选好、采集信息已填，但还没分析。
  Future<SessionRecord> create({
    required String athleteId,
    required String athleteName,
    required SessionTestType testType,
    required SessionView view,
    String? videoPath,
    String? videoFileName,
    int? fileSizeBytes,
    int? durationMs,
    int? width,
    int? height,
    double? fpsDeclared,
    int? frameCount,
    double? cameraDistanceM,
    double? cameraHeightM,
    double? axisTiltDeg,
    bool? exposureLocked,
    bool? hasLaneLine,
    bool? cameraFollowed,
  }) async {
    final now = DateTime.now();
    final record = SessionRecord(
      sessionId: 's_${now.millisecondsSinceEpoch}',
      teamId: teamId,
      athleteId: athleteId,
      athleteName: athleteName,
      recordedAt: now.toIso8601String(),
      testType: testType,
      view: view,
      videoPath: videoPath,
      videoFileName: videoFileName,
      fileSizeBytes: fileSizeBytes,
      durationMs: durationMs,
      width: width,
      height: height,
      fpsDeclared: fpsDeclared,
      frameCount: frameCount,
      cameraDistanceM: cameraDistanceM,
      cameraHeightM: cameraHeightM,
      axisTiltDeg: axisTiltDeg,
      exposureLocked: exposureLocked,
      hasLaneLine: hasLaneLine,
      cameraFollowed: cameraFollowed,
      status: SessionStatus.uploaded,
      createdAt: now.toIso8601String(),
    );
    await _upsert(record);
    return record;
  }

  Future<void> update(SessionRecord record) async => _upsert(record);

  /// 标记为已提交分析，记录服务端返回的任务 id。
  Future<void> markQueued(String sessionId, String taskId) async {
    final s = await findById(sessionId);
    if (s == null) return;
    await _upsert(s.copyWith(status: SessionStatus.queued, taskId: taskId));
  }

  /// 分析完成：写入结果并把记录标记为完成。
  ///
  /// 结果与分析 id 一起存 —— 界面点进记录时按 id 取结果。
  Future<void> markAnalyzed(
    String sessionId,
    String analysisId,
    AnalysisResult result,
  ) async {
    await _saveAnalysis(analysisId, result);

    final s = await findById(sessionId);
    if (s == null) return;
    await _upsert(s.copyWith(
      status: SessionStatus.done,
      analysisId: analysisId,
      qualityScore: result.qualityScore,
      perspectiveError: result.perspectiveErrorEstimate,
      fpsVerified: result.session.capture.fpsVerified,
      analyzedAt: DateTime.now().toIso8601String(),
    ));
  }

  /// 分析失败。**必须记录原因** —— 只说「失败」是没用的，
  /// 教练需要知道下一步做什么。
  Future<void> markFailed(String sessionId, String message) async {
    final s = await findById(sessionId);
    if (s == null) return;
    await _upsert(s.copyWith(
      status: SessionStatus.failed,
      errorMessage: message,
      analyzedAt: DateTime.now().toIso8601String(),
    ));
  }

  Future<void> softDelete(String sessionId) async {
    final s = await findById(sessionId);
    if (s == null) return;
    await _upsert(s.copyWith(deletedAt: DateTime.now().toIso8601String()));
  }

  // -- 分析结果 -----------------------------------------------------------

  Future<AnalysisResult?> loadAnalysis(String analysisId) async {
    final doc = await _analysis.read();
    final map = doc[_analysesKey];
    if (map is! Map) return null;
    final raw = map[analysisId];
    if (raw is! Map<String, dynamic>) return null;
    try {
      return AnalysisResult.fromJson(raw);
    } catch (_) {
      // 结果数据坏了不该让整个记录打不开，返回 null 由界面提示
      return null;
    }
  }

  Future<void> _saveAnalysis(String analysisId, AnalysisResult result) async {
    final doc = await _analysis.read();
    final map = (doc[_analysesKey] as Map?)?.cast<String, dynamic>() ??
        <String, dynamic>{};
    map[analysisId] = result.toJson();
    doc[_analysesKey] = map;
    await _analysis.write(doc);
  }

  // -- 内部 ---------------------------------------------------------------

  Future<List<SessionRecord>> _loadAll() async {
    final doc = await _index.read();
    final raw = doc[_sessionsKey];
    if (raw is! List) return [];

    final out = <SessionRecord>[];
    for (final item in raw) {
      if (item is! Map<String, dynamic>) continue;
      final r = SessionRecord.fromJson(item);
      if (r != null) out.add(r);
    }
    return out;
  }

  Future<void> _saveAll(List<SessionRecord> list) async {
    final doc = await _index.read();
    doc[_sessionsKey] = list.map((s) => s.toJson()).toList();
    await _index.write(doc);
  }

  Future<void> _upsert(SessionRecord record) async {
    final all = await _loadAll();
    final idx = all.indexWhere((s) => s.sessionId == record.sessionId);
    if (idx >= 0) {
      all[idx] = record;
    } else {
      all.add(record);
    }
    await _saveAll(all);
  }
}
