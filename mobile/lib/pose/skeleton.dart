/// 骨骼拓扑：哪些关键点连成线。
///
/// ## ⚠️ 先搞清楚两套关键点格式（这里踩过坑）
///
/// 项目里有**两套**关键点定义，容易搞混：
///
/// ```
/// COCO-17   ← 姿态模型（YOLOv8-pose / ONNX）的输出格式
///             鼻、双眼、双耳、双肩、双肘、双腕、双髋、双膝、双踝
///             有面部点，没有足部点
///
/// yu16      ← 电脑端算法使用的格式（backend/analysis/pose_types.py）
///             头、颈、双肩、双肘、双腕、双髋、双膝、双踝、足跟、足尖、
///             肩中心、骨盆中心
///             有足部点，没有面部点
/// ```
///
/// **手机端拿到的是 COCO-17。** 第一版这个文件是按 yu16 写的，
/// 用了 `neck` / `shoulder_center` / `pelvis_center` ——
/// 那些点 COCO-17 里根本不存在，画出来会是一条条断线。
///
/// 所以这份拓扑只使用 COCO-17 里真实存在的点。
///
/// ## 为什么不做 COCO-17 → yu16 的转换
///
/// 电脑端有完整的转换（含足部点几何推导），但手机端**不需要**：
///   · 手机端只负责画骨架和挑关键帧
///   · 20 个指标的计算在电脑端做（那里有完整的 yu16 和足部点推导）
///   · 手机端自己推导足部点会引入**第二套实现**，违背"指标算法只有一份"
///
/// 所以手机端画的就是纯粹的 COCO-17 骨架 —— 诚实、简单、不会漂移。
library;

import 'pose_types.dart';

/// 一条骨骼线。
class Bone {
  const Bone(this.from, this.to);

  /// 起点关键点名。
  final String from;

  /// 终点关键点名。
  final String to;
}

/// 人体骨骼连接关系（COCO-17）。
///
/// 顺序按"从躯干到四肢"排 —— 先画躯干再画四肢，
/// 这样四肢的线压在躯干上面，关节位置更清楚。
const List<Bone> skeletonBones = [
  // ---- 躯干 ----
  Bone('shoulder_l', 'shoulder_r'),
  Bone('shoulder_l', 'hip_l'),
  Bone('shoulder_r', 'hip_r'),
  Bone('hip_l', 'hip_r'),
  // 肩髋之间的两条交叉线不画 —— 会把躯干画成一个"X"，
  // 而真实躯干是前面那四条边围成的梯形。

  // ---- 头部 ----
  Bone('nose', 'shoulder_l'),
  Bone('nose', 'shoulder_r'),

  // ---- 左臂 ----
  Bone('shoulder_l', 'elbow_l'),
  Bone('elbow_l', 'wrist_l'),

  // ---- 右臂 ----
  Bone('shoulder_r', 'elbow_r'),
  Bone('elbow_r', 'wrist_r'),

  // ---- 左腿 ----
  Bone('hip_l', 'knee_l'),
  Bone('knee_l', 'ankle_l'),

  // ---- 右腿 ----
  Bone('hip_r', 'knee_r'),
  Bone('knee_r', 'ankle_r'),
];

/// 面部关键点。
///
/// COCO-17 里有 5 个面部点（鼻、双眼、双耳）。
/// 精确模式下画出来，精简模式下不画 ——
/// 手机上 5 个点会挤成一团，反而挡住真正重要的髋、膝、踝。
const List<String> faceKeypoints = [
  'nose', 'eye_l', 'eye_r', 'ear_l', 'ear_r',
];

/// 关键关节。这些在任何模式下都画。
///
/// 选这 12 个的理由：它们是判断跑姿技术的主要依据 ——
/// 肩肘腕看摆臂，髋膝踝看蹬伸与落地。
const List<String> keyJoints = [
  'shoulder_l', 'shoulder_r',
  'elbow_l', 'elbow_r',
  'wrist_l', 'wrist_r',
  'hip_l', 'hip_r',
  'knee_l', 'knee_r',
  'ankle_l', 'ankle_r',
];

/// 左右成对的关节，以及它们的对称伙伴。
///
/// 用途：
///   · 绘制时用**同色但不同明度**区分左右 —— 比用完全不同的颜色
///     更容易看出"这是同一类关节的两侧"
///   · 将来做左右对称性检查（步态不对称是常见的技术问题）
const Map<String, String> leftRightPairs = {
  'shoulder_l': 'shoulder_r',
  'shoulder_r': 'shoulder_l',
  'elbow_l': 'elbow_r',
  'elbow_r': 'elbow_l',
  'wrist_l': 'wrist_r',
  'wrist_r': 'wrist_l',
  'hip_l': 'hip_r',
  'hip_r': 'hip_l',
  'knee_l': 'knee_r',
  'knee_r': 'knee_l',
  'ankle_l': 'ankle_r',
  'ankle_r': 'ankle_l',
  'eye_l': 'eye_r',
  'eye_r': 'eye_l',
  'ear_l': 'ear_r',
  'ear_r': 'ear_l',
};

/// 这个点是不是身体左侧。
///
/// ⚠️ 注意：这是**解剖学**意义上的左右（`_l` 后缀），
///    不是画面上的左右。背面拍摄时，画面左边的腿是运动员的左腿；
///    正面拍摄时正好相反。
///
///    所以**不要**用这个来判断"画面左半边"。
bool isLeftSide(String name) => name.endsWith('_l');

/// 画面上的左右与解剖学左右是否一致。
///
/// ```
/// 侧面/背面拍摄：画面左 = 运动员左
/// 正面拍摄：    画面左 = 运动员右（因为人是面对镜头的）
/// ```
///
/// 用于绘制标注时避免标错。目前只做记录，
/// 因为 COCO-17 的输出本身已经是解剖学左右，不需要翻转。
bool screenMatchesAnatomy(String view) => view != 'front';

/// 按名字取索引。找不到返回 -1。
///
/// 每次线性查找 —— 17 个元素，比建 Map 更快，也不占内存。
int keypointIndex(String name) => cocoNames.indexOf(name);

/// 这份拓扑里的点数与 COCO-17 一致吗（自检用）。
///
/// 用于测试：确保没有写出 COCO-17 里不存在的点。
List<String> unknownKeypointsInTopology() {
  final known = cocoNames.toSet();
  final used = <String>{};
  for (final b in skeletonBones) {
    used.add(b.from);
    used.add(b.to);
  }
  used.addAll(faceKeypoints);
  used.addAll(keyJoints);
  return used.where((n) => !known.contains(n)).toList();
}
