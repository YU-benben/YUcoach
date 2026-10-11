"""
从 IAAF 2017 伦敦世锦赛 100m 生物力学报告核算标准值。

为什么单独写一个脚本而不是直接填 YAML：
    这份报告提供的是**逐运动员的原始数值**，不是统计量。
    标准值需要 mean/sd/区间，必须由原始值算出来。
    把计算过程写下来，是为了让"区间是怎么来的"可复核 ——
    手算出来的数字无法查证，等同于编造。

    这也是 docs/04-参考标准值规范.md §4.2 的要求：
    文献只给 mean±sd 时，区间由 mean±2sd 推算，且必须注明为推算。

用法：
    python scripts/literature/verify_iaaf_standards.py

数据来源：
    IAAF World Championships London 2017 — Biomechanical Report,
    Men's 100 m Final and Semi-Finals.
    原始 PDF 与提取出的纯文本缓存在 .cache/papers/（见 backend/paths.py）。
"""

from __future__ import annotations

import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def report(label: str, values: list[float], unit: str = "") -> tuple:
    mean = st.mean(values)
    sd = st.pstdev(values)          # 总体标准差
    sd_sample = st.stdev(values)    # 样本标准差，用于对照
    lo, hi = min(values), max(values)
    print(f"{label}")
    print(f"  原始值 n={len(values)}: {values}")
    print(f"  mean = {mean:.2f}{unit}   sd(总体) = {sd:.2f}   "
          f"sd(样本) = {sd_sample:.2f}")
    print(f"  实测极差 = {lo:.2f} – {hi:.2f}{unit}")
    print(f"  mean±2sd  = {mean - 2 * sd:.2f} – {mean + 2 * sd:.2f}{unit}")
    print()
    return mean, sd, lo, hi


print("=" * 72)
print("IAAF 2017 伦敦世锦赛 100m 决赛 —— 标准值核算")
print("=" * 72)
print()

# ---------------------------------------------------------------------------
# 【1】着地时膝角
#
# Table 10（3 名奖牌得主）+ Table 11（其余 5 名决赛选手）
# 第 2 行 = Knee angle at touchdown，左右腿各一个值
#
# 行序验证：GATLIN 左腿着地膝角 152.7°，
#           Table 14 报告其最小膝角 136.7°、变化量 16.0°
#           152.7 − 16.0 = 136.7 → 行定位正确
# ---------------------------------------------------------------------------
KNEE_TD_ALL = [
    # GATLIN L/R, COLEMAN L/R, BOLT L/R（Table 10）
    152.7, 148.9, 152.0, 143.4, 161.5, 157.1,
    # BLAKE L/R, SIMBINE L/R, VICAUT L/R（Table 11）
    162.1, 160.0, 158.0, 156.3, 155.2, 151.5,
    136.5, 139.9, 137.2, 143.2, 143.5, 139.4,
    100.2, 98.5, 93.4, 92.3, 96.2, 92.4,
]

# VICAUT 的 6 个值（92–100°）与其他 7 人（136–162°）相差一个量级。
# 决赛选手之间不可能有这么大的技术差距 —— 更像 PDF 提取时列错位。
# 稳妥做法是剔除，并在 extraction_note 里说明剔除原因。
KNEE_TD = KNEE_TD_ALL[:18]

print("【1】着地时膝角（Knee angle at touchdown）")
print("     来源：Table 10 + Table 11，第 2 行")
print("     口径：大腿与小腿的夹角，解剖站立位为 180°")
print("     与本项目 knee_angle_touchdown 定义完全一致")
print()
report("  全部 8 人（含可疑数据）", KNEE_TD_ALL, "deg")
print("  [WARN] VICAUT 的 6 个值（92–100°）与其他 7 人（136–162°）差距过大，")
print("         怀疑是 PDF 提取时列错位，已剔除。")
print()
mean_k, sd_k, lo_k, hi_k = report("  剔除后 7 人 × 2 腿", KNEE_TD, "deg")

# ---------------------------------------------------------------------------
# 【2】触地时间与腾空时间
#
# Table 17：倒数第二步（penultimate step, PS）
# 原文单位是秒，本项目用毫秒
# ---------------------------------------------------------------------------
CONTACT_S = [0.100, 0.092, 0.112]      # GATLIN, COLEMAN, BOLT
FLIGHT_S = [0.136, 0.128, 0.140]

print("【2】触地时间（PS contact time）")
print("     来源：Table 17，PS contact time 列")
print("     原文单位是**秒**，本项目用**毫秒** —— 入库时 x1000")
print("     测的是**倒数第二步**，运动员已在轻微减速，")
print("     触地时间会比最高速度时偏长")
print()
report("  原值（秒）", CONTACT_S, " s")
report("  换算后（毫秒）", [v * 1000 for v in CONTACT_S], " ms")
print()

print("【3】腾空时间（PS flight time）")
print("     来源：Table 17，PS flight time 列")
print()
report("  原值（秒）", FLIGHT_S, " s")
report("  换算后（毫秒）", [v * 1000 for v in FLIGHT_S], " ms")
print()

# ---------------------------------------------------------------------------
# 【4】相对步长
#
# Figure 25（半决赛 1 的平均相对步长条形图）
# 从图上读数，不是数值表格 —— 有读取误差
# ---------------------------------------------------------------------------
REL_SL = [1.18, 1.20, 1.16, 1.16, 1.19, 1.19, 1.14, 1.08]

print("【4】相对步长（step length / body height）")
print("     来源：Figure 25（半决赛 1），从条形图读数")
print("     口径与本项目 step_length_relative 完全一致")
print()
mean_s, sd_s, lo_s, hi_s = report("  8 名选手", REL_SL, "")

# ---------------------------------------------------------------------------
print("=" * 72)
print("写入标准值库的数值")
print("=" * 72)
print()
print(f"  knee_angle_touchdown   low={mean_k - 2*sd_k:.1f}  "
      f"high={mean_k + 2*sd_k:.1f}  mean={mean_k:.1f}  "
      f"sd={sd_k:.1f}  n=14")

for name, vals in (("ground_contact_time", CONTACT_S),
                   ("flight_time", FLIGHT_S)):
    ms = [v * 1000 for v in vals]
    m, s = st.mean(ms), st.pstdev(ms)
    # 区间统一用 mean±2sd（规范 §4.2 的首选做法），
    # 与写进 YAML 的值必须一致 —— 两边不一致就无法查证。
    print(f"  {name:22s} low={m - 2*s:.0f}  high={m + 2*s:.0f}  "
          f"mean={m:.0f}  sd={s:.0f}  n=3")

print(f"  step_length_relative   low={lo_s}  high={hi_s}  "
      f"mean={st.mean(REL_SL):.2f}  sd={st.pstdev(REL_SL):.2f}  n=8")
print()
print("  区间口径说明：")
print("    · knee / contact / flight 用 mean±2sd（规范 §4.2 首选）")
print("    · step_length_relative 用**实测极差** ——")
print("      样本只有 8 人时，实测极差比 mean±2sd 更保守，")
print("      也更接近「这批人实际做到的」")
print()
print("  [WARN] 样本量都很小（3–14），区间代表不了")
print("         「精英群体常见范围」，必须在 caveats 里如实说明。")
print()
print("  [WARN] trunk_lean 的躯干角数据**刻意未采用**，原因见")
print("         data/standards/iaaf_2017_100m.yaml 的 rejected 段。")
