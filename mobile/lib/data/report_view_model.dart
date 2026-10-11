import '../models/models.dart';

/// 界面需要的三种数据状态。
///
/// 契约里这些信息散落在多个字段上（reliable / confidence / insufficient /
/// perspective_error_estimate），界面不应该逐个字段去判断 —— 那是把业务规则
/// 漏进 UI 层。这里统一归约成一个枚举，界面只需 switch 三档。
///
/// 对应 docs/08-App功能与交互规范.md §4：
/// 让「不确定性」可见，是这个产品区别于玩具的地方。
enum MetricState {
  /// 可用于判断
  normal,

  /// 能算出来，但不该用于判断（帧率不足、跟踪过快、参考尺度不可靠）
  lowConfidence,

  /// 根本没算出来
  insufficient,
}

/// 单个指标在界面上的呈现形态。
class MetricView {
  const MetricView({
    required this.metricId,
    required this.nameZh,
    required this.unit,
    required this.state,
    required this.valueText,
    required this.hasReference,
    this.refLow,
    this.refHigh,
    this.refSource,
    this.refSourceText,
    this.note,
    this.insufficientReason,
    this.insufficientSuggestion,
    this.confidencePercent,
  });

  final String metricId;
  final String nameZh;
  final String unit;
  final MetricState state;

  /// 已格式化好待显示的数值，如 "183 ms"、"——"
  final String valueText;

  final bool hasReference;
  final double? refLow;
  final double? refHigh;

  final ReferenceRangeRefSource? refSource;

  /// 标准值来源的用户化措辞。
  /// 教练对「跟队友比」的信任度远高于「跟文献比」，措辞必须不同。
  final String? refSourceText;

  /// 低置信时必须给出的原因，界面显示在数值下方
  final String? note;

  final InsufficientReason? insufficientReason;

  /// 数据不足时给教练的可操作建议 —— 这是 App 里最有价值的一段文案
  final String? insufficientSuggestion;

  final int? confidencePercent;

  bool get needsAttention => state != MetricState.normal;
}

/// 单位的中文显示。
String unitLabel(String unit) => switch (unit) {
      'deg' => '°',
      'ms' => 'ms',
      'm' => 'm',
      'm/s' => 'm/s',
      'steps/min' => '步/分',
      'ratio' => '',
      'enum' => '',
      _ => unit,
    };

/// 把契约里的指标转成界面模型。
MetricView toMetricView(Metric metric) {
  final state = _resolveState(metric);

  return MetricView(
    metricId: metric.metricId,
    nameZh: metric.nameZh,
    unit: metric.unit.toJson(),
    state: state,
    valueText: _formatValue(metric),
    hasReference: metric.ref?.low != null && metric.ref?.high != null,
    refLow: metric.ref?.low,
    refHigh: metric.ref?.high,
    refSource: metric.ref?.source,
    refSourceText: _refSourceText(metric.ref?.source),
    note: _noteFor(metric),
    insufficientReason: metric.insufficient?.reason,
    insufficientSuggestion: metric.insufficient?.suggestion,
    confidencePercent:
        metric.confidence == null ? null : (metric.confidence! * 100).round(),
  );
}

MetricState _resolveState(Metric metric) {
  if (metric.insufficient != null || metric.value == null) {
    return MetricState.insufficient;
  }
  // confidence 与 reliable 是两个不同问题：
  //   reliable=false  —— 这个数不该用（方法学上不成立）
  //   confidence 低    —— 这个数可能不准（测量质量差）
  // 任一成立都要标警示，但都仍然显示数值 —— 隐藏会让教练怀疑数据被挑选过。
  // 见 docs/07-数据契约.md §6.3、§6.4。
  if (!metric.reliable || (metric.confidence ?? 1.0) < 0.7) {
    return MetricState.lowConfidence;
  }
  return MetricState.normal;
}

