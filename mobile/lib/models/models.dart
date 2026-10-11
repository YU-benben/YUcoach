// GENERATED FILE - DO NOT EDIT BY HAND
//
// 生成命令： python scripts/gen_models.py
// 来源契约： backend/contracts/*.schema.json
//
// 契约版本变更后必须重新生成。手写修改会在下次生成时被覆盖。
//
// 本文件零依赖，只需：
//   import 'package:yu_coach/models/models.dart';

/// 把任意 Map 安全地转成 `Map<String, dynamic>`。
///
/// 不能用 `as Map<String, dynamic>` —— 字面量与部分 JSON 解码结果的实际类型
/// 是 `Map<String, Object>`，强转会失败，得到 null 而不是抛错，
/// 随后在模型内部炸出与真正原因无关的空指针异常。
Map<String, dynamic> _asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return Map<String, dynamic>.from(value);
  throw FormatException('期望 JSON 对象，实际是 ${value.runtimeType}');
}

/// 同 [_asMap]，但允许 null —— 供契约声明为可空的字段使用。
Map<String, dynamic>? _asMapOrNull(Object? value) {
  if (value == null) return null;
  return _asMap(value);
}

/// 解析枚举，失败时给出**能直接定位问题**的错误信息。
///
/// 为什么需要它：枚举解析失败原本只会让 fromJson 得到 null，
/// 随后在 `!` 处抛出 "Null check operator used on a null value" ——
/// 报错位置在模型内部的某一行，既没说哪个字段，也没说收到了什么值，
/// 排查成本极高（本项目在此处浪费过大量时间）。
///
/// 现在会直接指明：字段名、收到的值、期望的取值集合。
T _enumFromJson<T>(
  Object? value,
  T? Function(Object?) parse,
  String fieldName,
  Map<T, String> allowed,
) {
  final parsed = parse(value);
  if (parsed != null) return parsed;
  if (value == null) {
    throw FormatException('字段 "$fieldName" 缺失或为 null，期望取值为 ${allowed.values.toList()}');
  }
  throw FormatException(
    '字段 "$fieldName" 收到未知取值 "$value"，期望取值为 ${allowed.values.toList()}',
  );
}

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

class Athlete {
  final String athleteId;
  final String name;
  final AthleteGender gender;
  /// 用于归一化与逐帧参考尺度。缺失时相关指标不可用
  final double? heightCm;
  final double? weightKg;
  final String event;
  final AthleteLevel level;

  const Athlete({
    required this.athleteId,
    required this.name,
    required this.gender,
    this.heightCm,
    this.weightKg,
    required this.event,
    required this.level
  });

  static Athlete fromJson(Map<String, dynamic> json) {
    return Athlete(
      level: _enumFromJson<AthleteLevel>(json['level']!, AthleteLevel.fromJson, 'level', AthleteLevel.valuesJson),
      event: json['event']! as String,
      weightKg: (json['weight_kg'] as num?)?.toDouble(),
      heightCm: (json['height_cm'] as num?)?.toDouble(),
      gender: _enumFromJson<AthleteGender>(json['gender']!, AthleteGender.fromJson, 'gender', AthleteGender.valuesJson),
      name: json['name']! as String,
      athleteId: json['athlete_id']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'athlete_id': athleteId,
      'event': event,
      'gender': gender.toJson(),
      'height_cm': heightCm,
      'level': level.toJson(),
      'name': name,
      'weight_kg': weightKg,
    };
  }
}

class Resolution {
  final int width;
  final int height;

  const Resolution({
    required this.width,
    required this.height
  });

  static Resolution fromJson(Map<String, dynamic> json) {
    return Resolution(
      height: (json['height']! as num).toInt(),
      width: (json['width']! as num).toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'height': height,
      'width': width,
    };
  }
}

/// 帧率校验结果。三项方法交叉验证，至少两项一致方可继续
class FpsVerify {
  final List<FpsVerifyMethod> methods;
  /// 每种方法的独立结果，键为方法名。值为 null 表示该方法本次无法得出结论（数据不足），这是正常情况而非错误：判定采信哪一项时需要知道哪些方法失效了
  final Map<String, dynamic> methodResults;
  /// 各方法结果的最大偏差百分比
  final double agreementPct;
  final FpsVerifyStatus status;
  final String? note;

  const FpsVerify({
    required this.methods,
    required this.methodResults,
    required this.agreementPct,
    required this.status,
    this.note
  });

  static FpsVerify fromJson(Map<String, dynamic> json) {
    return FpsVerify(
      note: json['note'] as String?,
      status: _enumFromJson<FpsVerifyStatus>(json['status']!, FpsVerifyStatus.fromJson, 'status', FpsVerifyStatus.valuesJson),
      agreementPct: (json['agreement_pct']! as num).toDouble(),
      methodResults: _asMap(json['method_results']!),
      methods: (json['methods']! as List<dynamic>).map((e) => FpsVerifyMethod.fromJson(e)).whereType<FpsVerifyMethod>().toList(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'agreement_pct': agreementPct,
      'method_results': methodResults,
      'methods': methods.map((e) => e.toJson()).toList(),
      'note': note,
      'status': status.toJson(),
    };
  }
}

class Camera {
  final double? distanceM;
  final double? heightM;
  final double? axisTiltDeg;
  final bool? exposureLocked;
  final bool? digitalZoom;

  const Camera({
    this.distanceM,
    this.heightM,
    this.axisTiltDeg,
    this.exposureLocked,
    this.digitalZoom
  });

  static Camera fromJson(Map<String, dynamic> json) {
    return Camera(
      digitalZoom: json['digital_zoom'] as bool?,
      exposureLocked: json['exposure_locked'] as bool?,
      axisTiltDeg: (json['axis_tilt_deg'] as num?)?.toDouble(),
      heightM: (json['height_m'] as num?)?.toDouble(),
      distanceM: (json['distance_m'] as num?)?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'axis_tilt_deg': axisTiltDeg,
      'digital_zoom': digitalZoom,
      'distance_m': distanceM,
      'exposure_locked': exposureLocked,
      'height_m': heightM,
    };
  }
}

class Capture {
  final String? deviceModel;
  final Resolution resolution;
  final int frameCount;
  final double? durationMs;
  /// 容器声明值。仅用于比对，不得用于计算
  final double? fpsDeclared;
  /// 校验认定值。所有时间换算必须使用它
  final double? fpsVerified;
  final FpsVerify fpsVerify;
  /// 是否执行了镜头畸变校正
  final bool? distortionCorrected;
  final Camera? camera;

