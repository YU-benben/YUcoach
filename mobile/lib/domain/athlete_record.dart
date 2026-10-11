import '../../models/models.dart';

/// 本地运动员档案 = 契约的 Athlete + 本地管理字段。
///
/// 为什么不直接把契约的 Athlete 落盘：
///   契约描述的是「服务端返回的运动员信息」，落盘还需要创建时间、
///   更新时间、软删除标记这些纯本地字段。把它们塞进契约模型会污染
///   「契约与实现解耦」这条原则（见 docs/00-文档地图.md P4）。
///
/// 转换方向明确：toContract() 产出给报告用的契约对象，
/// fromContract() 把服务端/假数据里的运动员信息纳入本地档案。
class AthleteRecord {
  const AthleteRecord({
    required this.athleteId,
    required this.teamId,
    required this.name,
    required this.gender,
    required this.event,
    required this.level,
    this.heightCm,
    this.weightKg,
    this.note,
    required this.createdAt,
    required this.updatedAt,
    this.deletedAt,
  });

  final String athleteId;
  final String teamId;
  final String name;
  final AthleteGender gender;
  final String event;
  final AthleteLevel level;

  /// 身高用于体型归一化与逐帧参考尺度。缺失时位移类指标不可用 ——
  /// 所以界面上要提示教练尽量填。
  final double? heightCm;
  final double? weightKg;

  /// 备注：伤病、技术特点等。处方推荐需要参考（避开禁忌动作）。
  final String? note;

  final String createdAt;
  final String updatedAt;

  /// 软删除。运动员档案关联着历史记录，直接删除会让记录变成孤儿；
  /// 标记删除既能让列表清爽，又保留数据可恢复。
  final String? deletedAt;

  bool get isDeleted => deletedAt != null;

  /// 身高是否已填 —— 决定位移类指标是否可用，界面上要据此提示
  bool get hasHeight => heightCm != null && heightCm! > 0;

  AthleteRecord copyWith({
    String? name,
    AthleteGender? gender,
    String? event,
    AthleteLevel? level,
    double? heightCm,
    double? weightKg,
    String? note,
    String? updatedAt,
    String? deletedAt,
    bool clearHeight = false,
    bool clearWeight = false,
    bool clearNote = false,
  }) =>
      AthleteRecord(
        athleteId: athleteId,
        teamId: teamId,
        name: name ?? this.name,
        gender: gender ?? this.gender,
        event: event ?? this.event,
        level: level ?? this.level,
        heightCm: clearHeight ? null : (heightCm ?? this.heightCm),
        weightKg: clearWeight ? null : (weightKg ?? this.weightKg),
        note: clearNote ? null : (note ?? this.note),
        createdAt: createdAt,
        updatedAt: updatedAt ?? this.updatedAt,
        deletedAt: deletedAt ?? this.deletedAt,
      );

  /// 转成契约对象，供报告页与后续接口复用。
  Athlete toContract() => Athlete(
        athleteId: athleteId,
        name: name,
        gender: gender,
        heightCm: heightCm,
        weightKg: weightKg,
        event: event,
        level: level,
      );

  /// 从契约对象建立本地档案（服务端返回运动员信息时用）。
  static AthleteRecord fromContract(
    Athlete a, {
    required String teamId,
    String? note,
  }) {
    final now = DateTime.now().toIso8601String();
    return AthleteRecord(
      athleteId: a.athleteId,
      teamId: teamId,
      name: a.name,
      gender: a.gender,
      event: a.event,
      level: a.level,
      heightCm: a.heightCm,
      weightKg: a.weightKg,
      note: note,
      createdAt: now,
      updatedAt: now,
    );
  }

  Map<String, dynamic> toJson() => {
        'athlete_id': athleteId,
        'team_id': teamId,
        'name': name,
        'gender': gender.toJson(),
        'event': event,
        'level': level.toJson(),
        'height_cm': heightCm,
        'weight_kg': weightKg,
        'note': note,
        'created_at': createdAt,
        'updated_at': updatedAt,
        'deleted_at': deletedAt,
      };

  /// 解析。字段缺失或枚举值未知时返回 null，由仓库跳过该条 ——
  /// 一条坏记录不该让整个运动员列表打不开。
  static AthleteRecord? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    final id = json['athlete_id'] as String?;
    final name = json['name'] as String?;
    if (id == null || id.isEmpty || name == null || name.isEmpty) return null;

    final gender = AthleteGender.fromJson(json['gender']);
    final level = AthleteLevel.fromJson(json['level']);
    if (gender == null || level == null) return null;

    double? num_(Object? v) => v is num ? v.toDouble() : null;

    return AthleteRecord(
      athleteId: id,
      teamId: json['team_id'] as String? ?? '',
      name: name,
      gender: gender,
      event: json['event'] as String? ?? '100m',
      level: level,
      heightCm: num_(json['height_cm']),
      weightKg: num_(json['weight_kg']),
      note: json['note'] as String?,
      createdAt: json['created_at'] as String? ?? '',
      updatedAt: json['updated_at'] as String? ?? '',
      deletedAt: json['deleted_at'] as String?,
    );
  }

  // ---------------------------------------------------------------------------
  // 相等性
  //
  // 按 athleteId 判定，而不是默认的引用比较。
  //
  // 为什么必须这样：每次 reload() 都会从文件反序列化出**全新实例**，
  // 内容相同但引用不同。默认的 == 会把它们判为不等，
  // 进而引发一类很难查的问题 —— 最典型的是 DropdownButtonFormField
  // 的断言崩溃（"There should be exactly one item with ... value"）。
  //
  // 只比较 id 而不是全部字段是刻意的：id 是身份，其余是属性。
  // 若按全部字段比较，改个名字就会让"同一个运动员"变成两个。
  // ---------------------------------------------------------------------------

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is AthleteRecord && other.athleteId == athleteId);

  @override
  int get hashCode => athleteId.hashCode;
}
