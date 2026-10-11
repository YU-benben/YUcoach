// GENERATED FILE - DO NOT EDIT BY HAND
//
// 生成命令： python scripts/gen_models.py
// 仅含枚举定义，便于只想引用枚举的场合。

enum AthleteGender {
  male,
  female;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<AthleteGender, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static AthleteGender? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <AthleteGender, String>{
    AthleteGender.male: 'male',
    AthleteGender.female: 'female',
  };
}

enum AthleteLevel {
  elite,
  subElite,
  college,
  highSchool,
  amateur;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<AthleteLevel, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static AthleteLevel? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <AthleteLevel, String>{
    AthleteLevel.elite: 'elite',
    AthleteLevel.subElite: 'sub_elite',
    AthleteLevel.college: 'college',
    AthleteLevel.highSchool: 'high_school',
    AthleteLevel.amateur: 'amateur',
  };
}

enum SessionTestType {
  blockStart,
  acceleration,
  maxVelocity,
  speedEndurance;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<SessionTestType, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static SessionTestType? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <SessionTestType, String>{
    SessionTestType.blockStart: 'block_start',
    SessionTestType.acceleration: 'acceleration',
    SessionTestType.maxVelocity: 'max_velocity',
    SessionTestType.speedEndurance: 'speed_endurance',
  };
}

enum SessionView {
  side,
  front,
  back;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<SessionView, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static SessionView? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <SessionView, String>{
    SessionView.side: 'side',
    SessionView.front: 'front',
    SessionView.back: 'back',
  };
}

enum FpsVerifyMethod {
  durationCheck,
  cadenceBackcalc,
  scaleDisplacement;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<FpsVerifyMethod, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static FpsVerifyMethod? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <FpsVerifyMethod, String>{
    FpsVerifyMethod.durationCheck: 'duration_check',
    FpsVerifyMethod.cadenceBackcalc: 'cadence_backcalc',
    FpsVerifyMethod.scaleDisplacement: 'scale_displacement',
  };
}

enum FpsVerifyStatus {
  verified,
  warning,
  rejected;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<FpsVerifyStatus, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static FpsVerifyStatus? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <FpsVerifyStatus, String>{
    FpsVerifyStatus.verified: 'verified',
    FpsVerifyStatus.warning: 'warning',
    FpsVerifyStatus.rejected: 'rejected',
  };
}

enum CameraMotionLevel {
  fixed,
  slightPan,
  strongPan;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<CameraMotionLevel, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static CameraMotionLevel? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <CameraMotionLevel, String>{
    CameraMotionLevel.fixed: 'fixed',
    CameraMotionLevel.slightPan: 'slight_pan',
    CameraMotionLevel.strongPan: 'strong_pan',
  };
}

enum CameraMotionDetectedBy {
  opticalFlow,
  featureMatch,
  manual;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<CameraMotionDetectedBy, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static CameraMotionDetectedBy? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <CameraMotionDetectedBy, String>{
    CameraMotionDetectedBy.opticalFlow: 'optical_flow',
    CameraMotionDetectedBy.featureMatch: 'feature_match',
    CameraMotionDetectedBy.manual: 'manual',
  };
}

enum ReferenceScaleMethod {
  laneLine,
  heightDerived,
  calibrationRod,
  none;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<ReferenceScaleMethod, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static ReferenceScaleMethod? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <ReferenceScaleMethod, String>{
    ReferenceScaleMethod.laneLine: 'lane_line',
    ReferenceScaleMethod.heightDerived: 'height_derived',
    ReferenceScaleMethod.calibrationRod: 'calibration_rod',
    ReferenceScaleMethod.none: 'none',
  };
}

enum SessionStatus {
  uploaded,
  queued,
  processing,
  done,
  failed;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<SessionStatus, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static SessionStatus? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <SessionStatus, String>{
    SessionStatus.uploaded: 'uploaded',
    SessionStatus.queued: 'queued',
    SessionStatus.processing: 'processing',
    SessionStatus.done: 'done',
    SessionStatus.failed: 'failed',
  };
}