  const Capture({
    this.deviceModel,
    required this.resolution,
    required this.frameCount,
    this.durationMs,
    this.fpsDeclared,
    this.fpsVerified,
    required this.fpsVerify,
    this.distortionCorrected,
    this.camera
  });

  static Capture fromJson(Map<String, dynamic> json) {
    return Capture(
      camera: json['camera'] == null ? null : Camera.fromJson(_asMap(json['camera'])),
      distortionCorrected: json['distortion_corrected'] as bool?,
      fpsVerify: FpsVerify.fromJson(_asMap(json['fps_verify']!)),
      fpsVerified: (json['fps_verified'] as num?)?.toDouble(),
      fpsDeclared: (json['fps_declared'] as num?)?.toDouble(),
      durationMs: (json['duration_ms'] as num?)?.toDouble(),
      frameCount: (json['frame_count']! as num).toInt(),
      resolution: Resolution.fromJson(_asMap(json['resolution']!)),
      deviceModel: json['device_model'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'camera': camera?.toJson(),
      'device_model': deviceModel,
      'distortion_corrected': distortionCorrected,
      'duration_ms': durationMs,
      'fps_declared': fpsDeclared,
      'fps_verified': fpsVerified,
      'fps_verify': fpsVerify.toJson(),
      'frame_count': frameCount,
      'resolution': resolution.toJson(),
    };
  }
}

/// 镜头运动检测结果。跟踪拍摄是本项目的前提，此结果影响多个指标的可用性
class CameraMotion {
  final CameraMotionLevel level;
  final bool isTracking;
  final CameraMotionDetectedBy? detectedBy;
  final double? meanShiftPxPerFrame;
  final String? note;

  const CameraMotion({
    required this.level,
    required this.isTracking,
    this.detectedBy,
    this.meanShiftPxPerFrame,
    this.note
  });

  static CameraMotion fromJson(Map<String, dynamic> json) {
    return CameraMotion(
      note: json['note'] as String?,
      meanShiftPxPerFrame: (json['mean_shift_px_per_frame'] as num?)?.toDouble(),
      detectedBy: CameraMotionDetectedBy.fromJson(json['detected_by']),
      isTracking: json['is_tracking']! as bool,
      level: _enumFromJson<CameraMotionLevel>(json['level']!, CameraMotionLevel.fromJson, 'level', CameraMotionLevel.valuesJson),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'detected_by': detectedBy?.toJson(),
      'is_tracking': isTracking,
      'level': level.toJson(),
      'mean_shift_px_per_frame': meanShiftPxPerFrame,
      'note': note,
    };
  }
}

class ValidRegion {
  final double xMin;
  final double xMax;

  const ValidRegion({
    required this.xMin,
    required this.xMax
  });

  static ValidRegion fromJson(Map<String, dynamic> json) {
    return ValidRegion(
      xMax: (json['x_max']! as num).toDouble(),
      xMin: (json['x_min']! as num).toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'x_max': xMax,
      'x_min': xMin,
    };
  }
}

/// 参考尺度。跟踪拍摄下为逐帧变化，此处为汇总信息
class ReferenceScale {
  final ReferenceScaleMethod method;
  /// 尺度是否逐帧变化。跟踪拍摄下为 true
  final bool validPerFrame;
  /// 为 null 时所有位移类指标返回 insufficient_data
  final double? medianPixelsPerMeter;
  final double? referenceLengthM;
  /// 有参考尺度的帧占比
  final double? coveragePct;
  final ValidRegion? validRegion;
  final String? note;

  const ReferenceScale({
    required this.method,
    required this.validPerFrame,
    this.medianPixelsPerMeter,
    this.referenceLengthM,
    this.coveragePct,
    this.validRegion,
    this.note
  });

  static ReferenceScale fromJson(Map<String, dynamic> json) {
    return ReferenceScale(
      note: json['note'] as String?,
      validRegion: json['valid_region'] == null ? null : ValidRegion.fromJson(_asMap(json['valid_region'])),
      coveragePct: (json['coverage_pct'] as num?)?.toDouble(),
      referenceLengthM: (json['reference_length_m'] as num?)?.toDouble(),
      medianPixelsPerMeter: (json['median_pixels_per_meter'] as num?)?.toDouble(),
      validPerFrame: json['valid_per_frame']! as bool,
      method: _enumFromJson<ReferenceScaleMethod>(json['method']!, ReferenceScaleMethod.fromJson, 'method', ReferenceScaleMethod.valuesJson),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'coverage_pct': coveragePct,
      'median_pixels_per_meter': medianPixelsPerMeter,
      'method': method.toJson(),
      'note': note,
      'reference_length_m': referenceLengthM,
      'valid_per_frame': validPerFrame,
      'valid_region': validRegion?.toJson(),
    };
  }
}

/// 采集场次。一次上传 = 一个 Session。定义来源：docs/07-数据契约.md §4
class Session {
  /// 契约版本，语义化版本格式
  final String schemaVersion;
  final String sessionId;
  final String teamId;
  final Athlete athlete;
  /// 采集时间，非报告生成时间
  final String recordedAt;
  final SessionTestType testType;
  /// 用户声明的拍摄视角。决定计算哪些指标
  final SessionView view;
  /// 系统自动推断的视角，用于交叉校验
  final SessionView viewDetected;
  /// 声明与推断是否一致。false 时报告需附提示
  final bool viewAgreement;
  final Capture capture;
  /// 镜头运动检测结果
  final CameraMotion cameraMotion;
  /// 参考尺度汇总信息
  final ReferenceScale referenceScale;
  /// 拍摄质量分。≥75 正常，55-74 附横幅，<55 不建议用于训练决策
  final double qualityScore;
  /// 质量分各分项得分，用于向用户解释扣分原因
  final Map<String, dynamic>? qualityBreakdown;
  final String? videoUrl;
  final SessionStatus status;
  final String? createdBy;
  final String? createdAt;

  const Session({
    required this.schemaVersion,
    required this.sessionId,
    required this.teamId,
    required this.athlete,
    required this.recordedAt,
    required this.testType,
    required this.view,
    required this.viewDetected,
    required this.viewAgreement,
    required this.capture,
    required this.cameraMotion,
    required this.referenceScale,
    required this.qualityScore,
    this.qualityBreakdown,
    this.videoUrl,
    required this.status,
    this.createdBy,
    this.createdAt
  });

