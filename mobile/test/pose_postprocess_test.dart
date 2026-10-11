import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:yu_coach/pose/pose_types.dart';
import 'package:yu_coach/pose/yolo_postprocess.dart';

/// 手机端姿态解析的测试。
///
/// ## 为什么这一组测试特别重要
///
/// 这段代码错了**不会报错**，只会让关键点悄悄偏一点：
///   · letterbox 填充漏掉 → 所有点整体偏移，看起来"模型不准"
///   · 通道布局搞错 → 解析出一堆垃圾，但形状仍然对
///   · 关键点顺序错位 → 关节对错位置，而**人体左右对称会让它看起来正常**
///
/// 所以每一种错法都要有测试守住。
void main() {
  // -------------------------------------------------------------------------
  group('letterbox', () {
    test('宽图（16:9）在上下填充', () {
      // 1920x1080 缩到 640：按宽算比例 = 640/1920 = 0.3333
      // 高度变成 1080 * 0.3333 = 360，上下各填 (640-360)/2 = 140
      final lb = computeLetterbox(1920, 1080, 640);
      expect(lb.scale, closeTo(640 / 1920, 1e-9));
      expect(lb.padX, closeTo(0, 1e-6), reason: '宽度方向不需要填充');
      expect(lb.padY, closeTo(140, 1e-6));
    });

    test('高图（竖屏）在左右填充', () {
      final lb = computeLetterbox(1080, 1920, 640);
      expect(lb.scale, closeTo(640 / 1920, 1e-9));
      expect(lb.padX, closeTo(140, 1e-6));
      expect(lb.padY, closeTo(0, 1e-6));
    });

    test('正方形图不填充', () {
      final lb = computeLetterbox(640, 640, 640);
      expect(lb.scale, closeTo(1.0, 1e-9));
      expect(lb.padX, closeTo(0, 1e-6));
      expect(lb.padY, closeTo(0, 1e-6));
    });

    test('坐标往返一致：原图 → 网络输入 → 原图', () {
      // 这是最关键的性质。算错了这个，所有关键点都会偏。
      //
      // ⚠️ 注意坐标的**量纲**：网络输出的是 0~inputSize 的**像素**值，
      //    不是 0~1 归一化值。第一版这里假设错了，结果整张图偏了 640 倍。
      //    往返测试**必须按真实量纲来构造**，否则它会跟着代码一起错 ——
      //    事实上第一版就是这样：往返测试通过了，但和 Python 对不上。
      const w = 1920, h = 1080, size = 640;
      final lb = computeLetterbox(w, h, size);

      for (final (ox, oy) in [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0),
                              (0.25, 0.75), (0.9, 0.1)]) {
        // 正向：原图归一化 → 网络输入像素
        final px = ox * w;
        final py = oy * h;
        final inX = px * lb.scale + lb.padX;
        final inY = py * lb.scale + lb.padY;

        // 反向：用被测函数映射回来
        expect(lb.toOriginalX(inX), closeTo(ox, 1e-9),
            reason: 'x 往返不一致，原图归一化 $ox');
        expect(lb.toOriginalY(inY), closeTo(oy, 1e-9),
            reason: 'y 往返不一致，原图归一化 $oy');
      }
    });

    test('中心点映射后仍在中心（无论怎么填充）', () {
      // 一个容易忽略的性质：填充是对称的，所以画面中心必须映射到中心。
      // 如果填充算错（比如只填一侧），这个测试会失败。
      for (final (w, h) in [(1920, 1080), (1080, 1920), (800, 600)]) {
        final lb = computeLetterbox(w, h, 640);
        final inX = 0.5 * w * lb.scale + lb.padX;
        final inY = 0.5 * h * lb.scale + lb.padY;
        expect(lb.toOriginalX(inX), closeTo(0.5, 1e-9),
            reason: '${w}x$h 的中心未映射到中心');
        expect(lb.toOriginalY(inY), closeTo(0.5, 1e-9),
            reason: '${w}x$h 的中心未映射到中心');
      }
    });

    test('量纲是像素：输入边长 640 时，输出值应当在 0~640 范围', () {
      // ⚠️ 这条守着那个"偏 640 倍"的错误。
      //    如果哪天有人改回"乘以 inputSize"，这里会立刻失败。
      const w = 960, h = 540, size = 640;
      final lb = computeLetterbox(w, h, size);

      // 原图右下角 → 网络输入里的像素位置
      final inX = w * lb.scale + lb.padX;
      final inY = h * lb.scale + lb.padY;
      expect(inX, closeTo(640, 1e-6),
          reason: '原图最右侧应当映射到输入的最右侧（像素 640）');
      expect(inY, closeTo(500, 1e-6),
          reason: '540 高按 0.6667 缩放后是 360，加上 140 的填充 = 500');

      // 映射回来必须是 1.0（原图右下角）
      expect(lb.toOriginalX(640), closeTo(1.0, 1e-9));
      expect(lb.toOriginalY(500), closeTo(1.0, 1e-9));
    });
  });

  // -------------------------------------------------------------------------
  group('YOLO 输出解析', () {
    /// 造一个假的 YOLO 输出：只放一个候选，其余全是 0。
    ///
    /// 用真值构造，才能验证"解析出来的东西就是放进去的东西"。
    Float32List makeOutput({
      required int n,
      required int keypointCount,
      required int atIndex,
      required double conf,
      required List<(double, double, double)> kps,
      double cx = 0.5,
      double cy = 0.5,
      double w = 0.3,
      double h = 0.4,
    }) {
      final channels = YoloPoseLayout.channels(keypointCount);
      final out = Float32List(channels * n);
      out[0 * n + atIndex] = cx;
      out[1 * n + atIndex] = cy;
      out[2 * n + atIndex] = w;
      out[3 * n + atIndex] = h;
      out[4 * n + atIndex] = conf;
      for (var k = 0; k < keypointCount; k++) {
        final base = YoloPoseLayout.keypointStart + k * 3;
        out[(base + 0) * n + atIndex] = kps[k].$1;
        out[(base + 1) * n + atIndex] = kps[k].$2;
        out[(base + 2) * n + atIndex] = kps[k].$3;
      }
      return out;
    }

    test('能解出唯一候选的 17 个关键点', () {
      // ⚠️ 坐标是**像素**量纲（0~640），不是归一化值。
      const size = 640.0;
      final kps = List.generate(17, (i) => (192.0 + i * 8.0, 256.0, 0.9));
      final out = makeOutput(
          n: 100, keypointCount: 17, atIndex: 7, conf: 0.8, kps: kps);
      final lb = computeLetterbox(640, 640, 640);

      final got = parseYoloPose(out, lb: lb);
      expect(got.length, 1);
      expect(got.first.keypoints.length, 17);
      expect(got.first.boxConfidence, closeTo(0.8, 1e-6));
      // 640x640 不填充不缩放：像素 192 → 归一化 192/640 = 0.3
      expect(got.first.keypoints[0].x, closeTo(192.0 / size, 1e-6));
      expect(got.first.keypoints[16].x,
          closeTo((192.0 + 16 * 8.0) / size, 1e-6));
      expect(got.first.keypoints[0].y, closeTo(256.0 / size, 1e-6));
    });

    test('低于阈值的候选被丢弃', () {
      final kps = List.generate(17, (_) => (320.0, 320.0, 0.9));
      final out = makeOutput(
          n: 50, keypointCount: 17, atIndex: 3, conf: 0.10, kps: kps);
      final lb = computeLetterbox(640, 640, 640);
      expect(parseYoloPose(out, lb: lb), isEmpty,
          reason: '置信度 0.10 低于默认阈值 0.25，应当被丢掉');
    });

    test('按置信度从高到低排序', () {
      const n = 20;
      const kpc = 17;
      final channels = YoloPoseLayout.channels(kpc);
      final out = Float32List(channels * n);
      final kps = List.generate(kpc, (_) => (320.0, 320.0, 0.9));
      // 放三个候选：0.3 / 0.9 / 0.6
      for (final (idx, conf) in [(2, 0.3), (5, 0.9), (9, 0.6)]) {
        out[4 * n + idx] = conf;
        for (var k = 0; k < kpc; k++) {
          final base = YoloPoseLayout.keypointStart + k * 3;
          out[(base + 0) * n + idx] = kps[k].$1;
          out[(base + 1) * n + idx] = kps[k].$2;
          out[(base + 2) * n + idx] = kps[k].$3;
        }
      }
      final lb = computeLetterbox(640, 640, 640);
      final got = parseYoloPose(out, lb: lb);
      expect(got.length, 3);
      expect(got[0].boxConfidence, closeTo(0.9, 1e-6));
      expect(got[1].boxConfidence, closeTo(0.6, 1e-6));
      expect(got[2].boxConfidence, closeTo(0.3, 1e-6));
    });

    test('通道数是 56，布局是 [通道][候选] 而不是 [候选][通道]', () {
      // ⚠️ 这条守着最常见的错法。
      //    如果按 [候选][通道] 布局去解析，形状仍然"看起来对"，
      //    但每个数字都是错的，而且不会抛异常。
      expect(YoloPoseLayout.channels(17), 56);
      expect(YoloPoseLayout.confidenceIndex, 4);
      expect(YoloPoseLayout.keypointStart, 5);

      // 造一个 n=2 的输出，在第 0 个候选和第 1 个候选放不同值
      const n = 2, kpc = 17;
      final channels = YoloPoseLayout.channels(kpc);
      final out = Float32List(channels * n);
      out[4 * n + 0] = 0.9; // 候选 0 的置信度
      out[4 * n + 1] = 0.7; // 候选 1 的置信度
      for (var k = 0; k < kpc; k++) {
        final base = YoloPoseLayout.keypointStart + k * 3;
        out[(base + 0) * n + 0] = 64.0; // 候选 0 的 x（像素）
        out[(base + 0) * n + 1] = 512.0; // 候选 1 的 x
        out[(base + 1) * n + 0] = 128.0;
        out[(base + 1) * n + 1] = 576.0;
        out[(base + 2) * n + 0] = 0.9;
        out[(base + 2) * n + 1] = 0.9;
      }
      final lb = computeLetterbox(640, 640, 640);
      final got = parseYoloPose(out, lb: lb);
      expect(got[0].boxConfidence, closeTo(0.9, 1e-6));
      expect(got[0].keypoints[0].x, closeTo(0.1, 1e-6),
          reason: '候选 0 的关键点被读成了候选 1 的 —— 布局搞反了');
      expect(got[1].keypoints[0].x, closeTo(0.8, 1e-6));
    });

    test('输出长度不是通道数整数倍时抛异常，而不是静默出错', () {
      final bad = Float32List(100); // 100 不是 56 的倍数
      final lb = computeLetterbox(640, 640, 640);
      expect(() => parseYoloPose(bad, lb: lb), throwsArgumentError);
    });

    test('坐标会经过 letterbox 反映射', () {
      // 1920x1080 的图：scale=0.3333，上下各填 140
      // 原图中心的网络输入坐标 = (960*0.3333, 540*0.3333+140) = (320, 320)
      final kps = List.generate(17, (_) => (320.0, 320.0, 0.9));
      final out = makeOutput(
          n: 10, keypointCount: 17, atIndex: 1, conf: 0.9, kps: kps);
      final lb = computeLetterbox(1920, 1080, 640);
      final got = parseYoloPose(out, lb: lb);
      expect(got.first.keypoints[0].x, closeTo(0.5, 1e-6));
      expect(got.first.keypoints[0].y, closeTo(0.5, 1e-6));
    });

    test('填充区域的点映射回来是负数，说明它在画面外', () {
      // 这是个**有意的性质**，不是 bug：
      // letterbox 填充区里的坐标映射回原图就是负的（或不合理的大）。
      // 上层据此判断"这个点不可信"。
      //
      // 1920x1080 的图上下各填 140 像素。y=10 落在上填充区里。
      final kps = List.generate(17, (_) => (320.0, 10.0, 0.9));
      final out = makeOutput(
          n: 10, keypointCount: 17, atIndex: 1, conf: 0.9, kps: kps);
      final lb = computeLetterbox(1920, 1080, 640);
      final got = parseYoloPose(out, lb: lb);
      expect(got.first.keypoints[0].y, lessThan(0.0),
          reason: '上填充区里的点，y 映射回来应当是负数');
    });
  });

  // -------------------------------------------------------------------------
  group('选人', () {
    /// 造一个候选。area 由 w×h 决定。
    PoseCandidate cand(double conf, double w, double h,
            {List<Keypoint>? kps}) =>
        PoseCandidate(
          boxConfidence: conf,
          cx: 0.5, cy: 0.5, w: w, h: h,
          keypoints: kps ?? [],
        );

    test('没有候选时返回 null', () {
      expect(pickPrimary([]), isNull);
      final sel = selectPerson([]);
      expect(sel.ok, isFalse);
      expect(sel.reason, contains('没有检出'));
    });

    test('只有一个候选时直接用它，不算歧义', () {
      final c = cand(0.9, 0.1, 0.1);
      expect(pickPrimary([c]), same(c));
      final sel = selectPerson([c]);
      expect(sel.isAmbiguous, isFalse);
      expect(sel.candidateCount, 1);
      expect(sel.reason, contains('只有一个人'));
    });

    test('⚠️ 面积大的胜出，即使置信度略低', () {
      // 这是核心行为，也是实测逼出来的：
      //   操场素材一帧检出 21 个人，背景的人置信度可能更高。
      //   而拍摄标准要求运动员占画面 1/3 以上 —— 框最大的才是他。
      final small = cand(0.85, 0.05, 0.08);  // 远处的人
      final big = cand(0.70, 0.30, 0.50);    // 运动员（占画面大）

      final got = pickPrimary([small, big]);
      expect(got, same(big),
          reason: '面积权重更高，占画面大的应当胜出');
    });

    test('面积相同时置信度高的胜出', () {
      final a = cand(0.6, 0.2, 0.3);
      final b = cand(0.9, 0.2, 0.3);
      expect(pickPrimary([a, b]), same(b));
    });

    test('把面积权重设为 0 时退化成纯置信度选择', () {
      // 对拍测试依赖这个行为 —— 它要和 Python 端（Ultralytics）
      // 的选人方式一致，而那边是按置信度选的。
      final small = cand(0.85, 0.05, 0.08);
      final big = cand(0.70, 0.30, 0.50);
      final got = pickPrimary([small, big],
          weights: const PoseSelectionWeights(area: 0));
      expect(got, same(small), reason: '纯置信度模式下应当选 0.85 那个');
    });

    test('前两名得分接近时判为歧义并说明原因', () {
      // 用比值而不是差值判断 —— 比值是尺度无关的。
      final a = cand(0.80, 0.20, 0.30);
      final b = cand(0.79, 0.20, 0.30);
      final sel = selectPerson([a, b]);
      expect(sel.isAmbiguous, isTrue);
      expect(sel.reason, contains('可能选错了人'));
      expect(sel.reason, contains('2 个人'));
    });

    test('差距明显时不算歧义，并说明选了多少人中的哪一个', () {
      final a = cand(0.80, 0.30, 0.40);
      final b = cand(0.30, 0.04, 0.06);
      final sel = selectPerson([a, b]);
      expect(sel.isAmbiguous, isFalse);
      expect(sel.reason, contains('2 个人'));
      expect(sel.reason, contains('占画面最大'));
    });

    test('选中的人永远是得分最高的那个', () {
      // 无论歧义与否，选出来的人都必须是第一名
      final cs = [
        cand(0.9, 0.02, 0.03),
        cand(0.5, 0.35, 0.45),
        cand(0.7, 0.10, 0.12),
        cand(0.3, 0.06, 0.08),
      ];
      final sel = selectPerson(cs);
      expect(sel.primary, same(cs[1]), reason: '面积最大的应当胜出');
    });

    test('框面积就是 w×h', () {
      expect(cand(0.9, 0.5, 0.4).area, closeTo(0.2, 1e-9));
    });

    test('一帧 21 个人时仍能选出运动员', () {
      // 复现实测场景：背景干扰很多
      final cs = <PoseCandidate>[
        // 一堆小的背景人
        for (var i = 0; i < 20; i++) cand(0.9 - i * 0.01, 0.03, 0.05),
        // 运动员：置信度不是最高，但占画面大
        cand(0.65, 0.28, 0.42),
      ];
      final sel = selectPerson(cs);
      expect(sel.primary, same(cs.last),
          reason: '应当选中占画面最大的那个，而不是置信度最高的背景人');
      expect(sel.candidateCount, 21);
    });
  });

  // -------------------------------------------------------------------------
  group('关键点与质量码', () {
    test('质量码阈值：0.5 以上清晰，0.25~0.5 存疑，以下不可见', () {
      expect(Keypoint.qualityOf(0.9), QualityCode.clear);
      expect(Keypoint.qualityOf(0.5), QualityCode.clear);
      expect(Keypoint.qualityOf(0.49), QualityCode.uncertain);
      expect(Keypoint.qualityOf(0.25), QualityCode.uncertain);
      expect(Keypoint.qualityOf(0.24), QualityCode.invisible);
      expect(Keypoint.qualityOf(0.0), QualityCode.invisible);
    });

    test('COCO-17 名称数量与点数一致', () {
      expect(cocoNames.length, cocoKeypointCount);
      expect(cocoNames.toSet().length, cocoNames.length, reason: '有重名');
    });

    test('包名与模型输出顺序一致（防重排）', () {
      // ⚠️ 这条守着"不要重排关键点列表"。
      //    重排会让关节错位，而人体左右对称会让它看起来正常。
      expect(cocoNames[0], 'nose');
      expect(cocoNames[5], 'shoulder_l');
      expect(cocoNames[6], 'shoulder_r');
      expect(cocoNames[11], 'hip_l');
      expect(cocoNames[12], 'hip_r');
      expect(cocoNames[15], 'ankle_l');
      expect(cocoNames[16], 'ankle_r');
    });

    test('按名字取点', () {
      final kps = List.generate(17, (i) => Keypoint(
          x: i / 17, y: 0.5, confidence: 0.9));
      final f = PoseFrame(frameIndex: 0, keypoints: kps);
      expect(f.byName('nose')!.x, closeTo(0 / 17, 1e-9));
      expect(f.byName('ankle_r')!.x, closeTo(16 / 17, 1e-9));
      expect(f.byName('不存在的点'), isNull);
    });

    test('包围盒只统计可见点', () {
      // 一个跑到画面外的点会把包围盒撑得很大，
      // 那会让裁剪、缩放全部算错。
      final kps = [
        const Keypoint(x: 0.3, y: 0.3, confidence: 0.9),
        const Keypoint(x: 0.5, y: 0.7, confidence: 0.9),
        const Keypoint(x: 0.4, y: 0.5, confidence: 0.9),
        // 这个点不可见，坐标是垃圾值
        const Keypoint(x: 99.0, y: -99.0, confidence: 0.01),
      ];
      final f = PoseFrame(frameIndex: 0, keypoints: kps);
      final bb = f.boundingBox!;
      expect(bb.$1, closeTo(0.3, 1e-9));
      expect(bb.$2, closeTo(0.3, 1e-9));
      expect(bb.$3, closeTo(0.5, 1e-9));
      expect(bb.$4, closeTo(0.7, 1e-9));
    });

    test('可见点太少时包围盒为 null，而不是返回错误的值', () {
      final kps = [
        const Keypoint(x: 0.3, y: 0.3, confidence: 0.9),
        const Keypoint(x: 0.5, y: 0.7, confidence: 0.01),
      ];
      final f = PoseFrame(frameIndex: 0, keypoints: kps);
      expect(f.boundingBox, isNull, reason: '只有 1 个可见点，包围盒没有意义');
    });

    test('覆盖率按可见点算', () {
      final kps = List.generate(
          10,
          (i) => Keypoint(
              x: 0.5,
              y: 0.5,
              confidence: i < 7 ? 0.9 : 0.01));
      final f = PoseFrame(frameIndex: 0, keypoints: kps);
      expect(f.coverage, closeTo(0.7, 1e-9));
    });
  });

  // -------------------------------------------------------------------------
  group('姿态序列', () {
    test('按关键点统计可见率', () {
      final seq = PoseSequence(
        sourceWidth: 640,
        sourceHeight: 480,
        frames: [
          // 第 0 个点两次都可见，第 16 个点只有一次可见
          PoseFrame(frameIndex: 0, keypoints: [
            const Keypoint(x: .5, y: .5, confidence: .9),
            ...List.generate(16, (_) =>
                const Keypoint(x: .5, y: .5, confidence: .01)),
          ]),
          PoseFrame(frameIndex: 1, keypoints: [
            const Keypoint(x: .5, y: .5, confidence: .9),
            ...List.generate(15, (_) =>
                const Keypoint(x: .5, y: .5, confidence: .01)),
            const Keypoint(x: .5, y: .5, confidence: .9),
          ]),
        ],
      );
      final cov = seq.coverageByKeypoint();
      expect(cov['nose'], closeTo(1.0, 1e-9));
      expect(cov['ankle_r'], closeTo(0.5, 1e-9));
      expect(cov['shoulder_l'], closeTo(0.0, 1e-9));
    });

    test('按帧号取帧', () {
      final seq = PoseSequence(
        sourceWidth: 640,
        sourceHeight: 480,
        frames: [
          PoseFrame(frameIndex: 5, keypoints: []),
          PoseFrame(frameIndex: 9, keypoints: []),
        ],
      );
      expect(seq.at(5)!.frameIndex, 5);
      expect(seq.at(9)!.frameIndex, 9);
      expect(seq.at(7), isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('数学边界', () {
    test('letterbox 对极端长宽比仍然成立', () {
      for (final (w, h) in [(4000, 100), (100, 4000), (1, 1)]) {
        final lb = computeLetterbox(w, h, 640);
        expect(lb.scale, greaterThan(0));
        final inX = 0.5 * w * lb.scale + lb.padX;
        expect(lb.toOriginalX(inX), closeTo(0.5, 1e-9),
            reason: '${w}x$h 的中心映射失败');
      }
    });

    test('坐标往返在随机点上成立', () {
      // 用固定种子保证可复现
      final rnd = math.Random(42);
      const w = 1280, h = 720, size = 640;
      final lb = computeLetterbox(w, h, size);
      for (var i = 0; i < 50; i++) {
        final ox = rnd.nextDouble();
        final oy = rnd.nextDouble();
        // 像素量纲
        final inX = ox * w * lb.scale + lb.padX;
        final inY = oy * h * lb.scale + lb.padY;
        expect(lb.toOriginalX(inX), closeTo(ox, 1e-9));
        expect(lb.toOriginalY(inY), closeTo(oy, 1e-9));
      }
    });
  });
}