enum TimeBaseEvent {
  setPosition,
  gunFire,
  blockClearance,
  touchdown,
  midstance,
  toeOff,
  swingPeak,
  finish;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<TimeBaseEvent, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static TimeBaseEvent? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <TimeBaseEvent, String>{
    TimeBaseEvent.setPosition: 'set_position',
    TimeBaseEvent.gunFire: 'gun_fire',
    TimeBaseEvent.blockClearance: 'block_clearance',
    TimeBaseEvent.touchdown: 'touchdown',
    TimeBaseEvent.midstance: 'midstance',
    TimeBaseEvent.toeOff: 'toe_off',
    TimeBaseEvent.swingPeak: 'swing_peak',
    TimeBaseEvent.finish: 'finish',
  };
}

enum TimeBaseUnit {
  ms;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<TimeBaseUnit, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static TimeBaseUnit? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <TimeBaseUnit, String>{
    TimeBaseUnit.ms: 'ms',
  };
}

enum ViewDirection {
  leftToRight,
  rightToLeft;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<ViewDirection, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static ViewDirection? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <ViewDirection, String>{
    ViewDirection.leftToRight: 'left_to_right',
    ViewDirection.rightToLeft: 'right_to_left',
  };
}

enum ViewCoordSystem {
  normalizedTopLeft;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<ViewCoordSystem, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static ViewCoordSystem? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <ViewCoordSystem, String>{
    ViewCoordSystem.normalizedTopLeft: 'normalized_top_left',
  };
}

enum KeypointQualityCode {
  n0,
  n1,
  n2;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<KeypointQualityCode, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static KeypointQualityCode? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <KeypointQualityCode, String>{
    KeypointQualityCode.n0: '0',
    KeypointQualityCode.n1: '1',
    KeypointQualityCode.n2: '2',
  };
}

enum PoseFrameMeasurementWindow {
  valid,
  degraded,
  excluded;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<PoseFrameMeasurementWindow, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static PoseFrameMeasurementWindow? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <PoseFrameMeasurementWindow, String>{
    PoseFrameMeasurementWindow.valid: 'valid',
    PoseFrameMeasurementWindow.degraded: 'degraded',
    PoseFrameMeasurementWindow.excluded: 'excluded',
  };
}

enum MetricUnit {
  deg,
  ms,
  m,
  mPerS,
  stepsPerMin,
  ratio,
  enumValue;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<MetricUnit, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static MetricUnit? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <MetricUnit, String>{
    MetricUnit.deg: 'deg',
    MetricUnit.ms: 'ms',
    MetricUnit.m: 'm',
    MetricUnit.mPerS: 'm/s',
    MetricUnit.stepsPerMin: 'steps/min',
    MetricUnit.ratio: 'ratio',
    MetricUnit.enumValue: 'enum',
  };
}

enum MetricPhase {
  setValue,
  start,
  acceleration,
  transition,
  maxVelocity,
  deceleration;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<MetricPhase, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static MetricPhase? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <MetricPhase, String>{
    MetricPhase.setValue: 'set',
    MetricPhase.start: 'start',
    MetricPhase.acceleration: 'acceleration',
    MetricPhase.transition: 'transition',
    MetricPhase.maxVelocity: 'max_velocity',
    MetricPhase.deceleration: 'deceleration',
  };
}

enum MetricSide {
  l,
  r,
  both;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<MetricSide, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static MetricSide? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <MetricSide, String>{
    MetricSide.l: 'L',
    MetricSide.r: 'R',
    MetricSide.both: 'both',
  };
}

enum ReferenceRangeRefSource {
  literature,
  team,
  global;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<ReferenceRangeRefSource, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static ReferenceRangeRefSource? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <ReferenceRangeRefSource, String>{
    ReferenceRangeRefSource.literature: 'literature',
    ReferenceRangeRefSource.team: 'team',
    ReferenceRangeRefSource.global: 'global',
  };
}

enum MetricReliability {
  a,
  b,
  c;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<MetricReliability, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static MetricReliability? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <MetricReliability, String>{
    MetricReliability.a: 'A',
    MetricReliability.b: 'B',
    MetricReliability.c: 'C',
  };
}

