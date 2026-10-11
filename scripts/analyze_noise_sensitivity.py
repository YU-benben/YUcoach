"""
关键点噪声敏感性分析。

这个脚本回答一个合成验证回答不了的问题：

    「端到端验证证明了计算逻辑正确（数值与解析解一致），
      但真实视频里的关键点是有抖动的 —— 那些抖动会让结果差多少？」

为什么需要它：
    我们目前**没有合规的真实素材**（现有素材 30 fps，所有指标被正确拦下）。
    所以无法用"人工标注基准 vs 模型输出"来量化真实精度。

    但可以反过来做：**人为地给解析解加噪声**，
    观察指标输出偏离真值多少。这给出的是"误差上界"——
    只要真实关键点的抖动不超过注入的幅度，指标精度就不会差于这里的结果。

    这不能替代真实精度验证，但能把"不知道差多少"变成
    "在最坏情况下差多少"，对判断结果是否可信有实际意义。

噪声幅度的选取：
    以**画面归一化坐标**为单位（0–1）。
    YOLOv8-pose 在 960 像素输入下的关键点误差通常在
    2–8 像素，换算到 960×540 的画面约为 0.002–0.008 归一化单位。
    所以测试 0.001 / 0.003 / 0.006 / 0.012 四档，
    覆盖"比实际好"到"比实际差"的范围。

用法：
    python scripts/analyze_noise_sensitivity.py
"""

from __future__ import annotations

import math
import statistics as st
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.analysis.metrics import MetricContext, compute_all_metrics  # noqa: E402
from backend.analysis.phases import detect_gait_events, detect_phases  # noqa: E402
from backend.analysis.pose_types import (  # noqa: E402
    KEYPOINT_NAMES,
    Q_CLEAR,
    PoseFrame,
    PoseSequence,
)
from backend.analysis.reference_scale import ScaleEstimate  # noqa: E402

# 噪声档位（画面归一化坐标）
NOISE_LEVELS = [0.0, 0.001, 0.003, 0.006, 0.012]

FPS = 240.0
N_FRAMES = 480

# 关注的指标（运动学角度类，最受关键点精度影响）
WATCH = [
    "knee_angle_touchdown",
    "knee_angle_midstance",
    "shank_angle_touchdown",
    "hip_angle_toeoff",
    "trunk_lean",
    "step_frequency",
]


# ---------------------------------------------------------------------------
# 构造一段"跑步"姿态序列：腿按步态周期摆动
# ---------------------------------------------------------------------------

def make_runner(i: int, fps: float) -> PoseFrame:
    """
    构造一帧侧视跑步姿态。

    用正弦摆动模拟跑步：骨盆上下起伏、大腿绕髋摆动、小腿绕膝摆动。

    ⚠️ 骨盆的**垂直起伏**是必须的，不是装饰。
       「支撑中期 = 髋中点高度的局部最低点」这个判据需要髋高有起伏 ——
       最早版本的构造里骨盆 y 恒定，结果是：
         · 髋高序列是一条直线（振幅 0.00000）
         · 极值检测在常量信号上会检出大量伪事件
         · 由此算出的所有噪声敏感性结论全部无效
       这个坑值得记下来：**验证脚本的输入必须让被验证的判据有信号可用**，
       否则测的是噪声，不是算法。

    垂直起伏的量级：跑步时重心起伏约 5–10 cm，
    按身高 1.78 m 折算成归一化坐标约 0.03–0.06。
    """
    kp = np.zeros((16, 3), dtype=np.float64)

    # 步态周期约 0.22 秒（步频约 273 步/分）
    t = i / fps
    step_cycle = 0.22
    phase = 2 * math.pi * t / step_cycle

    # ⚠️ 骨盆垂直起伏的频率必须等于**步频**，不能是它的两倍。
    #
    # 踩过的坑：最初写成 cos(2 * phase)，结果骨盆以 2f 起伏
    # （一个步周期里起伏两次）。这听起来像是"左右腿各支撑一次"，
    # 但那是**跨步（stride）**的节奏，而 phase 定义的是**步（step）**。
    #
    # 后果是自洽性坏掉：
    #   · 髋高曲线以 2f 振荡 -> 极值检测在 2f 上找支撑中期
    #     得到 18 个事件（间隔 26.5 帧），而正确值应是 9 个（间隔 53 帧）
    #   · 步频指标于是测到 2f 的谐波，算出 390 步/分（真值 273）
    #
    # 正确的构造：骨盆每个**步**起伏一次，与支撑中期同频。
    # 这样"支撑中期 = 髋高最低点"的判据才有意义。
    bob = 0.018 * math.cos(phase)
    cx = 0.35 + i * 0.0012          # 整体向右移动
    pelvis = np.array([cx, 0.55 + bob])

    # 躯干：轻微前倾且随周期微动
    trunk_lean = math.radians(8.0 + 3.0 * math.sin(phase))
    trunk_len = 0.24
    neck = pelvis + np.array([trunk_len * math.sin(trunk_lean),
                              -trunk_len * math.cos(trunk_lean)])
    head = neck + np.array([0.02 * math.sin(trunk_lean), -0.095])

    # 左右腿相位差 π
    def leg(ph: float):
        thigh = math.radians(35.0 * math.sin(ph))
        shank = math.radians(45.0 * math.sin(ph + 1.1) - 20.0)
        knee = pelvis + np.array([0.24 * math.sin(thigh),
                                  0.24 * math.cos(thigh)])
        ankle = knee + np.array([0.24 * math.sin(thigh + shank),
                                 0.24 * math.cos(thigh + shank)])
        return knee, ankle

    knee_r, ankle_r = leg(phase)
    knee_l, ankle_l = leg(phase + math.pi)

    def put(name: str, xy) -> None:
        kp[KEYPOINT_NAMES.index(name)] = [float(xy[0]), float(xy[1]), Q_CLEAR]

    put("pelvis_center", pelvis)
    put("hip_r", pelvis + [0.02, 0])
    put("hip_l", pelvis - [0.02, 0])
    put("neck", neck)
    put("shoulder_center", neck)
    put("shoulder_r", neck + [0.04, 0])
    put("shoulder_l", neck - [0.04, 0])
    put("head", head)
    put("knee_r", knee_r)
    put("knee_l", knee_l)
    put("ankle_r", ankle_r)
    put("ankle_l", ankle_l)
    # 足部点：由踝关节几何推导（与 keypoint_map 的做法一致）
    for side, ankle in (("r", ankle_r), ("l", ankle_l)):
        heel = ankle + [(-0.01 if side == "r" else 0.01), 0.012]
        toe = ankle + [(0.030 if side == "r" else -0.030), 0.010]
        put(f"heel_{side}", heel)
        put(f"toe_{side}", toe)

    kp[:, 0] = np.clip(kp[:, 0], 0.0, 1.0)
    kp[:, 1] = np.clip(kp[:, 1], 0.0, 1.0)

    return PoseFrame(frame_index=i, keypoints=kp, person_conf=0.95)


