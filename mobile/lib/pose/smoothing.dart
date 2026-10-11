/// 信号平滑。
///
/// ## 为什么必须平滑
///
/// 姿态模型的关键点有约 **3 像素**的抖动，而我们要提取的信号
/// （髋部高度的周期性起伏）可能只有几像素 ——
/// **抖动会淹没真实信号**。
///
/// 这是实测确认过的：项目里曾经因为没平滑，
/// 导致支撑中期检测漂移了 67 帧（整整一个步态周期）。
library;

/// 滑动平均。窗口大小为 [window]（奇数更好，保证对称）。
///
/// ## 边界怎么处理
///
/// 用**缩短的窗口**，而不是补零或复制边界值：
///
///   补零 → 首尾被拉向 0，产生假的极值
///   复制 → 首尾被冻结，产生假平台
///   缩短 → 首尾用能用的点求平均，最接近真实
///
/// 跑步视频的首尾（起跑和冲线）恰恰是关键帧所在，
/// 边界处理错了会直接影响关键帧位置。
List<double> movingAverage(List<double> x, int window) {
  if (window <= 1 || x.length < 2) return List<double>.from(x);

  // 窗口取奇数，保证中心对称
  var w = window.isEven ? window + 1 : window;
  if (w > x.length) w = x.length.isEven ? x.length - 1 : x.length;
  if (w <= 1) return List<double>.from(x);

  final half = w ~/ 2;
  final out = List<double>.filled(x.length, 0);

  for (var i = 0; i < x.length; i++) {
    final lo = i - half < 0 ? 0 : i - half;
    final hi = i + half >= x.length ? x.length - 1 : i + half;
    var sum = 0.0;
    for (var j = lo; j <= hi; j++) {
      sum += x[j];
    }
    out[i] = sum / (hi - lo + 1);
  }
  return out;
}

/// 中值滤波。
///
/// 比滑动平均更**抗离群值** —— 一个飞到画面外的关键点会把
/// 平均值拉偏几十像素，但不会影响中位数。
///
/// 代价是要排序，比滑动平均慢。关键点抖动不大的场景用滑动平均即可。
List<double> medianFilter(List<double> x, int window) {
  if (window <= 1 || x.length < 3) return List<double>.from(x);

  var w = window.isEven ? window + 1 : window;
  if (w > x.length) w = x.length.isEven ? x.length - 1 : x.length;
  if (w <= 1) return List<double>.from(x);

  final half = w ~/ 2;
  final out = List<double>.filled(x.length, 0);

  for (var i = 0; i < x.length; i++) {
    final lo = i - half < 0 ? 0 : i - half;
    final hi = i + half >= x.length ? x.length - 1 : i + half;
    final seg = x.sublist(lo, hi + 1)..sort();
    out[i] = seg[seg.length ~/ 2];
  }
  return out;
}

/// 数值微分（中心差分）。
///
/// 返回与输入等长的导数序列。边界用单侧差分。
List<double> gradient(List<double> y, double dt) {
  if (y.length < 2) return List<double>.filled(y.length, 0);
  final out = List<double>.filled(y.length, 0);
  for (var i = 0; i < y.length; i++) {
    if (i == 0) {
      out[i] = (y[1] - y[0]) / dt;
    } else if (i == y.length - 1) {
      out[i] = (y[i] - y[i - 1]) / dt;
    } else {
      out[i] = (y[i + 1] - y[i - 1]) / (2 * dt);
    }
  }
  return out;
}