  static Session fromJson(Map<String, dynamic> json) {
    return Session(
      createdAt: json['created_at'] as String?,
      createdBy: json['created_by'] as String?,
      status: _enumFromJson<SessionStatus>(json['status']!, SessionStatus.fromJson, 'status', SessionStatus.valuesJson),
      videoUrl: json['video_url'] as String?,
      qualityBreakdown: _asMapOrNull(json['quality_breakdown']),
      qualityScore: (json['quality_score']! as num).toDouble(),
      referenceScale: ReferenceScale.fromJson(_asMap(json['reference_scale'])),
      cameraMotion: CameraMotion.fromJson(_asMap(json['camera_motion'])),
      capture: Capture.fromJson(_asMap(json['capture']!)),
      viewAgreement: json['view_agreement']! as bool,
      viewDetected: _enumFromJson<SessionView>(json['view_detected'], SessionView.fromJson, 'view_detected', SessionView.valuesJson),
      view: _enumFromJson<SessionView>(json['view']!, SessionView.fromJson, 'view', SessionView.valuesJson),
      testType: _enumFromJson<SessionTestType>(json['test_type']!, SessionTestType.fromJson, 'test_type', SessionTestType.valuesJson),
      recordedAt: json['recorded_at']! as String,
      athlete: Athlete.fromJson(_asMap(json['athlete']!)),
      teamId: json['team_id']! as String,
      sessionId: json['session_id']! as String,
      schemaVersion: json['schema_version']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'athlete': athlete.toJson(),
      'camera_motion': cameraMotion.toJson(),
      'capture': capture.toJson(),
      'created_at': createdAt,
      'created_by': createdBy,
      'quality_breakdown': qualityBreakdown,
      'quality_score': qualityScore,
      'recorded_at': recordedAt,
      'reference_scale': referenceScale.toJson(),
      'schema_version': schemaVersion,
      'session_id': sessionId,
      'status': status.toJson(),
      'team_id': teamId,
      'test_type': testType.toJson(),
      'video_url': videoUrl,
      'view': view.toJson(),
      'view_agreement': viewAgreement,
      'view_detected': viewDetected.toJson(),
    };
  }
}

class Source {
  final int videoWidth;
  final int videoHeight;
  final int frameCount;
  final double? fpsDeclared;
  final double? fpsVerified;
  final FpsVerify fpsVerify;
  final bool? distortionCorrected;
  final CameraMotion cameraMotion;
  final ReferenceScale referenceScale;

  const Source({
    required this.videoWidth,
    required this.videoHeight,
    required this.frameCount,
    this.fpsDeclared,
    this.fpsVerified,
    required this.fpsVerify,
    this.distortionCorrected,
    required this.cameraMotion,
    required this.referenceScale
  });

  static Source fromJson(Map<String, dynamic> json) {
    return Source(
      referenceScale: ReferenceScale.fromJson(_asMap(json['reference_scale']!)),
      cameraMotion: CameraMotion.fromJson(_asMap(json['camera_motion']!)),
      distortionCorrected: json['distortion_corrected'] as bool?,
      fpsVerify: FpsVerify.fromJson(_asMap(json['fps_verify']!)),
      fpsVerified: (json['fps_verified'] as num?)?.toDouble(),
      fpsDeclared: (json['fps_declared'] as num?)?.toDouble(),
      frameCount: (json['frame_count']! as num).toInt(),
      videoHeight: (json['video_height']! as num).toInt(),
      videoWidth: (json['video_width']! as num).toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'camera_motion': cameraMotion.toJson(),
      'distortion_corrected': distortionCorrected,
      'fps_declared': fpsDeclared,
      'fps_verified': fpsVerified,
      'fps_verify': fpsVerify.toJson(),
      'frame_count': frameCount,
      'reference_scale': referenceScale.toJson(),
      'video_height': videoHeight,
      'video_width': videoWidth,
    };
  }
}

/// 时间零点定义。毫秒值由帧号与 fps_verified 导出，不依赖容器时间戳
class TimeBase {
  /// 时间零点的帧号。帧编号不一定从 0 开始（视频可能被裁剪）
  final int originFrameIndex;
  final TimeBaseEvent originReference;
  final TimeBaseUnit unit;

  const TimeBase({
    required this.originFrameIndex,
    required this.originReference,
    required this.unit
  });

  static TimeBase fromJson(Map<String, dynamic> json) {
    return TimeBase(
      unit: _enumFromJson<TimeBaseUnit>(json['unit']!, TimeBaseUnit.fromJson, 'unit', TimeBaseUnit.valuesJson),
      originReference: _enumFromJson<TimeBaseEvent>(json['origin_reference']!, TimeBaseEvent.fromJson, 'origin_reference', TimeBaseEvent.valuesJson),
      originFrameIndex: (json['origin_frame_index']! as num).toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'origin_frame_index': originFrameIndex,
      'origin_reference': originReference.toJson(),
      'unit': unit.toJson(),
    };
  }
}

class View {
  final SessionView declared;
  final SessionView detected;
  final bool? agreement;
  /// 跑动方向。影响角度正负号约定
  final ViewDirection? direction;
  /// 坐标系约定：归一化、原点左上、y 轴向下
  final ViewCoordSystem coordSystem;
  final String keypointFormat;
  final List<String> keypointNames;

  const View({
    required this.declared,
    required this.detected,
    this.agreement,
    this.direction,
    required this.coordSystem,
    required this.keypointFormat,
    required this.keypointNames
  });

  static View fromJson(Map<String, dynamic> json) {
    return View(
      keypointNames: (json['keypoint_names']! as List<dynamic>).cast<String>(),
      keypointFormat: json['keypoint_format']! as String,
      coordSystem: _enumFromJson<ViewCoordSystem>(json['coord_system']!, ViewCoordSystem.fromJson, 'coord_system', ViewCoordSystem.valuesJson),
      direction: ViewDirection.fromJson(json['direction']),
      agreement: json['agreement'] as bool?,
      detected: _enumFromJson<SessionView>(json['detected']!, SessionView.fromJson, 'detected', SessionView.valuesJson),
      declared: _enumFromJson<SessionView>(json['declared']!, SessionView.fromJson, 'declared', SessionView.valuesJson),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'agreement': agreement,
      'coord_system': coordSystem.toJson(),
      'declared': declared.toJson(),
      'detected': detected.toJson(),
      'direction': direction?.toJson(),
      'keypoint_format': keypointFormat,
      'keypoint_names': keypointNames,
    };
  }
}

/// 本次返回的帧窗口。客户端应据此判断是否为全量
class Window {
  final int from;
  final int to;
  final int returned;