def build_sequence(noise_sigma: float, seed: int) -> PoseSequence:
    """构造序列；noise_sigma > 0 时给每个关键点加高斯噪声。

    每个 (帧, 关键点) 独立加噪 —— 真实检测误差就是逐帧独立的，
    也是这一点让角度指标产生抖动（而不是整体平移抵消掉）。
    """
    rng = np.random.default_rng(seed)
    seq = PoseSequence(estimator_name="noise-test",
                       estimator_version="1.0.0")
    for i in range(N_FRAMES):
        pf = make_runner(i, FPS)
        if noise_sigma > 0:
            kp = pf.keypoints.copy()
            # 只给可见点加噪（不可见点本来就不参与计算）
            vis = kp[:, 2] > 0
            noise = rng.normal(0, noise_sigma, size=(int(vis.sum()), 2))
            kp[vis, :2] += noise
            kp[:, 0] = np.clip(kp[:, 0], 0.0, 1.0)
            kp[:, 1] = np.clip(kp[:, 1], 0.0, 1.0)
            pf = PoseFrame(frame_index=i, keypoints=kp,
                           person_conf=pf.person_conf)
        seq.frames.append(pf)
    return seq


def run_once(noise_sigma: float, seed: int) -> dict[str, float]:
    """跑一次分析，返回 {指标: 数值}。失败的指标不返回。"""
    seq = build_sequence(noise_sigma, seed)
    events = detect_gait_events(seq, FPS)
    phases, _ = detect_phases(seq, FPS)

    ctx = MetricContext(
        seq=seq, fps=FPS, view="side",
        # 尺度用身高推算：加了噪声也能算出来，
        # 这样测的是"关键点噪声的影响"而不是"尺度估计失败"
        scale=ScaleEstimate(
            method="person_height", valid_per_frame=True,
            median_pixels_per_meter=0.24 / 1.78),
        events=events, phases=phases, athlete_height_cm=178.0,
    )

    out: dict[str, float] = {}
    for r in compute_all_metrics(ctx):
        if r.insufficient is None and r.value is not None:
            out[r.metric_id] = float(r.value)
    return out


