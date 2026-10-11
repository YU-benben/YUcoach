import 'dart:io';

import 'package:flutter/services.dart';

/// 视频文件的实际元数据。
///
/// 全部字段都可能为 null —— 不同的容器/编码器提供的信息不一样，
/// 尤其是**帧率与帧数在很多文件里根本不存在**。
/// 缺失时如实标记为「未知」，绝不猜测，也绝不拿容器声称的值当真实值用。
///
/// 为什么这一点如此重要：帧率错一倍，触地时间、腾空时间、步频会静默出错，
/// 而且不会报错。见 docs/02-数据标准.md §8。
class VideoMetadata {
  const VideoMetadata({
    required this.uri,
    this.fileName,
    this.fileSizeBytes,
    this.durationMs,
    this.width,
    this.height,
    this.rotationDegrees = 0,
    this.frameRate,
    this.frameCount,
    this.bitrate,
    this.mimeType,
    this.hasVideoTrack = true,
  });

  final String uri;
  final String? fileName;
  final int? fileSizeBytes;

  final int? durationMs;

  /// 已按旋转角换算过的显示尺寸。
  ///
  /// 原生返回的是**存储方向**下的尺寸：竖屏视频常是 1080×1920 + rotation=90。
  /// 分析时按旋转后的画面处理，所以这里直接给出显示尺寸，
  /// 避免上层每处都要记得换算。
  final int? width;
  final int? height;

  final int rotationDegrees;

  /// 容器声称的帧率。**仅为声明值**，不代表真实时序 ——
  /// 慢动作视频导出后常被写成 30，实际是 240。
  final double? frameRate;

  final int? frameCount;
  final int? bitrate;
  final String? mimeType;
  final bool hasVideoTrack;

  double? get durationSeconds =>
      durationMs == null ? null : durationMs! / 1000.0;

  double? get fileSizeMb =>
      fileSizeBytes == null ? null : fileSizeBytes! / (1024 * 1024);

  int get shortSide {
    final w = width, h = height;
    if (w == null || h == null) return 0;
    return w < h ? w : h;
  }

  String get resolutionLabel =>
      (width == null || height == null) ? '未知' : '$width×$height';

  String get durationLabel {
    final s = durationSeconds;
    if (s == null) return '未知';
    return s < 60
        ? '${s.toStringAsFixed(1)} 秒'
        : '${(s / 60).floor()} 分 ${(s % 60).toStringAsFixed(0)} 秒';
  }

  String get frameRateLabel =>
      frameRate == null ? '未知' : '${frameRate!.toStringAsFixed(1)} fps';

  String get frameCountLabel => frameCount?.toString() ?? '未知';
}

/// 校验结论的严重程度。
///
/// 硬拦截 = 无法分析；软警告 = 能分析但部分指标不可用。
/// 分级的意义在于：不是所有问题都该阻止上传，
/// 但每一条都必须让教练知道后果。
enum CheckLevel { ok, warning, blocking }

class ValidationIssue {
  const ValidationIssue({
    required this.level,
    required this.title,
    required this.detail,
    this.suggestion,
  });

  final CheckLevel level;
  final String title;
  final String detail;

  /// 可操作建议。**必填于 warning 与 blocking** —— 只说"不合格"是没用的，
  /// 教练需要知道下次怎么拍。
  final String? suggestion;
}

class VideoValidation {
  const VideoValidation({required this.issues, required this.metadata});

  final List<ValidationIssue> issues;
  final VideoMetadata metadata;

  bool get hasBlocking =>
      issues.any((i) => i.level == CheckLevel.blocking);
  bool get hasWarning => issues.any((i) => i.level == CheckLevel.warning);

  /// 整体判定：可以作为上传依据
  bool get canProceed => !hasBlocking;

  /// 时间类指标（触地时间、腾空时间、占空比）是否可用。
  ///
  /// 门槛 120 fps —— 短跑单脚触地仅 80–120 ms，低于此值触地期内帧数不足，
  /// 误差超过 30%。这是硬性门槛，不是建议。
  ///
  /// 另外要求帧率**读得到**：读不到就没法判断，只能交给服务端校验，
  /// 此时不能对教练承诺时间类指标可用。
  bool get temporalMetricsUsable {
    final f = metadata.frameRate;
    if (f == null || f < 120) return false;
    // 帧率自相矛盾时同样不承诺 —— 声明值不可信
    return !issues.any((i) => i.title.contains('自相矛盾'));
  }

  /// 声明的帧率是否达到 120 fps 门槛
  bool get frameRateOk {
    final f = metadata.frameRate;
    return f != null && f >= 120;
  }
}

/// 从 content:// URI 读视频元数据（走 Android 原生通道）。
class VideoProbe {
  const VideoProbe();

  static const _channel = MethodChannel('cn.yucoach/video_probe');

