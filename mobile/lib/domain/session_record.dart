import '../../models/models.dart';

/// 采集场次记录 = 契约的 Session + 本地管理字段。
///
/// 为什么扁平复刻契约字段而不是嵌一个 Session 对象：
///   契约模型是「服务端返回什么」，本地记录是「这台设备存了什么」。
///   后者多了文件路径、分析任务 id、状态流转这些服务端不需要的字段。
///   扁平复刻让两边字段一一对应，序列化不用绕圈，也不容易漏字段。
///
/// 与契约的差异只有三类，都在这里有明确注释：
///   · 本地路径（视频文件、关键帧图）
///   · 分析任务（task_id、状态）
///   · 时间戳（创建、分析完成）
class SessionRecord {
  const SessionRecord({
    required this.sessionId,
    required this.teamId,
    required this.athleteId,
    required this.athleteName,
    required this.recordedAt,
    required this.testType,
    required this.view,
    // ---- 视频文件 ----
    this.videoPath,
    this.videoFileName,
    this.fileSizeBytes,
    // ---- 采集参数（契约 Session.capture）----
    this.durationMs,
    this.width,
    this.height,
    this.fpsDeclared,
    this.fpsVerified,
    this.frameCount,
    this.deviceModel,
    // ---- 采集信息（用户填写）----
    this.cameraDistanceM,
    this.cameraHeightM,
    this.axisTiltDeg,
    this.exposureLocked,
    this.hasLaneLine,
    this.cameraFollowed,
    // ---- 分析状态 ----
    required this.status,
    this.taskId,
    this.analysisId,
    this.qualityScore,
    this.perspectiveError,
    this.errorMessage,
    // ---- 本地时间戳 ----
    required this.createdAt,
    this.analyzedAt,
    this.deletedAt,
  });

  final String sessionId;
  final String teamId;
  final String athleteId;

  /// 冗余存一份姓名：列表展示时不必再查运动员表。
  /// 代价是改名后历史记录仍显示旧名字 —— 但报告里本来就该保留当时的姓名。
  final String athleteName;

  final String recordedAt;
  final SessionTestType testType;
  final SessionView view;

  final String? videoPath;
  final String? videoFileName;
  final int? fileSizeBytes;

  final int? durationMs;
  final int? width;
  final int? height;

  /// 容器声称的帧率。**仅供比对**，不用于计算。
  final double? fpsDeclared;

  /// 服务端校验后的真实帧率。所有时间换算以它为准。
  final double? fpsVerified;

  final int? frameCount;
  final String? deviceModel;

  final double? cameraDistanceM;
  final double? cameraHeightM;
  final double? axisTiltDeg;
  final bool? exposureLocked;

  /// 画面中是否有跑道分道线。决定位移类指标能否计算。
  final bool? hasLaneLine;

  /// 镜头是否跟随运动员移动。跟踪会引入透视误差。
  final bool? cameraFollowed;

  final SessionStatus status;
  final String? taskId;
  final String? analysisId;
  final double? qualityScore;
  final double? perspectiveError;

  /// 失败原因。失败时必填 —— 只说「失败」是没用的。
  final String? errorMessage;

  final String createdAt;
  final String? analyzedAt;
  final String? deletedAt;

  bool get isDeleted => deletedAt != null;
  bool get isAnalyzed => analysisId != null && status == SessionStatus.done;
  bool get isFailed => status == SessionStatus.failed;

  String get durationLabel {
    final s = durationMs;
    if (s == null) return '未知';
    return '${(s / 1000).toStringAsFixed(1)} 秒';
  }

  String get frameRateLabel => fpsVerified != null
      ? '${fpsVerified!.toStringAsFixed(0)} fps'
      : (fpsDeclared != null ? '${fpsDeclared!.toStringAsFixed(0)} fps（待校验）' : '未知');

  /// 采集信息是否填完整。缺项会影响分析有效性，界面上要能看出来。
  bool get captureInfoComplete =>
      cameraDistanceM != null && hasLaneLine != null && cameraFollowed != null;

