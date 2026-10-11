import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/gait_events.dart';
import 'package:yu_coach/pose/pose_types.dart';
import 'package:yu_coach/pose/yolo_postprocess.dart';

/// 用**真实素材**走一遍手机端的完整链路。
///
/// ## 为什么要有这个测试
///
/// 前面那些测试用的是人造的周期信号。人造信号规整、无噪声，
/// 通过它们不能说明在真实素材上也能工作。
///
/// 这个测试用真实视频帧的 ONNX 输出，跑：
///     解析关键点 → 构造姿态序列 → 检测事件 → 划分相位
///
/// 每一步都会打印实际情况，而不是只断言"不崩"。
///
/// ⚠️ 已知前提：这份素材是 **30 fps**，而触地时间只有 80~120 毫秒。
///    所以**事件检测本身在这份素材上不可靠** —— 这是素材的限制，
///    换成 120 fps 才能解决。这个测试的价值是**验证链路能跑通**，
///    而不是验证精度。
void main() {
  final dir = Directory('../samples/pose_fixtures');

  test('真实素材：解析 → 事件 → 相位 全链路', () {
    if (!dir.existsSync()) {
      markTestSkipped('缺少对拍样本，跳过');
      return;
    }

    final idx =
        jsonDecode(File('${dir.path}/index.json').readAsStringSync())
            as Map<String, dynamic>;
    final frames = (idx['frames'] as List).cast<int>();

    // ---- 逐帧解析 ----
    final poses = <PoseFrame>[];
    var ambiguousFrames = 0;
    final peopleCounts = <int>[];
    final selections = <PoseSelection>[];
    final diag = <String>[];

    for (final fi in frames) {
      final f = File('${dir.path}/frame_${fi.toString().padLeft(4, '0')}.json');
      if (!f.existsSync()) continue;
      final meta = jsonDecode(f.readAsStringSync()) as Map<String, dynamic>;

      final bytes =
          File('${dir.path}/${meta['output_file']}').readAsBytesSync();
      final raw = Float32List.view(
          bytes.buffer, bytes.offsetInBytes, bytes.lengthInBytes ~/ 4);

      final lbJson = meta['letterbox'] as Map<String, dynamic>;
      final lb = Letterbox(
        scale: (lbJson['scale'] as num).toDouble(),
        padX: (lbJson['pad_x'] as num).toDouble(),
        padY: (lbJson['pad_y'] as num).toDouble(),
        inputSize: lbJson['input_size'] as int,
        originalWidth: lbJson['original_width'] as int,
        originalHeight: lbJson['original_height'] as int,
      );

      final cands = parseYoloPose(raw, lb: lb);
      peopleCounts.add(cands.length);

      final sel = selectPerson(cands);
      if (sel.isAmbiguous) ambiguousFrames++;
      selections.add(sel);

      final c = sel.primary;
      if (c != null) {
        poses.add(toPoseFrame(c, fi));

        // 诊断：看看"框面积"到底有没有区分度
        final byScore = List<PoseCandidate>.from(cands)
          ..sort((a, b) =>
              const PoseSelectionWeights().score(b).compareTo(
                  const PoseSelectionWeights().score(a)));
        diag.add('帧$fi 检出 ${cands.length} 人，前三名：');
        for (var i = 0; i < byScore.length && i < 3; i++) {
          final x = byScore[i];
          final af = x.areaFraction;
          diag.add('    #${i + 1} 置信度=${x.boxConfidence.toStringAsFixed(2)} '
              '框=${x.w.toStringAsFixed(1)}×${x.h.toStringAsFixed(1)}px '
              '占画面=${af == null ? "?" : "${(af * 100).toStringAsFixed(2)}%"}');
        }
        final fracs = cands
            .map((x) => x.areaFraction ?? 0)
            .toList()
          ..sort();
        diag.add('    占画面面积范围: '
            '${(fracs.first * 100).toStringAsFixed(2)}% ~ '
            '${(fracs.last * 100).toStringAsFixed(2)}%');
        // 拍摄标准的门槛：运动员应占画面高度 1/3 以上。
        // 这里用面积近似判断，1/3 高度约等于 11% 面积（宽度按 1/3 算）。
        final maxFrac = fracs.last;
        if (maxFrac > 0 && maxFrac < 0.05) {
          diag.add('    ⚠️ 最大的框只占画面 ${(maxFrac * 100).toStringAsFixed(1)}% '
              '—— 远低于拍摄标准（运动员应占画面高度的 1/3 以上，'
              '对应面积约 11%）');
        }
      }
    }

    // ignore: avoid_print
    print('  解析出 ${poses.length} 帧姿态');
    // ignore: avoid_print
    print('  每帧候选人数: $peopleCounts');
    // ignore: avoid_print
    print('  有选人歧义的帧: $ambiguousFrames / ${frames.length}');
    for (final s in selections) {
      // ignore: avoid_print
      print('    · ${s.reason}');
    }
    // ignore: avoid_print
    print('  框面积诊断：');
    for (final d in diag) {
      // ignore: avoid_print
      print('  $d');
    }

    expect(poses, isNotEmpty, reason: '一帧都没解析出来');

    // ---- 覆盖率 ----
    final seq = PoseSequence(
      frames: poses,
      sourceWidth: 960,
      sourceHeight: 540,
    );
    final cov = seq.coverageByKeypoint();
    // ignore: avoid_print
    print('  关键点可见率（部分）:');
    for (final name in ['nose', 'shoulder_l', 'hip_l', 'knee_r', 'ankle_l']) {
      // ignore: avoid_print
      print('    $name: ${((cov[name] ?? 0) * 100).toStringAsFixed(0)}%');
    }

    // ---- 事件检测 ----
    // 采样帧间隔不均匀，这里按"帧号差"估算等效帧率。
    // 真实场景下帧是连续的，这里只是为了让链路能跑。
    final span = poses.last.frameIndex - poses.first.frameIndex;
    final fps = span > 0 ? poses.length / (span / 30.0) : 30.0;
    // ignore: avoid_print
    print('  采样等效帧率: ${fps.toStringAsFixed(1)} fps');

    final ev = detectGaitEvents(seq, fps: 30);
    // ignore: avoid_print
    print('  事件检测: $ev');
    // ignore: avoid_print
    print('  可靠性: ${ev.reliability}');
    for (final n in ev.notes) {
      // ignore: avoid_print
      print('    · $n');
    }

    // ---- 相位 ----
    final ph = detectPhases(seq, fps: 30, events: ev);
    // ignore: avoid_print
    print('  相位: ${ph.length} 段');
    for (final p in ph) {
      // ignore: avoid_print
      print('    ${PhaseName.zh(p.phase)}: 帧 ${p.fromFrame}-${p.toFrame} '
          '(conf=${p.confidence})');
    }

    // ---- 断言：链路必须能跑完，不崩 ----
    // 不断言"检出多少事件" —— 这份素材只有采样帧，检出多少都可能。
    expect(() => detectGaitEvents(seq, fps: 30), returnsNormally);
    expect(() => detectPhases(seq, fps: 30, events: ev), returnsNormally);
  });
}
