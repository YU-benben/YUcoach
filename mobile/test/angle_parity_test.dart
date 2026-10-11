import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/angle_catalog.dart';
import 'package:yu_coach/pose/foot_derivation.dart';
import 'package:yu_coach/pose/pose_types.dart';

/// 角度计算的跨语言对拍。
///
/// ## 这个测试在解决一个真实的张力
///
/// 项目原则：**指标算法只有一份**（在电脑端），避免两套实现漂移。
/// 但手机端要画角度弧，就必须自己算角度。
///
/// 解决办法是划清界限 + 用对拍钉住：
///
/// ```
/// 手机端算的角度  →  只用于【画弧】。报告数值仍以电脑端为准。
/// 这个测试        →  保证两边算出来的是同一个数。
/// ```
///
/// 只要对拍通过，就可以说"手机上看到的角度和报告里的数值一致"。
/// 一旦哪天有人改动了一边的公式，这里会立刻失败。
void main() {
  final file = File('../samples/angle_fixtures/angles.json');

  /// 角度容差。
  ///
  /// 两侧实现是逐字对应的公式，理论上应当完全相等。
  /// 但浮点运算顺序可能有细微差别（Dart 的 `math.pow` vs Python 的 `**`），
  /// 所以给一个极小容差。
  ///
  /// ⚠️ 不要放宽这个值。放宽到 0.1 的话，
  ///    "公式写错了"和"浮点尾差"就分不出来了。
  const tol = 1e-9;

  Map<String, dynamic>? load() {
    if (!file.existsSync()) return null;
    return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  }

  test('对拍样本存在', () {
    expect(file.existsSync(), isTrue,
        reason: '缺少角度对拍样本。请先跑：'
            'python scripts/pose/gen_angle_fixtures.py');
  });

  test('Dart 与 Python 的角度计算一致', () {
    final doc = load();
    if (doc == null) {
      markTestSkipped('样本不存在，跳过');
      return;
    }

    final samples = (doc['samples'] as List).cast<Map<String, dynamic>>();
    expect(samples, isNotEmpty);

    final failures = <String>[];
    var compared = 0;
    var maxDiff = 0.0;
    final perAngle = <String, double>{};

    for (final s in samples) {
      final fi = s['frame_index'] as int;

      // ---- 重建姿态 ----
      final kpMap =
          (s['keypoints'] as Map).cast<String, dynamic>();
      final kps = List.generate(cocoNames.length, (i) {
        final raw = kpMap[cocoNames[i]] as List?;
        if (raw == null) {
          return const Keypoint(x: 0, y: 0, confidence: 0);
        }
        return Keypoint(
          x: (raw[0] as num).toDouble(),
          y: (raw[1] as num).toDouble(),
          confidence: (raw[2] as num).toDouble(),
        );
      });
      final frame = PoseFrame(frameIndex: fi, keypoints: kps);

      // ---- 推导足部点 ----
      //
      // 这一步也要对拍 —— 足部点的公式在两边各写了一遍，
      // 参数不一致的话，用到脚尖的踝角就会对不上。
      final derived = deriveFrame(frame);
      final expectedDerived =
          (s['derived'] as Map).cast<String, dynamic>();

      for (final name in ['heel_l', 'toe_l', 'heel_r', 'toe_r']) {
        final exp = expectedDerived[name] as List?;
        final got = derived.byName(name);
        if (exp == null) {
          expect(got, isNull,
              reason: '帧$fi $name：Python 推不出来，Dart 却推出来了');
          continue;
        }
        expect(got, isNotNull, reason: '帧$fi $name：Dart 没推出来');
        final dx = (got!.x - (exp[0] as num).toDouble()).abs();
        final dy = (got.y - (exp[1] as num).toDouble()).abs();
        if (dx > 1e-6 || dy > 1e-6) {
          failures.add('帧$fi $name 推导不一致：'
              'Dart(${got.x}, ${got.y}) vs '
              'Python(${exp[0]}, ${exp[1]})');
        }
      }

      // ---- 逐角度比对 ----
      final expected =
          (s['angles'] as Map).cast<String, dynamic>();
      for (final entry in expected.entries) {
        final mid = entry.key;
        final expVal = entry.value;

        final def = angleById(mid);
        if (def == null) {
          failures.add('帧$fi：Dart 的目录里没有 $mid —— '
              '两边的角度清单不一致');
          continue;
        }

        final gotVal = computeAngle(def, derived);

        if (expVal == null) {
          // Python 算不出来（点不可见）。Dart 也应当算不出来。
          if (gotVal != null) {
            failures.add('帧$fi $mid：Python 算不出，Dart 却得到 '
                '${gotVal.toStringAsFixed(3)}');
          }
          continue;
        }

        if (gotVal == null) {
          failures.add('帧$fi $mid：Dart 算不出，Python 得到 $expVal');
          continue;
        }

        final diff = (gotVal - (expVal as num).toDouble()).abs();
        maxDiff = diff > maxDiff ? diff : maxDiff;
        final prev = perAngle[mid];
        if (prev == null || diff > prev) {
          perAngle[mid] = diff;
        }
        compared++;

        if (diff > tol) {
          failures.add('帧$fi $mid：'
              'Dart ${gotVal.toStringAsFixed(6)} vs '
              'Python ${(expVal).toStringAsFixed(6)}  '
              '差 ${diff.toStringAsExponential(2)}');
        }
      }
    }

    // ignore: avoid_print
    print('  比对 $compared 个角度值，最大差 ${maxDiff.toStringAsExponential(2)}');
    for (final e in perAngle.entries) {
      // ignore: avoid_print
      print('    ${e.key.padRight(24)} ${e.value.toStringAsExponential(2)}');
    }

    expect(failures, isEmpty,
        reason: 'Dart 与 Python 的角度计算不一致：\n${failures.join('\n')}');
    expect(compared, greaterThan(0), reason: '没有任何角度比对成功');
  });

  test('足部推导参数与电脑端一致', () {
    // ⚠️ 这条守着真实犯过的错：
    //    `heelBelowAnkleRatio` 我凭记忆写成 0.08，电脑端是 0.20。
    //    后果是脚跟的 y 差了 0.0037 —— 而**角度全对**，
    //    所以只看角度根本发现不了。
    //
    //    这条测试把参数值写死在这里，谁改了一边而没改另一边就会失败。
    //
    //    这些值来自 backend/analysis/keypoint_map.py:75-78。
    expect(FootConstants.footLengthRatio, 0.152);
    expect(FootConstants.toeAheadAnkleRatio, 0.75);
    expect(FootConstants.heelBehindAnkleRatio, 0.25);
    expect(FootConstants.heelBelowAnkleRatio, 0.20,
        reason: '电脑端 keypoint_map.py 的值是 0.20 —— '
            '曾经错写成 0.08，导致脚跟位置偏移');
  });

  test('两边的角度清单一致（数量与 id）', () {
    final doc = load();
    if (doc == null) {
      markTestSkipped('样本不存在，跳过');
      return;
    }

    // ⚠️ 这条守着"清单漂移"：
    //    如果谁在电脑端加了一个角度而忘了在手机端加，
    //    对拍会只覆盖一部分 —— 而没覆盖到的那条恰恰最可能出错。
    final pythonIds = (doc['angles'] as List)
        .map((e) => (e as Map)['metric_id'] as String)
        .toSet();
    final dartIds = angleCatalog.map((a) => a.metricId).toSet();

    final onlyPython = pythonIds.difference(dartIds);
    final onlyDart = dartIds.difference(pythonIds);

    expect(onlyPython, isEmpty,
        reason: '电脑端有但手机端没有的角度：$onlyPython');
    expect(onlyDart, isEmpty,
        reason: '手机端有但电脑端没有的角度：$onlyDart');
  });

  test('每个角度的定义（kind / points / vertex）两边一致', () {
    final doc = load();
    if (doc == null) {
      markTestSkipped('样本不存在，跳过');
      return;
    }

    for (final raw in (doc['angles'] as List).cast<Map<String, dynamic>>()) {
      final mid = raw['metric_id'] as String;
      final def = angleById(mid);
      expect(def, isNotNull, reason: '手机端缺少 $mid');

      final pyKind = raw['kind'] as String;
      final dartKind =
          def!.kind == AngleKind.threePoint ? 'three' : 'segment';
      expect(dartKind, pyKind, reason: '$mid 的 kind 不一致');

      final pyPoints = (raw['points'] as List).cast<String>();
      expect(def.points, pyPoints, reason: '$mid 的点列表不一致');

      expect(def.vertexIndex, raw['vertex_index'] as int,
          reason: '$mid 的顶点下标不一致');
    }
  });
}