  SessionRecord copyWith({
    SessionStatus? status,
    String? taskId,
    String? analysisId,
    double? qualityScore,
    double? perspectiveError,
    String? errorMessage,
    String? analyzedAt,
    String? deletedAt,
    double? fpsVerified,
  }) =>
      SessionRecord(
        sessionId: sessionId,
        teamId: teamId,
        athleteId: athleteId,
        athleteName: athleteName,
        recordedAt: recordedAt,
        testType: testType,
        view: view,
        videoPath: videoPath,
        videoFileName: videoFileName,
        fileSizeBytes: fileSizeBytes,
        durationMs: durationMs,
        width: width,
        height: height,
        fpsDeclared: fpsDeclared,
        fpsVerified: fpsVerified ?? this.fpsVerified,
        frameCount: frameCount,
        deviceModel: deviceModel,
        cameraDistanceM: cameraDistanceM,
        cameraHeightM: cameraHeightM,
        axisTiltDeg: axisTiltDeg,
        exposureLocked: exposureLocked,
        hasLaneLine: hasLaneLine,
        cameraFollowed: cameraFollowed,
        status: status ?? this.status,
        taskId: taskId ?? this.taskId,
        analysisId: analysisId ?? this.analysisId,
        qualityScore: qualityScore ?? this.qualityScore,
        perspectiveError: perspectiveError ?? this.perspectiveError,
        errorMessage: errorMessage ?? this.errorMessage,
        createdAt: createdAt,
        analyzedAt: analyzedAt ?? this.analyzedAt,
        deletedAt: deletedAt ?? this.deletedAt,
      );

  Map<String, dynamic> toJson() => {
        'session_id': sessionId,
        'team_id': teamId,
        'athlete_id': athleteId,
        'athlete_name': athleteName,
        'recorded_at': recordedAt,
        'test_type': testType.toJson(),
        'view': view.toJson(),
        'video_path': videoPath,
        'video_file_name': videoFileName,
        'file_size_bytes': fileSizeBytes,
        'duration_ms': durationMs,
        'width': width,
        'height': height,
        'fps_declared': fpsDeclared,
        'fps_verified': fpsVerified,
        'frame_count': frameCount,
        'device_model': deviceModel,
        'camera_distance_m': cameraDistanceM,
        'camera_height_m': cameraHeightM,
        'axis_tilt_deg': axisTiltDeg,
        'exposure_locked': exposureLocked,
        'has_lane_line': hasLaneLine,
        'camera_followed': cameraFollowed,
        'status': status.toJson(),
        'task_id': taskId,
        'analysis_id': analysisId,
        'quality_score': qualityScore,
        'perspective_error': perspectiveError,
        'error_message': errorMessage,
        'created_at': createdAt,
        'analyzed_at': analyzedAt,
        'deleted_at': deletedAt,
      };

  /// 解析。必需字段缺失或枚举值未知时返回 null，由仓库跳过该条 ——
  /// 一条坏记录不该让整个列表打不开。
  static SessionRecord? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;

    final id = json['session_id'] as String?;
    final athleteId = json['athlete_id'] as String?;
    if (id == null || id.isEmpty || athleteId == null || athleteId.isEmpty) {
      return null;
    }

    final testType = SessionTestType.fromJson(json['test_type']);
    final view = SessionView.fromJson(json['view']);
    final status = SessionStatus.fromJson(json['status']);
    if (testType == null || view == null || status == null) return null;

    double? d(Object? v) => v is num ? v.toDouble() : null;
    int? i(Object? v) => v is num ? v.toInt() : null;

    return SessionRecord(
      sessionId: id,
      teamId: json['team_id'] as String? ?? '',
      athleteId: athleteId,
      athleteName: json['athlete_name'] as String? ?? '',
      recordedAt: json['recorded_at'] as String? ?? '',
      testType: testType,
      view: view,
      videoPath: json['video_path'] as String?,
      videoFileName: json['video_file_name'] as String?,
      fileSizeBytes: i(json['file_size_bytes']),
      durationMs: i(json['duration_ms']),
      width: i(json['width']),
      height: i(json['height']),
      fpsDeclared: d(json['fps_declared']),
      fpsVerified: d(json['fps_verified']),
      frameCount: i(json['frame_count']),
      deviceModel: json['device_model'] as String?,
      cameraDistanceM: d(json['camera_distance_m']),
      cameraHeightM: d(json['camera_height_m']),
      axisTiltDeg: d(json['axis_tilt_deg']),
      exposureLocked: json['exposure_locked'] as bool?,
      hasLaneLine: json['has_lane_line'] as bool?,
      cameraFollowed: json['camera_followed'] as bool?,
      status: status,
      taskId: json['task_id'] as String?,
      analysisId: json['analysis_id'] as String?,
      qualityScore: d(json['quality_score']),
      perspectiveError: d(json['perspective_error']),
      errorMessage: json['error_message'] as String?,
      createdAt: json['created_at'] as String? ?? '',
      analyzedAt: json['analyzed_at'] as String?,
      deletedAt: json['deleted_at'] as String?,
    );
  }

  // 按 sessionId 判定相等性。理由同 AthleteRecord：
  // reload() 会产生全新实例，而 id 才是身份。
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is SessionRecord && other.sessionId == sessionId);

  @override
  int get hashCode => sessionId.hashCode;
}
