import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/data/video_probe.dart';

/// 视频初级校验的测试。
///
/// ⚠️ 只用 test()，不要加 testWidgets()（原因见 widget_test.dart 顶部说明）。
///
/// 这一层为什么值得测试：它是 App 里**唯一能提前发现帧率问题**的防线。
/// 帧率错一倍，触地时间、腾空时间、步频会静默出错且不报错 ——
/// 所以宁可多拦一道，也不能放过。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  VideoMetadata meta({
    int? durationMs = 10000,
    int? width = 1920,
    int? height = 1080,
    double? frameRate = 240,
    int? frameCount = 2400,
    int rotation = 0,
    bool hasVideo = true,
  }) =>
      VideoMetadata(
        uri: 'content://test/video.mp4',
        durationMs: durationMs,
        width: width,
        height: height,
        rotationDegrees: rotation,
        frameRate: frameRate,
        frameCount: frameCount,
        hasVideoTrack: hasVideo,
      );

  group('硬拦截', () {
    test('没有视频轨直接拦截', () {
      final v = validateVideo(meta(hasVideo: false));
      expect(v.hasBlocking, isTrue);
      expect(v.canProceed, isFalse);
      expect(v.issues.first.title, contains('没有视频画面'));
      // 拦截项必须给出下一步动作
      expect(v.issues.first.suggestion, isNotEmpty);
    });

    test('时长过短拦截并给出建议时长', () {
      final v = validateVideo(meta(durationMs: 1500, frameCount: 360));
      expect(v.hasBlocking, isTrue);
      final issue = v.issues.firstWhere((i) => i.title.contains('太短'));
      expect(issue.suggestion, contains('3'));
    });

    test('时长过长拦截', () {
      final v = validateVideo(meta(durationMs: 90000, frameCount: 21600));
      expect(v.hasBlocking, isTrue);
      expect(v.issues.any((i) => i.title.contains('太长')), isTrue);
    });

    test('分辨率不足拦截', () {
      final v = validateVideo(meta(
        width: 1280,
        height: 720,
        durationMs: 10000,
        frameRate: 60,
        frameCount: 600,
      ));
      expect(v.hasBlocking, isTrue);
      expect(v.issues.any((i) => i.title.contains('分辨率不足')), isTrue);
    });

    test('竖屏视频按短边判定，不会被误拦', () {
      // 1080×1920 是竖屏；短边 1080，应当通过
      final v = validateVideo(meta(width: 1080, height: 1920));
      expect(v.issues.any((i) => i.title.contains('分辨率不足')), isFalse);
    });
  });

  group('帧率判定', () {
    test('240fps：时间类指标可用', () {
      final v = validateVideo(meta(frameRate: 240, frameCount: 2400));
      expect(v.frameRateOk, isTrue);
      expect(v.temporalMetricsUsable, isTrue);
      expect(v.hasWarning, isFalse);
    });

    test('120fps 是门槛，刚好通过', () {
      final v = validateVideo(meta(frameRate: 120, frameCount: 1200));
      expect(v.frameRateOk, isTrue);
      expect(v.temporalMetricsUsable, isTrue);
    });

    test('60fps：不拦截但明确告知时间类指标不可用', () {
      final v = validateVideo(meta(frameRate: 60, frameCount: 600));

      // 不是硬拦截 —— 角度类指标仍然可用，不该剥夺教练用得上的部分
      expect(v.canProceed, isTrue);
      expect(v.hasWarning, isTrue);
      expect(v.frameRateOk, isFalse);
      expect(v.temporalMetricsUsable, isFalse);

      final issue = v.issues.firstWhere((i) => i.title.contains('帧率偏低'));
      // 必须说清「哪些能用、哪些不能用」，而不是简单说「不合格」
      expect(issue.detail, contains('触地时间'));
      expect(issue.detail, contains('角度'));
      expect(issue.suggestion, contains('慢动作'));
    });

    test('读不到帧率：不拦截，但提示可能经过剪辑导出', () {
      final v = validateVideo(meta(frameRate: null, frameCount: null));

      expect(v.canProceed, isTrue);
      expect(v.frameRateOk, isFalse);
      // 读不到就不能承诺时间类指标可用
      expect(v.temporalMetricsUsable, isFalse);

      final issue = v.issues.firstWhere((i) => i.title.contains('无法读取'));
      expect(issue.detail, contains('剪辑'));
    });
  });

  group('帧率自洽性（最能抓到问题的检查）', () {
    test('自洽的数据不报警', () {
      // 240fps × 10 秒 = 2400 帧
      final v = validateVideo(meta(frameRate: 240, frameCount: 2400));
      expect(v.issues.any((i) => i.title.contains('自相矛盾')), isFalse);
    });

    test('声明 30fps 但帧数是 240fps 的量 —— 抓到变速导出', () {
      // 这是真实场景里最危险的坑：
      // 剪辑软件导出的慢动作视频，容器写 30fps，帧数却是 240fps 的量。
      final v = validateVideo(meta(
        frameRate: 30,
        frameCount: 2400,
        durationMs: 10000,
      ));

      final issue = v.issues.firstWhere((i) => i.title.contains('自相矛盾'));
      expect(issue.level, CheckLevel.warning);
      // 必须把矛盾点说清楚：声明什么、推算多少、实际多少
      expect(issue.detail, contains('30'));
      expect(issue.detail, contains('2400'));
      expect(issue.suggestion, contains('不要用剪辑软件'));
    });

    test('自相矛盾时不对时间类指标作承诺', () {
      final v = validateVideo(meta(
        frameRate: 240,
        frameCount: 300, // 240fps × 10s 应有 2400 帧，差得离谱
        durationMs: 10000,
      ));

      expect(v.issues.any((i) => i.title.contains('自相矛盾')), isTrue);
      expect(v.temporalMetricsUsable, isFalse,
          reason: '声明值不可信时，不能承诺时间类指标可用');
    });

    test('偏差在 20% 以内不报警（正常容差）', () {
      // 240fps × 10 秒 = 2400，给 2100（偏差 12.5%）应当放过
      final v = validateVideo(meta(frameRate: 240, frameCount: 2100));
      expect(v.issues.any((i) => i.title.contains('自相矛盾')), isFalse);
    });
  });

  group('元数据展示', () {
    test('未知字段显示为「未知」而不是空白', () {
      final m = meta(
        frameRate: null,
        frameCount: null,
        durationMs: null,
        width: null,
        height: null,
      );
      expect(m.frameRateLabel, '未知');
      expect(m.frameCountLabel, '未知');
      expect(m.durationLabel, '未知');
      expect(m.resolutionLabel, '未知');
    });

    test('时长按量级选择合适的单位', () {
      expect(meta(durationMs: 8000).durationLabel, contains('秒'));
      expect(meta(durationMs: 95000).durationLabel, contains('分'));
    });
  });
}
