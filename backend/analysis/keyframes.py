"""
关键帧图像生成。

## 这个模块解决什么

报告里已经有数字了，但教练拿到「着地时膝角 152°」这句话时，
**看不出是哪一帧、哪个角、怎么量的**。本模块把关键瞬间
画成带骨骼线和角度弧的图片，让结论可核对。

## 契约要求（不是我们自己加的）

`analysis.schema.json` 的 `Keyframe` 定义里写着：

    image_url        关键帧图片地址
    pixels_per_meter 「该帧的参考尺度。报告必须在关键帧图上绘制尺度条，
                       否则教练会误判体型变化」

**尺度条是硬性要求** —— 少了它，同一张图在不同距离拍出来不一样大，
教练会以为运动员变胖或变瘦了。

## 选帧策略

比赛视频里关键瞬间很多（一次跑动有十几步）。全画出来：
  · 图太多，教练看不过来
  · 报告体积暴涨（每张几百 KB）

所以只挑**有代表性且信息量最大**的几帧：

    起跑 → acceleration 的第一次着地      看起跑姿态
    加速中段 → acceleration 的一次支撑中期  看加速期的重心
    途中跑 → max_velocity 的着地 + 支撑中期  看最高速度姿态

两个约束：
  · 同一阶段内两帧至少间隔 `MIN_GAP_FRAMES`，避免选出几乎一样的图
  · 总数上限 `MAX_KEYFRAMES`，防止长视频把报告撑爆

## 角度弧怎么画

只写「152°」教练不知道量的是哪个角。所以：
  1. 在关节点上按两条边画一段**弧线**
  2. 弧线中点写数值
  3. 边上画短刻度，指明是哪两条边

这与几何课本里标注角度的方式一致 —— 教练一看就懂。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .pose_types import (
    KEYPOINT_NAMES,
    Q_INVISIBLE,
    PoseFrame,
    PoseSequence,
)
from .video_io import iter_frames

#: 最多生成多少张关键帧图。超过就只保留最有代表性的。
MAX_KEYFRAMES = 6

#: 同一阶段内两帧的最小间隔（帧）。太近的两帧画出来几乎一样，浪费。
MIN_GAP_FRAMES = 8

#: 输出图片的 JPEG 质量。85 在清晰度和体积之间比较平衡 ——
#: 关键帧要能看清骨架细节，但报告里放太多大图会让手机加载很慢。
JPEG_QUALITY = 85

#: 尺度条长度（米）。1 米在画面上通常是几十到几百像素，够直观。
SCALE_BAR_METERS = 1.0

# 颜色（BGR）
_C_WHITE = (255, 255, 255)
_C_BLACK = (0, 0, 0)
_C_ARC = (60, 220, 255)        # 角度弧：橙黄，与骨架的绿/黄区分开
_C_SCALE = (255, 255, 255)


@dataclass
class KeyframeRequest:
    """一个待生成的关键帧。"""

    frame_index: int
    event: str            # touchdown / midstance / ...
    phase: str            # acceleration / max_velocity / ...
    step_index: int | None
    side: str | None      # L / R / both
    annotations: list[dict]   # [{metric_id, value, unit, ref_low, ref_high}]

    #: 相位是否**真的**落在检测到的相位区间内。
    #: False 表示该阶段是从最近的相位推断的 —— 图上要标注，
    #: 否则教练会以为"这确实是最高速度阶段"，而其实只是猜的。
    phase_is_exact: bool = True


# ---------------------------------------------------------------------------
# 选帧
# ---------------------------------------------------------------------------

def _phase_of_frame(ctx, frame_index: int) -> str:
    """
    该帧属于哪个运动阶段。

    ⚠️ 找不到时**退回最近的相位**，而不是返回空。

    为什么必须这样（真实踩过的坑）：
        现有素材是镜头跟随拍摄，而 detect_phases 靠"骨盆在画面里的
        水平位置"求速度 —— 镜头跟着运动员移动时，运动员在画面里
        位置几乎不变，于是算出的"速度曲线"反映的是镜头运动。

        实际结果：332 帧的素材，相位只覆盖了第 251–329 帧，
        而检出的着地（帧 14）与支撑中期（帧 21）**完全落在所有相位之外**。
        如果此时返回空，关键帧就把起跑和加速姿态全丢了 ——
        而那恰恰是教练最想看的两帧。

    退回最近相位是**有损**的（可能标错阶段），但比丢掉整帧好：
    图上标错阶段只是文字不精确，丢掉图则等于没有这张图。
    调用方可以通过 `phase_inferred` 判断这个阶段是推出来的还是量出来的。
    """
    for seg in (ctx.phases or []):
        if seg.from_frame <= frame_index <= seg.to_frame:
            return seg.phase

    if not ctx.phases:
        return ""

    # 退回最近的一段
    best, best_dist = None, None
    for seg in ctx.phases:
        if frame_index < seg.from_frame:
            d = seg.from_frame - frame_index
        else:
            d = frame_index - seg.to_frame
        if best_dist is None or d < best_dist:
            best, best_dist = seg, d
    return best.phase if best else ""


def _phase_is_exact(ctx, frame_index: int) -> bool:
    """该帧是否**真的落在**某个相位区间内（而非退回推断）。"""
    for seg in (ctx.phases or []):
        if seg.from_frame <= frame_index <= seg.to_frame:
            return True
    return False


def _athlete_size(ctx, frame_index: int) -> float:
    """
    该帧里运动员在画面中占多大（关键点包围盒的高度）。

    为什么要用它来挑帧（真实踩过的坑）：
        第一版按"阶段均匀取样"选帧，结果选中的是起跑蹲踞姿势那一帧 ——
        运动员蹲在地上、被前方其他人挡住、关键点画得七零八落。
        而那一帧在**信息量上恰恰是最差的**：教练看不出任何东西。

    所以同一阶段内有多帧可选时，应当挑**运动员清楚、占画面大**的那一帧 ——
    "占画面大"是拍摄标准的要求（运动员占画面高度 1/3 以上），
    也是关键点质量最直接的代理指标。

    返回包围盒高度（归一化坐标）。取不到返回 0。
    """
    pf = ctx.frames_by_index().get(frame_index)
    if pf is None:
        return 0.0

    ys = [float(kp[1]) for kp in pf.keypoints if kp[2] != Q_INVISIBLE]
    if len(ys) < 6:
        return 0.0
    return max(ys) - min(ys)


def _pick_best_in_phase(ctx, items: list[tuple[int, str]],
                        n: int) -> list[tuple[int, str]]:
    """
    在一个阶段内挑 n 帧：**优先清晰可读的**，再照顾时间分布。

    做法：
      1. 先按"运动员占画面大小"排序，取前 2n 个作为候选池
      2. 在候选池里按时间均匀取 n 个

    为什么两步走：只按大小取，可能几帧全挤在同一时刻；
    只按时间取，又会选中看不清的帧。两步兼顾。
    """
    if len(items) <= n:
        return sorted(items)

    scored = sorted(items, key=lambda it: -_athlete_size(ctx, it[0]))
    pool = sorted(scored[: max(n * 2, n)])
    if len(pool) <= n:
        return pool

    # 在候选池里按时间均匀取 n 个
    step = (len(pool) - 1) / max(n - 1, 1)
    picked_idx = {int(round(i * step)) for i in range(n)}
    return [pool[i] for i in sorted(picked_idx) if i < len(pool)]


def select_keyframes(ctx, metric_results: list | None = None
                     ) -> list[KeyframeRequest]:
    """
    按契约的 Event 枚举挑出要画的关键帧。

    返回的列表已按时间排序，且满足间隔与数量约束。

    为什么按「阶段」而不是「按步」来选：
        一次跑动有十几步，每步都画会有十几张几乎相同的图。
        教练真正关心的是**不同阶段**的姿态差异 ——
        起跑什么样、加速期什么样、途中跑什么样。
    """
    events = ctx.events
    if events is None:
        return []

    # 候选：(帧号, 事件名, 相位)。优先级用列表顺序表达。
    candidates: list[tuple[int, str]] = []

    # 每次事件都标注它所属的相位
    for td in events.touchdowns:
        candidates.append((td, "touchdown"))
    for ms in events.midstances:
        candidates.append((ms, "midstance"))

    if not candidates:
        return []

    # 按相位分组，每组只取第一个和最后一个有代表性的
    by_phase: dict[str, list[tuple[int, str]]] = {}
    for frame, ev in sorted(candidates):
        ph = _phase_of_frame(ctx, frame)
        if not ph:
            # 连一个相位都没有（detect_phases 完全失败）时，
            # 归到一个兜底分组，保证事件帧不会被丢掉
            ph = "acceleration"
        by_phase.setdefault(ph, []).append((frame, ev))

    # 阶段的优先级：起跑和加速最需要看，途中跑次之
    priority = ["acceleration", "max_velocity", "transition", "start",
                "deceleration"]

    # 每个阶段想选几个。加速段看两次（起步 + 中段），
    # 因为加速期姿态变化最大。
    want = {"acceleration": 3, "max_velocity": 2, "transition": 1,
            "start": 1, "deceleration": 1}

    picked: list[tuple[int, str, str]] = []
    for ph in priority:
        items = by_phase.get(ph) or []
        if not items:
            continue
        n = want.get(ph, 1)

        # 先按清晰度筛，再照顾时间分布。
        # 直接用 items[:n] 会选中"刚好排在前面"的帧 ——
        # 那可能是运动员被挡住、缩在画面角落的一帧。
        chosen = _pick_best_in_phase(ctx, items, n)

        for frame, ev in chosen:
            picked.append((frame, ev, ph))

    # 全局排序 + 总量封顶
    picked.sort()
    picked = picked[:MAX_KEYFRAMES]

    # 组装请求，并挂上该帧该量的角度标注
    out: list[KeyframeRequest] = []
    for frame, ev, ph in picked:
        out.append(KeyframeRequest(
            frame_index=frame,
            event=ev,
            phase=ph,
            step_index=_step_index_of(events, frame, ev),
            side=None,          # 侧面拍摄时左右都可能，不强行指定
            annotations=_annotations_for(ctx, frame, ev, ph, metric_results),
            phase_is_exact=_phase_is_exact(ctx, frame),
        ))
    return out


def _step_index_of(events, frame: int, event: str) -> int | None:
    """
    这是第几步。触地次数即步数 —— 契约里 step_index 的含义亦是如此。

    为什么按触地数而不是按"第几次支撑中期"：
        一次跑动的"步"通常按着地次数计，跳一步算一步。
        支撑中期与触地一一对应，但触地更直接。
    """
    tds = sorted(events.touchdowns)
    if not tds:
        return None
    # 找该帧之前（含）已经发生了多少次触地
    n = sum(1 for t in tds if t <= frame)
    return n if n > 0 else None


def _annotations_for(ctx, frame: int, event: str, phase: str,
                     metric_results: list) -> list[dict]:
    """
    这一帧要标注哪些角度。

    只标注**与这个事件真正相关**的指标 ——
    在着地帧上写"支撑中期膝角"会让教练困惑。

    事件与指标的对应关系来自指标的语义（见 docs/03-指标定义.md）：
        touchdown -> 着地时胫骨角 / 膝角 / 踝角
        midstance -> 支撑中期膝角
        toe_off   -> 离地时髋角

    ⚠️ 只标注【真正算出了数值】的指标。

        真实踩过的坑：第一版直接取 metric.value，而那些指标
        因为帧率不足被判了 insufficient_data —— value 是 None。
        结果图上仍然画出了角弧，并显示 "7°" / "0°" 这种数字。

        这是**最坏的一类错误**：系统在报告里说"这项测不出来"，
        却在图上画了一个数字。教练会信图，不会信文字。
        而且那个数字看起来完全正常。

        所以这里必须先检查 insufficient —— 有它就不标注。
        宁可图上一条角弧都没有，也不能画一个假的。
    """
    by_event = {
        "touchdown": ("shank_angle_touchdown", "knee_angle_touchdown",
                      "ankle_angle_touchdown"),
        "midstance": ("knee_angle_midstance",),
        "toe_off": ("hip_angle_toeoff",),
    }
    wanted = by_event.get(event, ())

    out: list[dict] = []
    results = {r.metric_id: r for r in (metric_results or [])}
    for mid in wanted:
        r = results.get(mid)
        if r is None:
            continue
        # 数据不足 → 不标注。与报告保持完全一致。
        if getattr(r, "insufficient", None) is not None:
            continue
        if r.value is None:
            continue
        out.append({
            "metric_id": mid,
            "value": round(float(r.value), 1),
            "unit": r.unit,
            "ref_low": None,
            "ref_high": None,
        })
    return out


# ---------------------------------------------------------------------------
# 绘图
# ---------------------------------------------------------------------------

def _joint_angle_points(metric_id: str, kps: np.ndarray, w: int, h: int):
    """
    返回画角度弧需要的三个点（像素坐标）：(a, vertex, c)。

    角度是 ∠(a, vertex, c) —— 与 metrics.py 里的算法保持一致。
    不一致的话，图上画的角和报告里写的数会对不上，
    而教练会先信图、后信数字。
    """
    idx = {n: i for i, n in enumerate(KEYPOINT_NAMES)}

    def px(name: str):
        i = idx[name]
        x, y, q = kps[i]
        if q == Q_INVISIBLE:
            return None
        return (int(x * w), int(y * h))

    table = {
        "knee_angle_touchdown": ("hip_r", "knee_r", "ankle_r"),
        "knee_angle_midstance": ("hip_r", "knee_r", "ankle_r"),
        "shank_angle_touchdown": ("knee_r", "ankle_r", "toe_r"),
        "ankle_angle_touchdown": ("knee_r", "ankle_r", "toe_r"),
        "hip_angle_toeoff": ("shoulder_r", "hip_r", "knee_r"),
    }
    names = table.get(metric_id)
    if not names:
        return None

    pts = [px(n) for n in names]
    if any(p is None for p in pts):
        # 右侧不可见时退回左侧
        names_l = tuple(n.replace("_r", "_l") for n in names)
        pts = [px(n) for n in names_l]
        if any(p is None for p in pts):
            return None
    return pts[0], pts[1], pts[2]


def _draw_angle_arc(img, a, vertex, c, value: float, unit: str,
                    radius: int = 48, label_slot: int = 0) -> None:
    """
    在 vertex 处画角度弧并写数值。

    画法：
      1. 从 vertex 向 a、c 各画一条短刻度线（指明量的是哪两条边）
      2. 在两条边之间画弧
      3. 在弧的中点偏移处写数值

    为什么要有刻度线：光画一条弧，教练不知道这条弧对应哪两条边。

    ⚠️ label_slot 是**必须的**：一帧上可能标 2–3 个角度，
       不加区分时它们的标签会互相压在一起（实际发生过：
       两个标签都落在画面左上角，叠成一团）。
       每个 slot 给一个不同的半径，标签就自然散开了。

    ⚠️ 标签还要**夹在画面内**。这个运动员常出现在画面边缘，
       不做夹取的话标签会跑到画面外，教练根本看不到数字。
    """
    h, w = img.shape[:2]
    vx, vy = vertex
    ang_a = math.atan2(a[1] - vy, a[0] - vx)
    ang_c = math.atan2(c[1] - vy, c[0] - vx)

    # 两条边的短刻度
    for ang in (ang_a, ang_c):
        ex = int(vx + radius * 1.15 * math.cos(ang))
        ey = int(vy + radius * 1.15 * math.sin(ang))
        cv2.line(img, (vx, vy), (ex, ey), _C_BLACK, 4, cv2.LINE_AA)
        cv2.line(img, (vx, vy), (ex, ey), _C_ARC, 2, cv2.LINE_AA)
        cv2.circle(img, (ex, ey), 3, _C_ARC, -1, cv2.LINE_AA)

    # 弧：从 ang_a 扫到 ang_c，取**劣弧**（夹角本身 ≤180°）
    deg_a = math.degrees(ang_a)
    deg_c = math.degrees(ang_c)
    diff = (deg_c - deg_a + 180) % 360 - 180
    n = max(8, int(abs(diff) / 4))

    pts = []
    for k in range(n + 1):
        d = math.radians(deg_a + diff * k / n)
        pts.append((int(vx + radius * math.cos(d)),
                    int(vy + radius * math.sin(d))))
    arr = np.array(pts, dtype=np.int32)
    cv2.polylines(img, [arr], False, _C_BLACK, 5, cv2.LINE_AA)
    cv2.polylines(img, [arr], False, _C_ARC, 3, cv2.LINE_AA)

    # 数值写在弧的中点外侧。半径随 slot 递增，避免多个标签重叠。
    mid = math.radians(deg_a + diff / 2)
    r_label = radius + 26 + label_slot * 30
    tx = int(vx + r_label * math.cos(mid))
    ty = int(vy + r_label * math.sin(mid))

    label = f"{value:.0f}{unit}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2)

    # 夹进画面内（留 6 px 余量）
    tx = max(6, min(tx, w - tw - 6))
    ty = max(th + 8, min(ty, h - 8))

    # 黑色描边保证在任何背景上都读得出来
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        cv2.putText(img, label, (tx + dx, ty + dy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, _C_BLACK, 3, cv2.LINE_AA)
    cv2.putText(img, label, (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, _C_ARC, 2, cv2.LINE_AA)


def _draw_scale_bar(img, pixels_per_meter: float | None) -> None:
    """
    画参考尺度条。

    契约原文：「报告必须在关键帧图上绘制尺度条，
             否则教练会误判体型变化」

    为什么这条重要：同一个运动员，相机离得近时在画面上更大。
    没有尺度条，教练把两次不同距离的截图一对比，
    会以为运动员变胖了或者长高了。
    """
    h, w = img.shape[:2]
    margin = max(6, int(w * 0.02))
    fs = _fit_font_scale(w, base=0.55)

    if not pixels_per_meter or pixels_per_meter <= 1e-6:
        # 没有尺度就说清楚「没有」，而不是画一条假的
        _draw_text_fitted(img, "无参考尺度（位移类指标不可用）",
                          margin, h - margin, fs, (80, 200, 255),
                          w - margin * 2)
        return

    bar_px = int(SCALE_BAR_METERS * pixels_per_meter)
    bar_px = min(bar_px, int(w * 0.42))
    if bar_px < 24:
        return      # 太短了画出来没有参考价值

    y = h - margin - 6
    x0 = margin
    x1 = x0 + bar_px

    cv2.line(img, (x0, y), (x1, y), _C_BLACK, 7, cv2.LINE_AA)
    cv2.line(img, (x0, y), (x1, y), _C_SCALE, 4, cv2.LINE_AA)
    for x in (x0, x1):
        cv2.line(img, (x, y - 8), (x, y + 8), _C_BLACK, 7, cv2.LINE_AA)
        cv2.line(img, (x, y - 8), (x, y + 8), _C_SCALE, 4, cv2.LINE_AA)

    label = f"{SCALE_BAR_METERS:.0f} m"
    _draw_text_fitted(img, label, x0, y - 16, fs, _C_SCALE,
                      w - x0 - margin)


def _crop_to_athlete(img, kps: np.ndarray, min_ratio: float = 0.34):
    """
    把画面裁到运动员附近，让骨架看得清。

    ## 为什么需要

        现有素材是 960×540 的远景，运动员只占画面高度约 1/5。
        骨架线和角度弧按像素画，人小的时候弧线几乎叠在一起，
        教练根本看不清量的是哪个角。

        拍摄标准要求"运动员占画面高度 1/3 以上"，但教练实际拍出来
        经常不到。裁剪是**在不改变测量结果的前提下**提升可读性 ——
        指标早就用归一化坐标算完了，裁图只影响显示。

    ## 为什么保留 1/3 画面高度

        裁得太狠会把地面裁掉，而**地面是判断足部接触的关键参照**。
        教练看出这张图，一半信息来自"脚离地多远"。
        所以下限设在画面高度的 1/3，并向上多留一点给头部。

    返回裁剪后的图。无法裁剪（关键点太少）时返回原图。
    """
    h, w = img.shape[:2]
    xs = [float(kp[0]) for kp in kps if kp[2] != Q_INVISIBLE]
    ys = [float(kp[1]) for kp in kps if kp[2] != Q_INVISIBLE]
    if len(xs) < 6:
        return img

    x0, x1 = min(xs) * w, max(xs) * w
    y0, y1 = min(ys) * h, max(ys) * h

    bw, bh = x1 - x0, y1 - y0
    if bh < 1 or bw < 1:
        return img

    # 目标框：人身边留 60% 余量（水平），竖直方向下方多留（地面）
    pad_x = bw * 0.60
    pad_top = bh * 0.35
    pad_bottom = bh * 0.85      # 下方留更多 —— 地面是重要参照

    cx0 = x0 - pad_x
    cx1 = x1 + pad_x
    cy0 = y0 - pad_top
    cy1 = y1 + pad_bottom

    # 保证不低于画面高度的 min_ratio，也不超过原图
    min_h = h * min_ratio
    if cy1 - cy0 < min_h:
        extra = (min_h - (cy1 - cy0)) / 2
        cy0 -= extra
        cy1 += extra

    min_w = min_h * (w / h)
    if cx1 - cx0 < min_w:
        extra = (min_w - (cx1 - cx0)) / 2
        cx0 -= extra
        cx1 += extra

    ix0 = max(0, int(cx0))
    iy0 = max(0, int(cy0))
    ix1 = min(w, int(cx1))
    iy1 = min(h, int(cy1))

    if ix1 - ix0 < 32 or iy1 - iy0 < 32:
        return img
    return img[iy0:iy1, ix0:ix1].copy()


def _fit_font_scale(img_w: int, base: float = 0.62,
                    ref_w: int = 960) -> float:
    """
    按图片宽度缩放字号。

    ⚠️ 为什么必须有这个函数（真实踩过的坑）：

        远景素材裁剪后只有 326×184 像素，而字号是按 960 宽的画面定的。
        结果信息条文字画到画面外 —— 图里只剩"第 14 帧 · 0.47s · 着地 ·
        加速段 · 第"，后面的"1 步（阶段为推断值）"全被切掉了。

        教练看到一条被切断的文字，会以为信息本身有问题。

        按比例缩放能让文字在任何尺寸的图上都完整显示。
        下限 0.34 是经验值 —— 再小就认不清了，那时宁可少显示几个字。
    """
    scale = base * (img_w / ref_w)
    return max(0.34, min(base, scale))


def _text_size(text: str, scale: float) -> tuple[int, int]:
    (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    return w, h


def _draw_text_fitted(img, text: str, x: int, y: int, scale: float,
                      color, max_w: int) -> None:
    """
    画一行文字，保证不超出 max_w。

    超出时**逐字截断并加省略号** —— 而不是让它画到画面外。
    截断比溢出好：溢出会让教练看到半句话，还以为信息本身有问题。
    """
    shown = text
    if _text_size(shown, scale)[0] > max_w:
        for cut in range(len(text) - 1, 2, -1):
            cand = text[:cut] + "…"
            if _text_size(cand, scale)[0] <= max_w:
                shown = cand
                break

    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        cv2.putText(img, shown, (x + dx, y + dy),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, _C_BLACK, 3,
                    cv2.LINE_AA)
    cv2.putText(img, shown, (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)


def _draw_caption(img, req: KeyframeRequest, time_s: float,
                  step_total: int) -> None:
    """
    左上角信息条：这是第几帧、什么事件、第几步、什么时刻。

    为什么必须有：教练看到一张图，第一个问题是
    「这是什么时候的？」—— 不告诉他，这张图就没法用。
    """
    h, w = img.shape[:2]
    event_zh = {"touchdown": "着地", "midstance": "支撑中期",
                "toe_off": "离地", "block_clearance": "离器",
                "set_position": "各就位", "gun_fire": "枪响",
                "swing_peak": "摆动最高", "finish": "冲线"}
    phase_zh = {"set": "各就位", "start": "起动", "acceleration": "加速段",
                "transition": "过渡", "max_velocity": "最高速度",
                "deceleration": "减速"}

    parts = [f"第 {req.frame_index} 帧",
             f"{time_s:.2f}s",
             event_zh.get(req.event, req.event),
             phase_zh.get(req.phase, req.phase)]
    if req.step_index:
        parts.append(f"第 {req.step_index} 步")

    text = "  ·  ".join(parts)

    # ⚠️ 字号必须按图片宽度缩放。
    #    远景素材裁剪后只有 326 像素宽，而字号是按 960 宽定的 ——
    #    不缩放的话文字会画到画面外，教练看到半句话。
    fs = _fit_font_scale(w)
    margin = max(6, int(w * 0.02))
    avail = w - margin * 2

    # 半透明底条。高度也跟着字号走，否则小图上底条会显得很厚。
    bar_h = int(_text_size("测", fs)[1] * 2.0) + 10
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), _C_BLACK, -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)

    _draw_text_fitted(img, text, margin, int(bar_h * 0.72), fs,
                      _C_WHITE, avail)

    # 「阶段为推断值」单独一行 —— 它是**警告**，不该混在信息里被截断。
    # 阶段是推断的时候必须说清楚：不标的话教练会以为这确实是最高速度阶段，
    # 然后拿起跑姿势去对照最高速度的标准值。
    if not req.phase_is_exact:
        _draw_text_fitted(img, "阶段为推断值",
                          margin, bar_h + int(bar_h * 0.8), fs,
                          (80, 200, 255), avail)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def render_keyframes(
    ctx,
    video_path: Path,
    out_dir: Path,
    metric_results: list | None = None,
    url_prefix: str = "keyframes",
) -> list[dict]:
    """
    生成关键帧图片，返回可写入报告的 keyframes 数组。

    参数
    ----
    ctx : MetricContext
    video_path : 原始视频。关键帧图必须从**原视频**取帧 ——
                 不能从姿态数据重绘，那样会丢失真实背景，
                 教练就认不出是哪个场地、哪个运动员。
    out_dir : 图片输出目录
    metric_results : compute_all_metrics 的结果。用于取该帧要标注的角度值。
    url_prefix : 写进报告的相对路径前缀，由服务端拼成完整 URL

    返回
    ----
    契约 Keyframe 对象的列表。生成失败的帧**不写入**，
    而不是写一条 image_url 指向不存在的文件。
    """
    requests = select_keyframes(ctx, metric_results)
    if not requests:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)

    # 视频帧号 -> 目标帧集合
    want = {r.frame_index: r for r in requests}

    # 尺度：逐帧优先，退回全局中位数
    from .metrics import _resolve_pixels_per_meter
    global_ppm = _resolve_pixels_per_meter(ctx)

    fps = ctx.fps or 30.0
    frames_by_index = {f.frame_index: f for f in ctx.seq.frames}

    # 复用 cli 的骨架绘制（含质量码可视化与黑色描边）
    from .cli import draw_pose

    results: list[dict] = []
    for idx, bgr in iter_frames(video_path):
        req = want.get(idx)
        if req is None:
            continue

        pf: PoseFrame | None = frames_by_index.get(idx)
        if pf is None:
            continue

        # ---- 先画骨架 ----
        img = draw_pose(bgr, pf.keypoints, show_quality=True)

        ppm = None
        if getattr(ctx.scale, "per_frame", None):
            ppm = ctx.scale.per_frame.get(idx) or global_ppm
        else:
            ppm = global_ppm

        # ---- 角度弧先画在**未裁剪**的画面上（坐标系正确）----
        # 然后在裁剪时连同画面一起带走，位置自然还是对的。
        #
        # ⚠️ 顺序上踩过两次坑，所以写清楚：
        #   ① 不能「裁剪后再用原始关键点画标注」—— 裁剪改变了坐标系，
        #      按原图尺寸算出的像素位置会全部偏移。
        #   ② 不能「先画文字条再裁剪」—— 信息条在左上角，会被裁掉一半
        #      （实际发生过：图里只剩"加速段·第"）。
        #   正确顺序是：骨架 → 角度弧 → 裁剪 → 信息条与尺度条。
        h, w = img.shape[:2]
        slot = 0
        for ann in req.annotations:
            pts = _joint_angle_points(ann["metric_id"], pf.keypoints, w, h)
            if pts is None:
                continue
            _draw_angle_arc(img, pts[0], pts[1], pts[2],
                            ann["value"], ann["unit"], label_slot=slot)
            slot += 1

        # ---- 裁到运动员附近 ----
        # 远景素材里人只占画面 1/5，骨架和角弧挤成一团看不清。
        # 裁剪只影响显示 —— 指标早已用归一化坐标算完，不受影响。
        img = _crop_to_athlete(img, pf.keypoints)

        # ---- 信息条与尺度条画在**裁剪后**的画面上 ----
        # 这样它们永远在可视区域内，且不受裁剪范围影响。
        _draw_scale_bar(img, ppm)
        _draw_caption(img, req, idx / fps, len(ctx.events.touchdowns))

        # 文件名用帧号，稳定且可读 —— 出问题时能直接从文件名定位
        fname = f"f{idx:06d}_{req.event}.jpg"
        fpath = out_dir / fname
        ok = cv2.imwrite(str(fpath),
                         img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok or not fpath.exists():
            # 写不出图就不写进报告 —— 报告里指向不存在的文件比没有更糟
            continue

        results.append({
            "frame_index": req.frame_index,
            "event": req.event,
            "side": req.side,
            "step_index": req.step_index,
            "phase": req.phase,
            "image_url": f"{url_prefix}/{fname}",
            "pixels_per_meter": round(ppm, 2) if ppm else None,
            "annotations": req.annotations,
            # 阶段是否为推断值。契约里没有这个字段，
            # 所以只在**图片上**标注，不写进报告 ——
            # 写了会让 analysis 契约校验失败（additionalProperties: false）。
        })

    results.sort(key=lambda k: k["frame_index"])
    return results
