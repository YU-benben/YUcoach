import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/capture_quality.dart';
import 'package:yu_coach/pose/pose_types.dart';

/// 拍摄质量检查的测试。
///
/// ## 为什么这组测试重要
///
/// 这个模块的作用是**在分析前拦住不合格的素材**。
/// 判错的后果是不对称的：
///
///   · 该拦没拦 → 用户拿到一份看起来正常、实际不可信的报告
///   · 错拦好素材 → 用户被无故劝退，体验很差
///
/// 所以两个方向的边界都要测。
void main() {
  PoseSequence dummySeq(int n) => PoseSequence(
        frames: List.generate(n, (i) => PoseFrame(frameIndex: i, keypoints: [])),
        sourceWidth: 960,
        sourceHeight: 540,
      );

  group('人物大小', () {
    test('占画面 1/3 以上时通过', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100),
        fps: 120,
        personHeights: List.filled(100, 0.40),
      );
      expect(q.isClean, isTrue);
      expect(q.verdict, '素材符合要求');
    });

    test('实测那种素材（12.6%）判为阻断', () {
      // ⚠️ 这条守着真实发现：
      //    实测素材运动员只占画面高度 12.6%，远低于要求的 33%。
      //    而这一条能解释后面所有指标的精度问题。
      final q = assessCaptureQuality(
        seq: dummySeq(100),
        fps: 30,
        personHeights: List.filled(100, 0.126),
      );
      expect(q.hasBlocking, isTrue);
      expect(q.verdict, contains('建议重拍'));

      final sizeIssue = q.issues.firstWhere((i) => i.title.contains('太小'));
      expect(sizeIssue.level, CaptureIssueLevel.blocking);
      expect(sizeIssue.detail, contains('12.6%'));
      // 建议必须可执行，不能只说"素材不行"
      expect(sizeIssue.suggestion, contains('移近'));
    });

    test('0.15~0.33 之间是警告而不是阻断', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100),
        fps: 120,
        personHeights: List.filled(100, 0.22),
      );
      expect(q.hasBlocking, isFalse, reason: '这个区间还能算，不该拦');
      expect(q.issues.any((i) => i.level == CaptureIssueLevel.warning), isTrue);
      expect(q.verdict, contains('精度会受影响'));
    });

    test('刚好在边界上不报警', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100),
        fps: 120,
        personHeights: List.filled(100, 0.33),
      );
      expect(q.issues.any((i) => i.title.contains('小')), isFalse);
    });

    test('取的是最大高度，不是平均', () {
      // 运动员可能在某些帧更靠近镜头。用最大值判断"素材是否可用"
      // 比用平均更合理 —— 只要有足够大的帧，就说明拍摄距离是够的。
      final heights = List.filled(100, 0.10)..[50] = 0.40;
      final q = assessCaptureQuality(
        seq: dummySeq(100),
        fps: 120,
        personHeights: heights,
      );
      expect(q.maxPersonHeightFraction, closeTo(0.40, 1e-9));
      expect(q.issues.any((i) => i.title.contains('太小')), isFalse);
    });
  });

  group('帧率', () {
    test('120 fps 通过', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 120,
        personHeights: List.filled(100, 0.40));
      expect(q.issues.any((i) => i.title.contains('帧率')), isFalse);
    });

    test('30 fps 是阻断（连角度都偏低）', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 30,
        personHeights: List.filled(100, 0.40));
      final f = q.issues.firstWhere((i) => i.title.contains('帧率'));
      expect(f.level, CaptureIssueLevel.blocking);
      expect(f.suggestion, contains('慢动作'));
    });

    test('60 fps 是警告（角度够、时序不够）', () {
      // 这个区分很重要：只说"帧率低"用户不知道该不该重拍。
      // 说清"角度能算、时序不能"他才能判断。
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 60,
        personHeights: List.filled(100, 0.40));
      final f = q.issues.firstWhere((i) => i.title.contains('帧率'));
      expect(f.level, CaptureIssueLevel.warning);
      expect(f.detail, contains('角度'));
    });

    test('帧率未知时给出提示而不是假装通过', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: null,
        personHeights: List.filled(100, 0.40));
      expect(q.issues.any((i) => i.title.contains('没有读到帧率')), isTrue);
      expect(q.isClean, isFalse, reason: '未知不等于合格');
    });
  });

  group('检出率与画面人数', () {
    test('检出率过低判为阻断', () {
      // 只有 30% 的帧有人的话，事件检测无从谈起
      final heights = <double>[
        ...List.filled(30, 0.40),
        ...List.filled(70, 0.0),
      ];
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 120, personHeights: heights);
      expect(q.hasBlocking, isTrue);
      expect(q.detectionRate, closeTo(0.30, 1e-9));
      expect(q.issues.any((i) => i.title.contains('没检出人')), isTrue);
    });

    test('画面里人太多给出警告与建议', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 120,
        personHeights: List.filled(100, 0.40),
        ambiguousFrames: 80,   // 80% 的帧有歧义
      );
      final i = q.issues.firstWhere((x) => x.title.contains('人比较多'));
      expect(i.level, CaptureIssueLevel.warning);
      expect(i.suggestion, contains('避开'));
    });

    test('歧义比例不高时不报警', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 120,
        personHeights: List.filled(100, 0.40),
        ambiguousFrames: 10,
      );
      expect(q.issues.any((i) => i.title.contains('人比较多')), isFalse);
    });
  });

  group('组合与边界', () {
    test('多个问题同时存在时全部列出', () {
      // 实测素材就是这个情况：人小 + 帧率低
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 30,
        personHeights: List.filled(100, 0.126),
      );
      expect(q.issues.length, greaterThanOrEqualTo(2),
          reason: '人太小和帧率过低应当都报出来');
      expect(q.hasBlocking, isTrue);
    });

    test('空序列不崩', () {
      final q = assessCaptureQuality(
        seq: dummySeq(0), fps: 120, personHeights: []);
      expect(q.totalFrames, 0);
      expect(q.detectionRate, 0);
      expect(() => q.verdict, returnsNormally);
    });

    test('全部帧都没检出人时明确说明', () {
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 120, personHeights: List.filled(100, 0.0));
      expect(q.hasBlocking, isTrue);
      expect(q.framesWithPerson, 0);
    });

    test('verdict 的优先级：阻断 > 警告 > 通过', () {
      final blocking = assessCaptureQuality(
        seq: dummySeq(100), fps: 30,
        personHeights: List.filled(100, 0.10));
      expect(blocking.verdict, contains('重拍'));

      final warn = assessCaptureQuality(
        seq: dummySeq(100), fps: 60,
        personHeights: List.filled(100, 0.40));
      expect(warn.verdict, contains('精度'));

      final clean = assessCaptureQuality(
        seq: dummySeq(100), fps: 120,
        personHeights: List.filled(100, 0.40));
      expect(clean.verdict, contains('符合要求'));
    });

    test('每条问题都必须有可执行的建议', () {
      // 只说"素材不合格"对用户没有帮助。这条测试守住这个要求。
      final q = assessCaptureQuality(
        seq: dummySeq(100), fps: 30,
        personHeights: List.filled(100, 0.10),
        ambiguousFrames: 80,
      );
      expect(q.issues, isNotEmpty);
      for (final i in q.issues) {
        expect(i.suggestion.trim(), isNotEmpty,
            reason: '「${i.title}」没有给建议');
        expect(i.detail.trim(), isNotEmpty,
            reason: '「${i.title}」没有说明原因');
        // 建议不能是空话
        expect(i.suggestion.length, greaterThan(8),
            reason: '「${i.title}」的建议太短，大概是空话');
      }
    });

    test('expectedFrames 能覆盖实际帧数（用于计算检出率）', () {
      // 手机端可能只对部分帧做了推理，但检出率要按**视频总帧数**算，
      // 否则"只推理了 10 帧、全部检出"会被误判为 100% 检出率。
      final q = assessCaptureQuality(
        seq: dummySeq(10), fps: 120,
        personHeights: List.filled(10, 0.40),
        expectedFrames: 100,
      );
      expect(q.detectionRate, closeTo(0.10, 1e-9));
      expect(q.hasBlocking, isTrue, reason: '只推理了 10% 的帧，应当报警');
    });
  });
}