enum InsufficientReason {
  lowFrameRate,
  viewMismatch,
  noReferenceScale,
  cameraMotion,
  occlusion,
  missingEvent,
  perspectiveError,
  frameRateUnverified,
  insufficientSamples,
  insufficientCycles,
  noAthleteHeight,
  implausibleValue,
  contactTimingUnreliable,
  notImplemented;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<InsufficientReason, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static InsufficientReason? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <InsufficientReason, String>{
    InsufficientReason.lowFrameRate: 'low_frame_rate',
    InsufficientReason.viewMismatch: 'view_mismatch',
    InsufficientReason.noReferenceScale: 'no_reference_scale',
    InsufficientReason.cameraMotion: 'camera_motion',
    InsufficientReason.occlusion: 'occlusion',
    InsufficientReason.missingEvent: 'missing_event',
    InsufficientReason.perspectiveError: 'perspective_error',
    InsufficientReason.frameRateUnverified: 'frame_rate_unverified',
    InsufficientReason.insufficientSamples: 'insufficient_samples',
    InsufficientReason.insufficientCycles: 'insufficient_cycles',
    InsufficientReason.noAthleteHeight: 'no_athlete_height',
    InsufficientReason.implausibleValue: 'implausible_value',
    InsufficientReason.contactTimingUnreliable: 'contact_timing_unreliable',
    InsufficientReason.notImplemented: 'not_implemented',
  };
}

enum FindingSeverity {
  major,
  minor,
  info,
  insufficientData;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<FindingSeverity, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static FindingSeverity? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <FindingSeverity, String>{
    FindingSeverity.major: 'major',
    FindingSeverity.minor: 'minor',
    FindingSeverity.info: 'info',
    FindingSeverity.insufficientData: 'insufficient_data',
  };
}

enum FindingBasis {
  normal,
  lowReliability,
  singleSample,
  extrapolated;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<FindingBasis, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static FindingBasis? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <FindingBasis, String>{
    FindingBasis.normal: 'normal',
    FindingBasis.lowReliability: 'low_reliability',
    FindingBasis.singleSample: 'single_sample',
    FindingBasis.extrapolated: 'extrapolated',
  };
}

enum AnalysisTaskTaskStatus {
  queued,
  running,
  done,
  failed;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<AnalysisTaskTaskStatus, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static AnalysisTaskTaskStatus? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <AnalysisTaskTaskStatus, String>{
    AnalysisTaskTaskStatus.queued: 'queued',
    AnalysisTaskTaskStatus.running: 'running',
    AnalysisTaskTaskStatus.done: 'done',
    AnalysisTaskTaskStatus.failed: 'failed',
  };
}

enum StageName {
  decode,
  fpsVerify,
  cameraMotion,
  viewCheck,
  undistort,
  referenceScale,
  poseEstimation,
  smoothing,
  validWindow,
  events,
  phases,
  metrics,
  rules,
  report;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<StageName, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static StageName? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <StageName, String>{
    StageName.decode: 'decode',
    StageName.fpsVerify: 'fps_verify',
    StageName.cameraMotion: 'camera_motion',
    StageName.viewCheck: 'view_check',
    StageName.undistort: 'undistort',
    StageName.referenceScale: 'reference_scale',
    StageName.poseEstimation: 'pose_estimation',
    StageName.smoothing: 'smoothing',
    StageName.validWindow: 'valid_window',
    StageName.events: 'events',
    StageName.phases: 'phases',
    StageName.metrics: 'metrics',
    StageName.rules: 'rules',
    StageName.report: 'report',
  };
}

enum StageStatus {
  pending,
  running,
  done,
  failed,
  skipped;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<StageStatus, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static StageStatus? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <StageStatus, String>{
    StageStatus.pending: 'pending',
    StageStatus.running: 'running',
    StageStatus.done: 'done',
    StageStatus.failed: 'failed',
    StageStatus.skipped: 'skipped',
  };
}

enum ApiErrorActionRequired {
  confirmView,
  confirmScale,
  selectShorterClip,
  reupload,
  retryLater;

  String toJson() => _values[this]!;

  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。
  static Map<ApiErrorActionRequired, String> get valuesJson => _values;

  /// 未知取值返回 null，而不是抛异常。
  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。
  static ApiErrorActionRequired? fromJson(Object? v) {
    if (v == null) return null;
    final key = v.toString();
    for (final entry in _values.entries) {
      if (entry.value == key) return entry.key;
    }
    return null;
  }

  static const _values = <ApiErrorActionRequired, String>{
    ApiErrorActionRequired.confirmView: 'confirm_view',
    ApiErrorActionRequired.confirmScale: 'confirm_scale',
    ApiErrorActionRequired.selectShorterClip: 'select_shorter_clip',
    ApiErrorActionRequired.reupload: 'reupload',
    ApiErrorActionRequired.retryLater: 'retry_later',
  };
}