  const Window({
    required this.from,
    required this.to,
    required this.returned
  });

  static Window fromJson(Map<String, dynamic> json) {
    return Window(
      returned: (json['returned']! as num).toInt(),
      to: (json['to']! as num).toInt(),
      from: (json['from']! as num).toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'from': from,
      'returned': returned,
      'to': to,
    };
  }
}

/// 单个关键点。q=0 时 x/y 为 0，客户端不应绘制
class Keypoint {
  /// 归一化横坐标，原点在画面左上角
  final double x;
  /// 归一化纵坐标，原点在画面左上角，向下为正
  final double y;
  final KeypointQualityCode q;

  const Keypoint({
    required this.x,
    required this.y,
    required this.q
  });

  static Keypoint fromJson(Map<String, dynamic> json) {
    return Keypoint(
      q: _enumFromJson<KeypointQualityCode>(json['q']!, KeypointQualityCode.fromJson, 'q', KeypointQualityCode.valuesJson),
      y: (json['y']! as num).toDouble(),
      x: (json['x']! as num).toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'q': q.toJson(),
      'x': x,
      'y': y,
    };
  }
}

class PoseFrame {
  /// 视频中的绝对帧号
  final int frameIndex;
  /// 相对 time_base.origin_frame_index 的毫秒数
  final double? timeMs;
  final double? personConf;
  final List<double>? bbox;
  /// 定长数组，长度必须等于 view.keypoint_names 的长度。不可见点用 q=0 占位，不得缺项
  final List<Keypoint> keypoints;
  final bool isOccluded;
  /// 该帧为插值补出，非实测。客户端必须画成虚线，不可与实测混淆
  final bool isInterpolated;
  /// 有效测量窗标记。excluded 的帧不参与任何指标计算
  final PoseFrameMeasurementWindow measurementWindow;
  /// 该帧的视线偏斜角估计。越大表示运动员偏离画面中心越远
  final double? skewDeg;
  /// 该帧的参考尺度。跟踪拍摄下逐帧不同，位移换算必须用此值而非全局值
  final double? pixelsPerMeter;

  const PoseFrame({
    required this.frameIndex,
    this.timeMs,
    this.personConf,
    this.bbox,
    required this.keypoints,
    required this.isOccluded,
    required this.isInterpolated,
    required this.measurementWindow,
    this.skewDeg,
    this.pixelsPerMeter
  });

  static PoseFrame fromJson(Map<String, dynamic> json) {
    return PoseFrame(
      pixelsPerMeter: (json['pixels_per_meter'] as num?)?.toDouble(),
      skewDeg: (json['skew_deg'] as num?)?.toDouble(),
      measurementWindow: _enumFromJson<PoseFrameMeasurementWindow>(json['measurement_window'], PoseFrameMeasurementWindow.fromJson, 'measurement_window', PoseFrameMeasurementWindow.valuesJson),
      isInterpolated: json['is_interpolated']! as bool,
      isOccluded: json['is_occluded']! as bool,
      keypoints: (json['keypoints']! as List<dynamic>).map((e) => Keypoint.fromJson(_asMap(e))).toList(),
      bbox: (json['bbox'] as List<dynamic>?)?.cast<double>(),
      personConf: (json['person_conf'] as num?)?.toDouble(),
      timeMs: (json['time_ms'] as num?)?.toDouble(),
      frameIndex: (json['frame_index']! as num).toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'bbox': bbox,
      'frame_index': frameIndex,
      'is_interpolated': isInterpolated,
      'is_occluded': isOccluded,
      'keypoints': keypoints.map((e) => e.toJson()).toList(),
      'measurement_window': measurementWindow.toJson(),
      'person_conf': personConf,
      'pixels_per_meter': pixelsPerMeter,
      'skew_deg': skewDeg,
      'time_ms': timeMs,
    };
  }
}

/// 姿态数据。逐帧人体关键点。定义来源：docs/07-数据契约.md §5
class PoseResponse {
  /// 契约版本，语义化版本格式
  final String schemaVersion;
  final String sessionId;
  final String analysisId;
  final Source source;
  final TimeBase timeBase;
  final View view;
  /// 本次返回的帧窗口。客户端应据此判断是否为全量
  final Window? window;
  /// 逐帧数据。单次请求最多返回 600 帧
  final List<PoseFrame> frames;

  const PoseResponse({
    required this.schemaVersion,
    required this.sessionId,
    required this.analysisId,
    required this.source,
    required this.timeBase,
    required this.view,
    this.window,
    required this.frames
  });

  static PoseResponse fromJson(Map<String, dynamic> json) {
    return PoseResponse(
      frames: (json['frames']! as List<dynamic>).map((e) => PoseFrame.fromJson(_asMap(e))).toList(),
      window: json['window'] == null ? null : Window.fromJson(_asMap(json['window'])),
      view: View.fromJson(_asMap(json['view']!)),
      timeBase: TimeBase.fromJson(_asMap(json['time_base']!)),
      source: Source.fromJson(_asMap(json['source']!)),
      analysisId: json['analysis_id']! as String,
      sessionId: json['session_id']! as String,
      schemaVersion: json['schema_version']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'analysis_id': analysisId,
      'frames': frames.map((e) => e.toJson()).toList(),
      'schema_version': schemaVersion,
      'session_id': sessionId,
      'source': source.toJson(),
      'time_base': timeBase.toJson(),
      'view': view.toJson(),
      'window': window?.toJson(),
    };
  }
}

/// 同阶段多步次的统计量。单次采样不可用于判断，n 必须给出
class Aggregate {
  final double? mean;
  final double? sd;
  final int n;
  final double? min;
  final double? max;

  const Aggregate({
    this.mean,
    this.sd,
    required this.n,
    this.min,
    this.max
  });

  static Aggregate fromJson(Map<String, dynamic> json) {
    return Aggregate(
      max: (json['max'] as num?)?.toDouble(),
      min: (json['min'] as num?)?.toDouble(),
      n: (json['n']! as num).toInt(),
      sd: (json['sd'] as num?)?.toDouble(),
      mean: (json['mean'] as num?)?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'max': max,
      'mean': mean,
      'min': min,
      'n': n,
      'sd': sd,
    };
  }
}

/// 标准值区间。applicable_phase 与指标 phase 不符时，deviation 必须为 null
class ReferenceRange {
  final double? low;
  final double? high;
  final double? mean;
  /// 缺失时 deviation 必须为 null，不得用经验值补全
  final double? sd;
  final ReferenceRangeRefSource source;
  final MetricPhase applicablePhase;
  final SessionView view;
  final String stdVersion;