String _formatValue(Metric metric) {
  final value = metric.value;
  if (value == null) return '——';

  final unit = unitLabel(metric.unit.toJson());

  if (value is num) {
    // 不同单位的小数位不同：毫秒取整，角度一位，比值两位
    final digits = switch (metric.unit) {
      MetricUnit.ms => 0,
      MetricUnit.deg => 1,
      MetricUnit.ratio => 2,
      _ => 1,
    };
    return '${value.toStringAsFixed(digits)}$unit';
  }
  return '$value';
}

String? _noteFor(Metric metric) {
  if (metric.insufficient != null) return null;
  if (metric.reliabilityNote != null) return metric.reliabilityNote;

  final err = metric.perspectiveErrorEstimate;
  if (err != null && err > 3.0) {
    return '镜头跟踪导致透视误差约 ±${err.toStringAsFixed(1)}°，该数值可能偏小';
  }
  return null;
}

String? _refSourceText(ReferenceRangeRefSource? source) => switch (source) {
      ReferenceRangeRefSource.literature => '文献参考值',
      ReferenceRangeRefSource.team => '本队同水平均值',
      ReferenceRangeRefSource.global => '同项目均值',
      null => null,
    };

/// 数据不足原因的用户化措辞。
///
/// 这些文案直接决定教练下次怎么拍 —— 是整个 App 中最有价值的部分之一。
/// 不得使用「数据异常」这类无信息量的说法。
///
/// ⚠️ 必须保留 `_` 兜底分支。
///    契约的 InsufficientReason 是**会增长的枚举**（新增取值属 Minor 变更，
///    已发生一次：1.1.0 从 9 个增到 14 个）。
///    穷尽 switch 会让旧客户端在契约升级后**编译失败** ——
///    这正是 docs/07-数据契约.md 里"新增枚举值需客户端准备 default 分支"
///    所指的情况。
String reasonLabel(InsufficientReason? reason) => switch (reason) {
      InsufficientReason.lowFrameRate => '拍摄帧率不够',
      InsufficientReason.viewMismatch => '该指标需要另一种拍摄方位',
      InsufficientReason.noReferenceScale => '缺少参考尺度',
      InsufficientReason.cameraMotion => '镜头移动导致该指标不可靠',
      InsufficientReason.occlusion => '关键点被遮挡',
      InsufficientReason.missingEvent => '缺少所需的动作事件',
      InsufficientReason.perspectiveError => '运动员偏离画面中心过远',
      InsufficientReason.frameRateUnverified => '帧率无法校验',
      InsufficientReason.insufficientSamples => '完整步次不足',
      InsufficientReason.insufficientCycles => '完整步态周期不足',
      InsufficientReason.noAthleteHeight => '档案里没填身高',
      InsufficientReason.implausibleValue => '推算结果超出合理范围',
      InsufficientReason.contactTimingUnreliable => '触地时刻判定不可靠',
      InsufficientReason.notImplemented => '该指标尚未实现',
      // 兜底分支。既覆盖 null，也覆盖契约将来新增的取值。
      //
      // 为什么不用显式的 `null =>`：Dart 里通配符 `_` 已经包含 null，
      // 再写一条 null 分支会报 unreachable_switch_case。
      //
      // 不给具体说法也不影响可操作性 —— 真正有用的「怎么补」由服务端
      // 在 suggestion 字段里给出，那部分是自由文本，不依赖枚举。
      _ => '该项本次未能测出',
    };

/// 拍摄质量分对应的免责强度。
///
/// 对应 docs/09-报告与指导解析规范.md §6.1。
enum QualityBanner { none, partial, referenceOnly }

QualityBanner qualityBannerFor(double score) {
  if (score >= 75) return QualityBanner.none;
  if (score >= 55) return QualityBanner.partial;
  return QualityBanner.referenceOnly;
}

String qualityBannerText(QualityBanner banner) => switch (banner) {
      QualityBanner.none => '',
      QualityBanner.partial => '本报告部分指标精度受限',
      QualityBanner.referenceOnly => '本报告结论仅供参考，不建议用于训练决策',
    };