  /// 读取元数据。失败时返回错误信息，由界面转成可操作提示。
  Future<VideoMetadata> probe(String uri, {String? fileName}) async {
    if (!Platform.isAndroid) {
      // 桌面端没有这套原生 API。开发期在 Windows 上跑时不应崩溃，
      // 而是明确告知「此平台不支持」。
      throw UnsupportedError(
        '读取视频元数据目前只支持 Android。当前平台：${Platform.operatingSystem}',
      );
    }

    final raw = await _channel.invokeMapMethod<String, dynamic>(
      'probe',
      {'uri': uri},
    );
    if (raw == null) {
      throw StateError('原生侧没有返回任何数据');
    }

    final rotation = (raw['rotation'] as num?)?.toInt() ?? 0;
    var w = (raw['width'] as num?)?.toInt();
    var h = (raw['height'] as num?)?.toInt();

    // 换算成显示尺寸：旋转 90/270 时宽高互换。
    // 不做这一步的话，竖屏视频会被当成横屏，画面比例和后续处理全错。
    if (rotation == 90 || rotation == 270) {
      final t = w;
      w = h;
      h = t;
    }

    return VideoMetadata(
      uri: uri,
      fileName: fileName,
      durationMs: (raw['duration_ms'] as num?)?.toInt(),
      width: w,
      height: h,
      rotationDegrees: rotation,
      frameRate: (raw['frame_rate'] as num?)?.toDouble(),
      frameCount: (raw['frame_count'] as num?)?.toInt(),
      bitrate: (raw['bitrate'] as num?)?.toInt(),
      mimeType: raw['mime_type'] as String?,
      hasVideoTrack: (raw['has_video'] as bool?) ?? true,
    );
  }
}

/// 初级校验。
///
/// **App 端只能做初级校验**：权威的帧率校验需要姿态分析反推步频，
/// 那在服务端。这里能做的是自洽性检查 —— 但它已经能抓到最常见的那个坑：
/// 变速导出的视频，容器帧率与实际帧数对不上。
///
/// 放在 App 端做的意义：让教练在**上传前**就知道素材可疑，
/// 而不是传完几百 MB、等分析跑完才被告知「帧率校验未通过」。
VideoValidation validateVideo(
  VideoMetadata m, {
  int minDurationMs = 3000,
  int maxDurationMs = 60000,
  int minShortSide = 1080,
}) {
  final issues = <ValidationIssue>[];

  // ---- 硬拦截：没有视频轨 ----
  if (!m.hasVideoTrack) {
    issues.add(const ValidationIssue(
      level: CheckLevel.blocking,
      title: '文件里没有视频画面',
      detail: '这个文件不含视频轨，可能是纯音频或已损坏。',
      suggestion: '请重新选择一段视频文件。',
    ));
    return VideoValidation(issues: issues, metadata: m);
  }

  // ---- 硬拦截：时长 ----
  final ms = m.durationMs;
  if (ms == null) {
    issues.add(const ValidationIssue(
      level: CheckLevel.warning,
      title: '读不到视频时长',
      detail: '无法判断素材长度是否合适。',
      suggestion: '可以继续上传，服务端会再校验一次。',
    ));
  } else if (ms < minDurationMs) {
    issues.add(ValidationIssue(
      level: CheckLevel.blocking,
      title: '视频太短',
      detail: '当前 ${m.durationLabel}，至少需要 3 秒才能覆盖一个完整步态循环。',
      suggestion: '短跑分析通常需要 3–15 秒：起跑加前几步，或一段途中跑。',
    ));
  } else if (ms > maxDurationMs) {
    issues.add(ValidationIssue(
      level: CheckLevel.blocking,
      title: '视频太长',
      detail: '当前 ${m.durationLabel}，超过 60 秒。文件太大会让上传很慢。',
      suggestion: '只上传需要分析的那一段（3–15 秒就够）。',
    ));
  }

  // ---- 硬拦截：分辨率 ----
  if (m.shortSide > 0 && m.shortSide < minShortSide) {
    issues.add(ValidationIssue(
      level: CheckLevel.blocking,
      title: '分辨率不足',
      detail: '当前 ${m.resolutionLabel}，短边低于 $minShortSide。'
          '关键点定位精度不够，角度会算不准。',
      suggestion: '用 1080p 或更高分辨率拍摄。',
    ));
  }

  // ---- 帧率 ----
  final fps = m.frameRate;
  if (fps == null) {
    issues.add(const ValidationIssue(
      level: CheckLevel.warning,
      title: '帧率无法读取',
      detail: '文件里没有帧率信息。'
          '这常见于剪辑软件导出的视频 —— 而导出的慢动作视频，'
          '容器帧率往往与实际时序不符。',
      suggestion: '建议用系统相机直接拍、直接传，不要经过剪辑软件导出。',
    ));
  } else if (fps < 120) {
    issues.add(ValidationIssue(
      level: CheckLevel.warning,
      title: '帧率偏低（${m.frameRateLabel}）',
      detail: '低于时间类指标要求的 120 fps。'
          '触地时间、腾空时间、占空比将无法计算。'
          '角度类指标（膝角、躯干前倾等）不受影响。',
      suggestion: '用手机「慢动作」模式录制（120 或 240 fps）。',
    ));
  }

  // ---- 帧率自洽性：这是最能抓到问题的一条 ----
  //
  // 帧数 与 帧率×时长 应当吻合。不吻合说明容器元数据不可信 ——
  // 变速导出的典型症状就是「帧率写 30，帧数却是高帧率的量」。
  final count = m.frameCount;
  if (fps != null && count != null && count > 0 && ms != null && ms > 0) {
    final expected = fps * (ms / 1000.0);
    if (expected > 0) {
      final deviation = (count - expected).abs() / expected;
      if (deviation > 0.20) {
        issues.add(ValidationIssue(
          level: CheckLevel.warning,
          title: '帧率信息自相矛盾',
          detail: '声明 ${m.frameRateLabel}、时长 ${m.durationLabel}，'
              '推算应有 ${expected.round()} 帧，实际 $count 帧'
              '（偏差 ${(deviation * 100).round()}%）。'
              '这说明文件经过变速处理，或容器元数据不可信。',
          suggestion: '用系统相机重新拍摄并直接上传，不要用剪辑软件导出。'
              '若确实需要保留这段素材，分析时将以服务端校验的帧率为准。',
        ));
      }
    }
  }

  return VideoValidation(issues: issues, metadata: m);
}