  const ReferenceRange({
    this.low,
    this.high,
    this.mean,
    this.sd,
    required this.source,
    required this.applicablePhase,
    required this.view,
    required this.stdVersion
  });

  static ReferenceRange fromJson(Map<String, dynamic> json) {
    return ReferenceRange(
      stdVersion: json['std_version']! as String,
      view: _enumFromJson<SessionView>(json['view']!, SessionView.fromJson, 'view', SessionView.valuesJson),
      applicablePhase: _enumFromJson<MetricPhase>(json['applicable_phase']!, MetricPhase.fromJson, 'applicable_phase', MetricPhase.valuesJson),
      source: _enumFromJson<ReferenceRangeRefSource>(json['source']!, ReferenceRangeRefSource.fromJson, 'source', ReferenceRangeRefSource.valuesJson),
      sd: (json['sd'] as num?)?.toDouble(),
      mean: (json['mean'] as num?)?.toDouble(),
      high: (json['high'] as num?)?.toDouble(),
      low: (json['low'] as num?)?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'applicable_phase': applicablePhase.toJson(),
      'high': high,
      'low': low,
      'mean': mean,
      'sd': sd,
      'source': source.toJson(),
      'std_version': stdVersion,
      'view': view.toJson(),
    };
  }
}

/// 数据不足的说明。三要素必须齐全：是什么、为什么、怎么办
class InsufficientInfo {
  final InsufficientReason reason;
  /// 该指标需要什么条件
  final String required;
  /// 本次实际的条件
  final String actual;
  /// 受影响的指标 ID 列表
  final List<String> impact;
  /// 给用户的可操作建议。必填，不得为空
  final String suggestion;

  const InsufficientInfo({
    required this.reason,
    required this.required,
    required this.actual,
    required this.impact,
    required this.suggestion
  });

  static InsufficientInfo fromJson(Map<String, dynamic> json) {
    return InsufficientInfo(
      suggestion: json['suggestion']! as String,
      impact: (json['impact']! as List<dynamic>).cast<String>(),
      actual: json['actual']! as String,
      required: json['required']! as String,
      reason: _enumFromJson<InsufficientReason>(json['reason']!, InsufficientReason.fromJson, 'reason', InsufficientReason.valuesJson),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'actual': actual,
      'impact': impact,
      'reason': reason.toJson(),
      'required': required,
      'suggestion': suggestion,
    };
  }
}

/// 指标。定义来源：docs/07-数据契约.md §6
class Metric {
  /// 全局唯一 ID。清单见 docs/03-指标定义.md 附录 A
  final String metricId;
  final String nameZh;
  /// ratio 表示无量纲比值
  final MetricUnit unit;
  /// 该指标所属视角。与请求视角不匹配时返回 insufficient_data
  final SessionView view;
  final MetricPhase phase;
  /// 事件帧指标才有；逐帧指标为 null
  final TimeBaseEvent? event;
  /// 分侧指标才有
  final MetricSide? side;
  final int? frameIndex;
  final double? timeMs;
  /// 单帧/单次值。insufficient_data 时为 null。枚举类指标为字符串
  final Object? value;
  /// 同阶段多步次的统计量
  final Aggregate? aggregate;
  /// 参与计算的有效帧数（已排除窗外帧与 ambiguous 帧）
  final int? validFrameCount;
  final int? totalFrameCount;
  /// 标准值区间。为 null 表示无标准值，此时不做偏离判断
  final ReferenceRange? ref;
  /// 标准化偏离。下列任一情况必须为 null：(1) ref.sd 缺失 (2) ref.applicable_phase 与 phase 不符 (3)
  /// ref.view 与 view 不匹配
  final double? deviation;
  /// 这个数准不准。与 reliable 是两个不同问题
  final double? confidence;
  final MetricReliability reliability;
  /// 这个数该不该用。false 时界面必须显示但标注警示，不得隐藏
  final bool reliable;
  /// reliable=false 时必须给出原因，不得为 null
  final String? reliabilityNote;
  /// 该指标受镜头跟踪影响的角度误差量级（度）。>3 时报告结论措辞必须降级
  final double? perspectiveErrorEstimate;
  /// 数据不足的说明。数据不足时必须输出，不得静默省略该指标
  final InsufficientInfo? insufficient;

  const Metric({
    required this.metricId,
    required this.nameZh,
    required this.unit,
    required this.view,
    required this.phase,
    this.event,
    this.side,
    this.frameIndex,
    this.timeMs,
    this.value,
    this.aggregate,
    this.validFrameCount,
    this.totalFrameCount,
    this.ref,
    this.deviation,
    this.confidence,
    required this.reliability,
    required this.reliable,
    this.reliabilityNote,
    this.perspectiveErrorEstimate,
    this.insufficient
  });

  static Metric fromJson(Map<String, dynamic> json) {
    return Metric(
      insufficient: json['insufficient'] == null ? null : InsufficientInfo.fromJson(_asMap(json['insufficient'])),
      perspectiveErrorEstimate: (json['perspective_error_estimate'] as num?)?.toDouble(),
      reliabilityNote: json['reliability_note'] as String?,
      reliable: json['reliable']! as bool,
      reliability: _enumFromJson<MetricReliability>(json['reliability']!, MetricReliability.fromJson, 'reliability', MetricReliability.valuesJson),
      confidence: (json['confidence'] as num?)?.toDouble(),
      deviation: (json['deviation'] as num?)?.toDouble(),
      ref: json['ref'] == null ? null : ReferenceRange.fromJson(_asMap(json['ref'])),
      totalFrameCount: (json['total_frame_count'] as num?)?.toInt(),
      validFrameCount: (json['valid_frame_count'] as num?)?.toInt(),
      aggregate: json['aggregate'] == null ? null : Aggregate.fromJson(_asMap(json['aggregate'])),
      value: json['value'],
      timeMs: (json['time_ms'] as num?)?.toDouble(),
      frameIndex: (json['frame_index'] as num?)?.toInt(),
      side: MetricSide.fromJson(json['side']),
      event: TimeBaseEvent.fromJson(json['event']),
      phase: _enumFromJson<MetricPhase>(json['phase']!, MetricPhase.fromJson, 'phase', MetricPhase.valuesJson),
      view: _enumFromJson<SessionView>(json['view']!, SessionView.fromJson, 'view', SessionView.valuesJson),
      unit: _enumFromJson<MetricUnit>(json['unit']!, MetricUnit.fromJson, 'unit', MetricUnit.valuesJson),
      nameZh: json['name_zh']! as String,
      metricId: json['metric_id']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'aggregate': aggregate?.toJson(),
      'confidence': confidence,
      'deviation': deviation,
      'event': event?.toJson(),
      'frame_index': frameIndex,
      'insufficient': insufficient?.toJson(),
      'metric_id': metricId,
      'name_zh': nameZh,
      'perspective_error_estimate': perspectiveErrorEstimate,
      'phase': phase.toJson(),
      'ref': ref?.toJson(),
      'reliability': reliability.toJson(),
      'reliability_note': reliabilityNote,
      'reliable': reliable,
      'side': side?.toJson(),
      'time_ms': timeMs,
      'total_frame_count': totalFrameCount,
      'unit': unit.toJson(),
      'valid_frame_count': validFrameCount,
      'value': value,
      'view': view.toJson(),
    };
  }
}

class Evidence {
  final String metricId;
  final Object? value;
  final double? refLow;
  final double? refHigh;
  /// 人类可读的偏离描述，如'低于下限 6.8°'
  final String? deviationText;
  final MetricPhase? phase;
  final int? frameIndex;