def main() -> int:
    print("=" * 72)
    print("关键点噪声敏感性分析")
    print("=" * 72)
    print()
    print(f"合成序列：{N_FRAMES} 帧 @ {FPS:.0f} fps")
    print(f"噪声档位：{NOISE_LEVELS}（画面归一化坐标）")
    print()

    # 噪声是随机的，单次结果波动大。每个档位跑多次取统计量。
    REPEATS = 8
    print(f"每个档位重复 {REPEATS} 次（噪声是随机的，需看分布）")
    print()

    # ---- 先跑无噪声，作为真值 ----
    truth = run_once(0.0, seed=0)
    print("无噪声时算出的指标（作为真值）：")
    for k in WATCH:
        if k in truth:
            print(f"  {k:26s} {truth[k]:>10.3f}")
    print()

    missing = [k for k in WATCH if k not in truth]
    if missing:
        print(f"  [WARN] 无噪声时也算不出的指标：{missing}")
        print("         这些指标无法参与噪声分析。")
        print()

    # ---- 各噪声档位 ----
    results: dict[float, dict[str, list[float]]] = {}
    for sigma in NOISE_LEVELS:
        per_metric: dict[str, list[float]] = {k: [] for k in truth}
        for rep in range(REPEATS):
            vals = run_once(sigma, seed=1000 + rep)
            for k, v in vals.items():
                if k in per_metric:
                    per_metric[k].append(v)
        results[sigma] = per_metric

    # ---- 汇总表 ----
    print("=" * 72)
    print("误差随噪声的变化")
    print("=" * 72)
    print()
    print("表中数值 = |实测 − 真值| 的中位数（跨重复次数）")
    print()

    hdr = "  指标".ljust(28)
    for sigma in NOISE_LEVELS:
        px = sigma * 960
        hdr += f"{px:>7.1f}px"
    print(hdr)
    print("  " + "-" * (26 + 9 * len(NOISE_LEVELS)))

    summary: dict[str, dict[float, float]] = {}
    for k in WATCH:
        if k not in truth or not results[NOISE_LEVELS[0]][k]:
            continue
        row = f"  {k:26s}"
        summary[k] = {}
        for sigma in NOISE_LEVELS:
            vals = results[sigma][k]
            if not vals:
                row += f"{'—':>9s}"
                continue
            errs = [abs(v - truth[k]) for v in vals]
            med = st.median(errs)
            summary[k][sigma] = med
            row += f"{med:>9.2f}"
        print(row)

    print()
    print("（'px' 是按 960 像素宽的画面把归一化噪声换算成的像素值）")
    print()

    # ---- 结论 ----
    print("=" * 72)
    print("结论")
    print("=" * 72)
    print()

    # 找"误差开始明显变大"的档位
    real_world = 0.003      # 约 3 像素，YOLOv8-pose 的典型水平
    print(f"以 {real_world * 960:.0f} 像素噪声（YOLOv8-pose 的典型水平）为例：")
    print()
    for k in WATCH:
        if k not in summary or real_world not in summary[k]:
            continue
        err = summary[k][real_world]
        v = truth[k]
        if abs(v) > 1e-6:
            rel = err / abs(v) * 100
            print(f"  {k:26s} 误差 {err:>7.2f}"
                  f"（真值 {v:>8.2f}，相对 {rel:>5.1f}%）")
        else:
            print(f"  {k:26s} 误差 {err:>7.2f}（真值 {v:.2f}）")
    print()

    print("怎么用这个结果：")
    print("  · 误差小的指标（相对 <5%）—— 关键点抖动不影响结论，可放心用")
    print("  · 误差大的指标 —— 单次测量的数值不可较真，")
    print("    但**同一个人不同时期的变化趋势**仍然可用（系统误差会抵消）")
    print()
    print("⚠️ 这个分析的边界：")
    print("  · 它给的是**误差上界**，不是真实精度。")
    print("    真实误差还包含模型偏差（关键点系统性偏移），")
    print("    而这里注入的是零均值噪声，只造成随机误差。")
    print("  · 真实素材还有遮挡、运动模糊、透视变形，")
    print("    这些都不是高斯噪声能模拟的。")
    print("  · 所以结论只能用来判断「哪些指标对噪声敏感」，")
    print("    不能替代用真实素材做的精度验证。")
    print()
    print("⚠️ 已知的合成模型局限（会让上述误差**偏乐观**）：")
    print("  · knee_angle_touchdown 与 knee_angle_midstance 的真值相同")
    print(f"    （都是 {truth.get('knee_angle_midstance', 0):.1f}°），")
    print("    而真实跑步中着地膝角明显小于支撑中期膝角（相差约 30°）。")
    print("    原因是合成腿的摆动是简单正弦，缺少着地缓冲的屈膝动作。")
    print("    后果：这两个指标在本测试里其实测的是同一个角度，")
    print("    无法反映「取值时刻不同」带来的差异。")
    print("  · 骨盆起伏是纯正弦，缺少真实跑步中左右腿的不对称。")
    print()
    print("  → 这些局限不改变「哪些指标对噪声敏感」的结论，")
    print("    但绝对值不能当作真实精度引用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
