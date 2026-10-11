import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/yolo_postprocess.dart';

/// 跨语言对拍：Dart 解析器 vs Python 解析器。
///
/// ## 这个测试在防什么
///
/// 手机端自己实现了「从 YOLO 输出解出关键点」，而电脑上这部分是
/// Ultralytics 做的。两边实现不同，就有**算出不同结果**的风险。
///
/// 后果是：同一个运动员，手机上和电脑上的报告数字不一样，
/// 而且**看不出哪里错了** —— 因为两边都不报错。
///
/// ## 怎么做
///
/// `scripts/gen_pose_fixtures.py` 在电脑上跑一遍，存下：
///   · ONNX 的原始输出（那个 (1,56,8400) 的大数组）
///   · 电脑端算出的关键点（期望值）
///
/// 这个测试读同一份原始输出，用 Dart 解析一遍，比对期望值。
///
/// ## 容差怎么定
///
/// 前处理的插值方式两边可能略有不同（cv2.resize vs Flutter 的实现），
/// 所以坐标不可能**完全**相等。但差异应当在亚像素级。
///
/// 参照项目已有的噪声敏感性数据：3 像素噪声 → 躯干角误差 0.03°。
/// 所以 1 像素以内完全可忽略。
void main() {
  // ⚠️ Flutter 测试的工作目录是 `mobile/`，而对拍样本在**仓库根**的
  //    `samples/pose_fixtures/`。所以要用 `../` 回到上一层。
  //
  //    这与 `samples/fixtures/`（契约样本）不同 —— 那个是被复制进
  //    `mobile/assets/` 的，这里没复制：对拍样本有 1.8 MB × 4，
  //    打包进 APK 是浪费（它们只在测试时用）。
  final fixtureDir = Directory('../samples/pose_fixtures');

  /// 单个关键点允许的最大坐标偏差（原图归一化坐标）。
  ///
  /// 原图 960 像素宽时，0.002 约等于 2 像素。
  const tolX = 0.004;
  const tolY = 0.004;

  test('对拍样本存在', () {
    expect(fixtureDir.existsSync(), isTrue,
        reason: '缺少对拍样本。请先跑：python scripts/gen_pose_fixtures.py');
    final idx = File('${fixtureDir.path}/index.json');
    expect(idx.existsSync(), isTrue);
  });

  test('Dart 解析器与 Python 的结果一致', () {
    final idxFile = File('${fixtureDir.path}/index.json');
    if (!idxFile.existsSync()) {
      markTestSkipped('对拍样本不存在，跳过');
      return;
    }
    final idx = jsonDecode(idxFile.readAsStringSync()) as Map<String, dynamic>;
    final frames = (idx['frames'] as List).cast<int>();
    expect(frames, isNotEmpty, reason: '样本里没有帧');

    var comparedFrames = 0;
    var totalPoints = 0;
    var worstX = 0.0;
    var worstY = 0.0;
    final failures = <String>[];

    for (final fi in frames) {
      final metaFile =
          File('${fixtureDir.path}/frame_${fi.toString().padLeft(4, '0')}.json');
      if (!metaFile.existsSync()) continue;
      final meta =
          jsonDecode(metaFile.readAsStringSync()) as Map<String, dynamic>;

      // ---- 读原始输出 ----
      final binFile =
          File('${fixtureDir.path}/${meta['output_file'] as String}');
      expect(binFile.existsSync(), isTrue,
          reason: '缺少二进制输出 ${binFile.path}');

      final bytes = binFile.readAsBytesSync();
      final raw = Float32List.view(
        bytes.buffer,
        bytes.offsetInBytes,
        bytes.lengthInBytes ~/ 4,
      );

      // ---- 读 letterbox 参数 ----
      final lbJson = meta['letterbox'] as Map<String, dynamic>;
      final lb = Letterbox(
        scale: (lbJson['scale'] as num).toDouble(),
        padX: (lbJson['pad_x'] as num).toDouble(),
        padY: (lbJson['pad_y'] as num).toDouble(),
        inputSize: lbJson['input_size'] as int,
        originalWidth: lbJson['original_width'] as int,
        originalHeight: lbJson['original_height'] as int,
      );

      // ---- Dart 解析 ----
      final cands = parseYoloPose(raw, lb: lb, confThreshold: 0.25);
      if (cands.isEmpty) {
        failures.add('帧$fi: Dart 一个候选都没解出来');
        continue;
      }

      // ⚠️ 这里**必须用和 Python 相同的选人方式**（纯置信度最高），
      //    否则两边可能选中不同的人，对拍会假失败。
      //
      //    而"选人逻辑"本身是另一件事，由 pose_postprocess_test.dart
      //    单独测试。把两件事分开，失败时才能立刻知道是哪一边错了。
      final got = pickPrimary(
        cands,
        weights: const PoseSelectionWeights(area: 0),
      )!;

      // ---- 选人是否一致 ----
      final expBoxConf = (meta['box_confidence'] as num).toDouble();
      if ((got.boxConfidence - expBoxConf).abs() > 0.05) {
        failures.add('帧$fi: 选到的人不同 —— '
            'Dart 框置信度 ${got.boxConfidence.toStringAsFixed(3)}，'
            'Python ${expBoxConf.toStringAsFixed(3)}');
        continue;
      }

      // ---- 逐点比对 ----
      final expected =
          (meta['expected_keypoints'] as List).cast<Map<String, dynamic>>();
      expect(got.keypoints.length, expected.length,
          reason: '帧$fi 关键点数量不同');

      for (var k = 0; k < expected.length; k++) {
        final ex = (expected[k]['x'] as num).toDouble();
        final ey = (expected[k]['y'] as num).toDouble();
        final gx = got.keypoints[k].x;
        final gy = got.keypoints[k].y;

        final dx = (gx - ex).abs();
        final dy = (gy - ey).abs();
        worstX = math.max(worstX, dx);
        worstY = math.max(worstY, dy);
        totalPoints++;

        if (dx > tolX || dy > tolY) {
          final name = expected[k]['name'];
          failures.add('帧$fi 关键点 $name: '
              'Dart(${gx.toStringAsFixed(4)}, ${gy.toStringAsFixed(4)}) vs '
              'Python(${ex.toStringAsFixed(4)}, ${ey.toStringAsFixed(4)})  '
              '差(${dx.toStringAsFixed(4)}, ${dy.toStringAsFixed(4)})');
        }
      }
      comparedFrames++;
    }

    // ---- 结果 ----
    // ignore: avoid_print
    print('  比对 $comparedFrames 帧 / $totalPoints 个关键点');
    // ignore: avoid_print
    print('  最大偏差: x=${worstX.toStringAsFixed(5)}  '
        'y=${worstY.toStringAsFixed(5)}（原图归一化坐标）');
    // ignore: avoid_print
    print('  换算成 960 像素宽的画面: '
        'x=${(worstX * 960).toStringAsFixed(2)} px  '
        'y=${(worstY * 540).toStringAsFixed(2)} px');

    expect(failures, isEmpty,
        reason: 'Dart 与 Python 的解析结果不一致：\n${failures.join('\n')}');
    expect(comparedFrames, greaterThan(0), reason: '没有任何帧比对成功');
  });

  test('解析结果的置信度也与 Python 一致', () {
    final idxFile = File('${fixtureDir.path}/index.json');
    if (!idxFile.existsSync()) {
      markTestSkipped('对拍样本不存在，跳过');
      return;
    }
    final idx = jsonDecode(idxFile.readAsStringSync()) as Map<String, dynamic>;

    for (final fi in (idx['frames'] as List).cast<int>()) {
      final metaFile =
          File('${fixtureDir.path}/frame_${fi.toString().padLeft(4, '0')}.json');
      if (!metaFile.existsSync()) continue;
      final meta =
          jsonDecode(metaFile.readAsStringSync()) as Map<String, dynamic>;

      final binFile =
          File('${fixtureDir.path}/${meta['output_file'] as String}');
      final bytes = binFile.readAsBytesSync();
      final raw = Float32List.view(
          bytes.buffer, bytes.offsetInBytes, bytes.lengthInBytes ~/ 4);

      final lbJson = meta['letterbox'] as Map<String, dynamic>;
      final cands = parseYoloPose(raw, lb: Letterbox(
        scale: (lbJson['scale'] as num).toDouble(),
        padX: (lbJson['pad_x'] as num).toDouble(),
        padY: (lbJson['pad_y'] as num).toDouble(),
        inputSize: lbJson['input_size'] as int,
        originalWidth: lbJson['original_width'] as int,
        originalHeight: lbJson['original_height'] as int,
      ));
      expect(cands, isNotEmpty, reason: '帧$fi 一个候选都没解出来');

      // 和上一个测试一样，用纯置信度选人 —— 与 Python 的选人方式一致
      final got = pickPrimary(
        cands,
        weights: const PoseSelectionWeights(area: 0),
      )!;

      final expected =
          (meta['expected_keypoints'] as List).cast<Map<String, dynamic>>();
      for (var k = 0; k < expected.length; k++) {
        final ec = (expected[k]['confidence'] as num).toDouble();
        // 置信度是网络直接输出的，不经过任何几何变换，
        // 所以容差可以更严
        expect(got.keypoints[k].confidence, closeTo(ec, 1e-4),
            reason: '帧$fi 第 $k 个点的置信度不一致');
      }
    }
  });
}