  const Evidence({
    required this.metricId,
    this.value,
    this.refLow,
    this.refHigh,
    this.deviationText,
    this.phase,
    this.frameIndex
  });

  static Evidence fromJson(Map<String, dynamic> json) {
    return Evidence(
      frameIndex: (json['frame_index'] as num?)?.toInt(),
      phase: MetricPhase.fromJson(json['phase']),
      deviationText: json['deviation_text'] as String?,
      refHigh: (json['ref_high'] as num?)?.toDouble(),
      refLow: (json['ref_low'] as num?)?.toDouble(),
      value: json['value'],
      metricId: json['metric_id']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'deviation_text': deviationText,
      'frame_index': frameIndex,
      'metric_id': metricId,
      'phase': phase?.toJson(),
      'ref_high': refHigh,
      'ref_low': refLow,
      'value': value,
    };
  }
}

class Drill {
  final String drillId;
  final String name;
  final String? sets;
  final String? reps;
  final String? duration;
  /// 教练现场喊给运动员的口令。一句话、可执行、无术语、单一焦点。处方块中最重要的一行
  final String cue;
  /// 为什么这个练习能解决该问题
  final String? mechanism;
  final String? videoUrl;

  const Drill({
    required this.drillId,
    required this.name,
    this.sets,
    this.reps,
    this.duration,
    required this.cue,
    this.mechanism,
    this.videoUrl
  });

  static Drill fromJson(Map<String, dynamic> json) {
    return Drill(
      videoUrl: json['video_url'] as String?,
      mechanism: json['mechanism'] as String?,
      cue: json['cue']! as String,
      duration: json['duration'] as String?,
      reps: json['reps'] as String?,
      sets: json['sets'] as String?,
      name: json['name']! as String,
      drillId: json['drill_id']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'cue': cue,
      'drill_id': drillId,
      'duration': duration,
      'mechanism': mechanism,
      'name': name,
      'reps': reps,
      'sets': sets,
      'video_url': videoUrl,
    };
  }
}

/// 结论。规则引擎的输出，是'判断'而非'事实'。定义来源：docs/07-数据契约.md §7
class Finding {
  final String findingId;
  /// 结论的责任人。教练质疑时据此追溯到规则。数据不足型结论为 null
  final String? ruleId;
  final String? ruleVersion;
  final FindingSeverity severity;
  final SessionView view;
  final MetricPhase phase;
  /// 一句话结论。不得评价人，只描述动作现象
  final String title;
  /// 关联指标 ID，供界面联动高亮。无关联时返回空数组，不返回 null
  final List<String> metricIds;
  /// 具体证据：实测值、标准区间、偏离量、帧号。数据不足型结论返回空数组，不返回 null
  final List<Evidence> evidence;
  /// 必须写机制，不得重复 title。判断标准：必须有一句能回答'这为什么是问题'
  final String explanation;
  /// 结论置信度。若依据的指标 reliable=false，此值必须 <= 0.5
  final double? confidence;
  final FindingBasis? basis;
  /// 低置信度时给用户的明确提示。basis=normal 时为 null，否则必填
  final String? caveat;
  /// 训练处方。不超过 3 个，超过则教练无从选择
  final List<Drill> drills;
  /// 数据不足型结论（severity=insufficient_data）才有
  final InsufficientReason? reason;
  /// 数据不足型结论：该判断需要什么条件
  final String? required;
  /// 数据不足型结论：本次实际的条件
  final String? actual;
  /// 数据不足型结论：受影响的指标 ID
  final List<String>? impact;
  /// 数据不足型结论：给用户的可操作建议。必填，不得为空
  final String? suggestion;

  const Finding({
    required this.findingId,
    this.ruleId,
    this.ruleVersion,
    required this.severity,
    required this.view,
    required this.phase,
    required this.title,
    required this.metricIds,
    required this.evidence,
    required this.explanation,
    this.confidence,
    this.basis,
    this.caveat,
    required this.drills,
    this.reason,
    this.required,
    this.actual,
    this.impact,
    this.suggestion
  });

  static Finding fromJson(Map<String, dynamic> json) {
    return Finding(
      suggestion: json['suggestion'] as String?,
      impact: (json['impact'] as List<dynamic>?)?.cast<String>(),
      actual: json['actual'] as String?,
      required: json['required'] as String?,
      reason: InsufficientReason.fromJson(json['reason']),
      drills: (json['drills']! as List<dynamic>).map((e) => Drill.fromJson(_asMap(e))).toList(),
      caveat: json['caveat'] as String?,
      basis: FindingBasis.fromJson(json['basis']),
      confidence: (json['confidence'] as num?)?.toDouble(),
      explanation: json['explanation']! as String,
      evidence: (json['evidence']! as List<dynamic>).map((e) => Evidence.fromJson(_asMap(e))).toList(),
      metricIds: (json['metric_ids']! as List<dynamic>).cast<String>(),
      title: json['title']! as String,
      phase: _enumFromJson<MetricPhase>(json['phase']!, MetricPhase.fromJson, 'phase', MetricPhase.valuesJson),
      view: _enumFromJson<SessionView>(json['view']!, SessionView.fromJson, 'view', SessionView.valuesJson),
      severity: _enumFromJson<FindingSeverity>(json['severity']!, FindingSeverity.fromJson, 'severity', FindingSeverity.valuesJson),
      ruleVersion: json['rule_version'] as String?,
      ruleId: json['rule_id'] as String?,
      findingId: json['finding_id']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'actual': actual,
      'basis': basis?.toJson(),
      'caveat': caveat,
      'confidence': confidence,
      'drills': drills.map((e) => e.toJson()).toList(),
      'evidence': evidence.map((e) => e.toJson()).toList(),
      'explanation': explanation,
      'finding_id': findingId,
      'impact': impact,
      'metric_ids': metricIds,
      'phase': phase.toJson(),
      'reason': reason?.toJson(),
      'required': required,
      'rule_id': ruleId,
      'rule_version': ruleVersion,
      'severity': severity.toJson(),
      'suggestion': suggestion,
      'title': title,
      'view': view.toJson(),
    };
  }
}

/// 五套版本号中的四套（schema_version 在根级）。用于回答'为什么这次数据和上次不一样'
class Versions {
  final String algoVersion;
  final String modelVersion;
  final String ruleVersion;
  final String stdVersion;

  const Versions({
    required this.algoVersion,
    required this.modelVersion,
    required this.ruleVersion,
    required this.stdVersion
  });

  static Versions fromJson(Map<String, dynamic> json) {
    return Versions(
      stdVersion: json['std_version']! as String,
      ruleVersion: json['rule_version']! as String,
      modelVersion: json['model_version']! as String,
      algoVersion: json['algo_version']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'algo_version': algoVersion,
      'model_version': modelVersion,
      'rule_version': ruleVersion,
      'std_version': stdVersion,
    };
  }
}

class PhaseDetection {
  final MetricPhase phase;
  final int frameStart;
  final int frameEnd;
  /// 阶段切分置信度。低于阈值时该阶段所有结论降级为 insufficient_data
  final double? confidence;

  const PhaseDetection({
    required this.phase,
    required this.frameStart,
    required this.frameEnd,
    this.confidence
  });

  static PhaseDetection fromJson(Map<String, dynamic> json) {
    return PhaseDetection(
      confidence: (json['confidence'] as num?)?.toDouble(),
      frameEnd: (json['frame_end']! as num).toInt(),
      frameStart: (json['frame_start']! as num).toInt(),
      phase: _enumFromJson<MetricPhase>(json['phase']!, MetricPhase.fromJson, 'phase', MetricPhase.valuesJson),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'confidence': confidence,
      'frame_end': frameEnd,
      'frame_start': frameStart,
      'phase': phase.toJson(),
    };
  }
}

/// 总览。headline 由服务端确定性生成，不由 LLM 自由撰写
class Summary {
  /// 一句话总结，不超过 60 字
  final String headline;
  final int majorCount;
  final int minorCount;
  final int insufficientCount;

  const Summary({
    required this.headline,
    required this.majorCount,
    required this.minorCount,
    required this.insufficientCount
  });

  static Summary fromJson(Map<String, dynamic> json) {
    return Summary(
      insufficientCount: (json['insufficient_count']! as num).toInt(),
      minorCount: (json['minor_count']! as num).toInt(),
      majorCount: (json['major_count']! as num).toInt(),
      headline: json['headline']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'headline': headline,
      'insufficient_count': insufficientCount,
      'major_count': majorCount,
      'minor_count': minorCount,
    };
  }
}

class KeyframeAnnotation {
  final String metricId;
  final double value;
  final String unit;
  final double? refLow;
  final double? refHigh;

  const KeyframeAnnotation({
    required this.metricId,
    required this.value,
    required this.unit,
    this.refLow,
    this.refHigh
  });

  static KeyframeAnnotation fromJson(Map<String, dynamic> json) {
    return KeyframeAnnotation(
      refHigh: (json['ref_high'] as num?)?.toDouble(),
      refLow: (json['ref_low'] as num?)?.toDouble(),
      unit: json['unit']! as String,
      value: (json['value']! as num).toDouble(),
      metricId: json['metric_id']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'metric_id': metricId,
      'ref_high': refHigh,
      'ref_low': refLow,
      'unit': unit,
      'value': value,
    };
  }
}

class Keyframe {
  final int frameIndex;
  final TimeBaseEvent event;
  final MetricSide? side;
  final int? stepIndex;
  final MetricPhase phase;
  final String imageUrl;
  /// 该帧的参考尺度。报告必须在关键帧图上绘制尺度条，否则教练会误判体型变化
  final double? pixelsPerMeter;
  /// 该帧上要标注的角度值
  final List<KeyframeAnnotation> annotations;

  const Keyframe({
    required this.frameIndex,
    required this.event,
    this.side,
    this.stepIndex,
    required this.phase,
    required this.imageUrl,
    this.pixelsPerMeter,
    required this.annotations
  });

  static Keyframe fromJson(Map<String, dynamic> json) {
    return Keyframe(
      annotations: (json['annotations']! as List<dynamic>).map((e) => KeyframeAnnotation.fromJson(_asMap(e))).toList(),
      pixelsPerMeter: (json['pixels_per_meter'] as num?)?.toDouble(),
      imageUrl: json['image_url']! as String,
      phase: _enumFromJson<MetricPhase>(json['phase']!, MetricPhase.fromJson, 'phase', MetricPhase.valuesJson),
      stepIndex: (json['step_index'] as num?)?.toInt(),
      side: MetricSide.fromJson(json['side']),
      event: _enumFromJson<TimeBaseEvent>(json['event']!, TimeBaseEvent.fromJson, 'event', TimeBaseEvent.valuesJson),
      frameIndex: (json['frame_index']! as num).toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'annotations': annotations.map((e) => e.toJson()).toList(),
      'event': event.toJson(),
      'frame_index': frameIndex,
      'image_url': imageUrl,
      'phase': phase.toJson(),
      'pixels_per_meter': pixelsPerMeter,
      'side': side?.toJson(),
      'step_index': stepIndex,
    };
  }
}

/// 聚合分析结果。报告页一次拉取全部内容。定义来源：docs/07-数据契约.md §8
class AnalysisResult {
  /// 契约版本，语义化版本格式
  final String schemaVersion;
  final String analysisId;
  final Session session;
  final Versions versions;
  final double qualityScore;
  /// 整份报告的透视误差量级（度），取各指标的最大值
  final double? perspectiveErrorEstimate;
  final List<PhaseDetection> phasesDetected;
  /// 全部指标，含数据不足的。数据不足的指标 value 为 null 且 insufficient 非 null。无数据时返回空数组，不返回 null
  final List<Metric> metrics;
  /// 全部结论，含数据不足型。报告主体只展示 severity 为 major/minor 的前 3 条。无结论时返回空数组，不返回 null
  final List<Finding> findings;
  final Summary summary;
  final List<Keyframe> keyframes;

  const AnalysisResult({
    required this.schemaVersion,
    required this.analysisId,
    required this.session,
    required this.versions,
    required this.qualityScore,
    this.perspectiveErrorEstimate,
    required this.phasesDetected,
    required this.metrics,
    required this.findings,
    required this.summary,
    required this.keyframes
  });

  static AnalysisResult fromJson(Map<String, dynamic> json) {
    return AnalysisResult(
      keyframes: (json['keyframes']! as List<dynamic>).map((e) => Keyframe.fromJson(_asMap(e))).toList(),
      summary: Summary.fromJson(_asMap(json['summary']!)),
      findings: (json['findings']! as List<dynamic>).map((e) => Finding.fromJson(_asMap(e))).toList(),
      metrics: (json['metrics']! as List<dynamic>).map((e) => Metric.fromJson(_asMap(e))).toList(),
      phasesDetected: (json['phases_detected']! as List<dynamic>).map((e) => PhaseDetection.fromJson(_asMap(e))).toList(),
      perspectiveErrorEstimate: (json['perspective_error_estimate'] as num?)?.toDouble(),
      qualityScore: (json['quality_score']! as num).toDouble(),
      versions: Versions.fromJson(_asMap(json['versions']!)),
      session: Session.fromJson(_asMap(json['session']!)),
      analysisId: json['analysis_id']! as String,
      schemaVersion: json['schema_version']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'analysis_id': analysisId,
      'findings': findings.map((e) => e.toJson()).toList(),
      'keyframes': keyframes.map((e) => e.toJson()).toList(),
      'metrics': metrics.map((e) => e.toJson()).toList(),
      'perspective_error_estimate': perspectiveErrorEstimate,
      'phases_detected': phasesDetected.map((e) => e.toJson()).toList(),
      'quality_score': qualityScore,
      'schema_version': schemaVersion,
      'session': session.toJson(),
      'summary': summary.toJson(),
      'versions': versions.toJson(),
    };
  }
}

class Stage {
  /// 阶段名。与分析链路的顺序一致
  final StageName name;
  final StageStatus status;
  final int? durationMs;
  final String? note;

  const Stage({
    required this.name,
    required this.status,
    this.durationMs,
    this.note
  });

  static Stage fromJson(Map<String, dynamic> json) {
    return Stage(
      note: json['note'] as String?,
      durationMs: (json['duration_ms'] as num?)?.toInt(),
      status: _enumFromJson<StageStatus>(json['status']!, StageStatus.fromJson, 'status', StageStatus.valuesJson),
      name: _enumFromJson<StageName>(json['name']!, StageName.fromJson, 'name', StageName.valuesJson),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'duration_ms': durationMs,
      'name': name.toJson(),
      'note': note,
      'status': status.toJson(),
    };
  }
}

/// 错误对象。suggestion 必填——失败时只显示'失败'是无用的。定义来源：docs/07-数据契约.md §2.2、§9
class ApiError {
  /// 错误码。1xxx 认证权限 / 2xxx 参数 / 3xxx 资源状态 / 4xxx 业务拒绝 / 5xxx 服务异常
  final int code;
  /// 简短错误描述
  final String message;
  /// 详细说明，用于解释具体发生了什么
  final String? detail;
  /// 给用户的可操作建议。必填，不得为空字符串。必须告诉用户下一步做什么
  final String suggestion;
  /// 用户能否通过重试或调整输入解决。true 时界面应提供重试入口
  final bool recoverable;
  /// 需要用户执行的特定动作，界面据此弹出对应的交互
  final ApiErrorActionRequired? actionRequired;

  const ApiError({
    required this.code,
    required this.message,
    this.detail,
    required this.suggestion,
    required this.recoverable,
    this.actionRequired
  });

  static ApiError fromJson(Map<String, dynamic> json) {
    return ApiError(
      actionRequired: ApiErrorActionRequired.fromJson(json['action_required']),
      recoverable: json['recoverable']! as bool,
      suggestion: json['suggestion']! as String,
      detail: json['detail'] as String?,
      message: json['message']! as String,
      code: (json['code']! as num).toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'action_required': actionRequired?.toJson(),
      'code': code,
      'detail': detail,
      'message': message,
      'recoverable': recoverable,
      'suggestion': suggestion,
    };
  }
}

/// 分析任务状态。stages 必须暴露，否则 90 秒的等待会让用户以为卡死。定义来源：docs/07-数据契约.md §9
class AnalysisTask {
  final String taskId;
  final String sessionId;
  final String? analysisId;
  final AnalysisTaskTaskStatus status;
  /// 当前阶段名，与 stages[].name 对应
  final String? stage;
  final double? progress;
  /// 分阶段进度。必须暴露全部阶段，让用户知道还要等多久，也让失败时能定位到具体阶段
  final List<Stage> stages;
  final ApiError? error;
  final String? createdAt;
  final String? finishedAt;

  const AnalysisTask({
    required this.taskId,
    required this.sessionId,
    this.analysisId,
    required this.status,
    this.stage,
    this.progress,
    required this.stages,
    this.error,
    this.createdAt,
    this.finishedAt
  });

  static AnalysisTask fromJson(Map<String, dynamic> json) {
    return AnalysisTask(
      finishedAt: json['finished_at'] as String?,
      createdAt: json['created_at'] as String?,
      error: json['error'] == null ? null : ApiError.fromJson(_asMap(json['error'])),
      stages: (json['stages']! as List<dynamic>).map((e) => Stage.fromJson(_asMap(e))).toList(),
      progress: (json['progress'] as num?)?.toDouble(),
      stage: json['stage'] as String?,
      status: _enumFromJson<AnalysisTaskTaskStatus>(json['status']!, AnalysisTaskTaskStatus.fromJson, 'status', AnalysisTaskTaskStatus.valuesJson),
      analysisId: json['analysis_id'] as String?,
      sessionId: json['session_id']! as String,
      taskId: json['task_id']! as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'analysis_id': analysisId,
      'created_at': createdAt,
      'error': error?.toJson(),
      'finished_at': finishedAt,
      'progress': progress,
      'session_id': sessionId,
      'stage': stage,
      'stages': stages.map((e) => e.toJson()).toList(),
      'status': status.toJson(),
      'task_id': taskId,
    };
  }
}
