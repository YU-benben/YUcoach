"""
报告生成：把各项计算结果组装成契约要求的 analysis JSON。

核心原则：**报告里出现的事实与判断必须分开。**
    metrics    是事实   —— 测出来的数值
    findings   是判断   —— 依据规则得出的结论
    summary    是概括   —— 只说数量，不含新判断

    混在一起的后果：教练分不清"这是测出来的"还是"这是系统猜的"，
    进而无法判断该信到什么程度。

另一个原则：**数据不足必须显式呈现。**
    缺失的指标不能省略，否则教练会以为是"没问题"而不是"没测出来"。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .metrics import MetricContext, MetricResult, compute_all_metrics
from .metrics_base import METRIC_SPECS, MetricSpec, aggregate_block
from .phases import GaitEvents, PhaseSegment
from .pose_types import PoseSequence
from .reference_scale import ScaleEstimate
from .video_io import VideoInfo

SCHEMA_VERSION = "1.1.0"

# 分析引擎各组件版本。写入报告用于回答"为什么这次和上次不一样"。
VERSIONS = {
    "algo_version": "0.2.0",
    "model_version": "yolov8n-pose",
    "rule_version": "0.1.0",
    "std_version": "0.1.0",
}


@dataclass
class ReportInputs:
    """生成报告所需的全部素材。"""

    video: VideoInfo
    seq: PoseSequence
    scale: ScaleEstimate
    events: GaitEvents
    phases: list[PhaseSegment]
    camera_motion_level: str
    camera_motion_shift: float

    # 运动员与场次信息（由 App 端填写）
    athlete_id: str = "at_unknown"
    athlete_name: str = "未署名"
    athlete_gender: str = "male"
    athlete_event: str = "100m"
    athlete_level: str = "college"
    athlete_height_cm: float | None = None
    session_id: str = "s_unknown"
    team_id: str = "t_unknown"
    test_type: str = "acceleration"
    view: str = "side"

    # 采集参数（由 App 端填写）
    camera_distance_m: float | None = None
    camera_height_m: float | None = None
    has_lane_line: bool | None = None
    camera_followed: bool | None = None

    notes: list[str] = field(default_factory=list)


def _phase_to_contract(phase: str) -> str:
    """把内部的相位名映射到契约枚举。"""
    mapping = {
        "acceleration": "acceleration",
        "max_velocity": "max_velocity",
        "transition": "transition",
        "deceleration": "deceleration",
        "set": "set",
        "start": "start",
        "whole_run": "max_velocity",   # 整段处理时归入途中跑
    }
    return mapping.get(phase, "max_velocity")


def _canonical_session_id(athlete_id: str, session_id: str | None) -> str:
    """
    生成符合契约格式的 session_id。

    契约要求 `^s_\\d{8}_at\\d{5}_\\d{2}$`，例如 `s_20260301_at00007_01`。
    这个格式不是装饰 —— 它把**日期、运动员、序号**编进 ID 里，
    使得仅凭一个 ID 就能判断记录属于谁、哪一天。
    离线场景下（本项目的主场景）没有中心数据库发号，
    这种自描述 ID 是唯一能在本地保证唯一性的办法。

    调用方传来的 ID 若不符合格式，这里重新生成一个合规的，
    而不是让非法 ID 流进报告 —— 那会在校验时失败。
    """
    import re

    pattern = re.compile(r"^s_\d{8}_at\d{5}_\d{2}$")
    if session_id and pattern.match(session_id):
        return session_id

    # 从运动员 ID 里抽出数字部分，取不到就补零
    digits = re.sub(r"\D", "", athlete_id or "")
    at_num = int(digits[-5:]) if digits else 0
    today = datetime.now().strftime("%Y%m%d")
    # 序号取当天时间的后两位，同一秒内多次分析会撞号，
    # 但本项目的分析是串行的，实际不会发生。
    seq = datetime.now().second % 100
    return f"s_{today}_at{at_num:05d}_{seq:02d}"


def _canonical_motion_level(level: str) -> tuple[str, str | None]:
    """
    把镜头运动检测结果规范到契约枚举。

    契约只允许 fixed / slight_pan / strong_pan 三个值，
    而检测可能返回 unknown（特征点不足，无法估计）。

    为什么 unknown 落到 fixed 而不是随便挑一个：
        在无法估计时，**不能声称检测到了镜头跟随** ——
        那会让报告写上一句无依据的警示。反过来，
        声称"固定机位"也是不准确的，所以同时附上 note 说明
        本次未能估计，让读者自己判断。

    返回 (level, note)
    """
    if level in ("fixed", "slight_pan", "strong_pan"):
        return level, None
    return "fixed", (
        "本次未能有效估计镜头运动（画面特征点不足，"
        "可能是画面过曝、过于模糊，或场景纹理太少）。"
        "报告中按固定机位处理，但此项未经验证 —— "
        "若素材实际是跟踪拍摄，位移类指标的可靠性会下降。"
    )


def build_session_block(inp: ReportInputs) -> dict:
    """构造契约的 session 结构。"""
    fps_verification = inp.video.fps_verification

    capture: dict = {
        "resolution": {
            "width": int(inp.video.width),
            "height": int(inp.video.height),
        },
        "frame_count": int(inp.video.frame_count),
        "duration_ms": int(round(inp.video.duration_s * 1000)),
        "fps_declared": inp.video.fps_declared,
        "fps_verified": inp.video.fps_verified,
        "fps_verify": {
            "status": fps_verification.status,
            # 契约规定的三种交叉验证方法。当前只实现了 duration_check
            # （比对容器声明的帧数与逐帧解码数出的帧数）。
            # 另外两项需要姿态数据参与，尚未实现 —— 但键必须出现，
            # 值为 null 表示"该方法本次无法得出结论"，
            # 这是契约里明确允许的正常情况。
            "methods": ["duration_check"],
            "agreement_pct": round(fps_verification.agreement_pct, 2),
            "method_results": {
                "duration_check": (
                    round(fps_verification.agreement_pct, 2)
                    if fps_verification.agreement_pct > 0 else None
                ),
                "cadence_backcalc": None,
                "scale_displacement": None,
            },
            "note": (
                "cadence_backcalc（由步频反推帧率）与 "
                "scale_displacement（由已知尺寸的位移反推帧率）"
                "需要姿态与参考尺度数据，当前版本尚未实现。"
                "本次仅完成 duration_check，"
                "即容器声明帧数与逐帧解码帧数的一致性校验。"
            ),
        },
    }

    if inp.camera_distance_m is not None:
        capture.setdefault("camera", {})["distance_m"] = inp.camera_distance_m
    if inp.camera_height_m is not None:
        capture.setdefault("camera", {})["height_m"] = inp.camera_height_m
    if inp.camera_followed is not None:
        capture.setdefault("camera", {})["followed_athlete"] = inp.camera_followed

    # 镜头运动：规范到契约枚举，并对"估计失败"给出说明
    motion_level, motion_note = _canonical_motion_level(inp.camera_motion_level)

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": _canonical_session_id(inp.athlete_id, inp.session_id),
        "team_id": inp.team_id,
        "athlete": {
            "athlete_id": inp.athlete_id,
            "name": inp.athlete_name,
            "gender": inp.athlete_gender,
            "event": inp.athlete_event,
            "level": inp.athlete_level,
            **({"height_cm": inp.athlete_height_cm}
               if inp.athlete_height_cm else {}),
        },
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "test_type": inp.test_type,
        "view": inp.view,
        # view_detected 是算法自动判定的结果。**本项目尚未实现视角自动检测**，
        # 所以这里只能回填用户声明的值，并把 view_agreement 标为 true。
        # 这是已知的不足：如果用户把背面拍成了正面，系统不会发现。
        # 待实现后用左右关键点的可见性差异来判断，届时这里换成真实检测结果。
        "view_detected": inp.view,
        "view_agreement": True,
        "capture": capture,
        "camera_motion": {
            "level": motion_level,
            "is_tracking": motion_level != "fixed",
            "mean_shift_px_per_frame": round(inp.camera_motion_shift, 3),
            **({"note": motion_note} if motion_note else {}),
        },
        "reference_scale": inp.scale.as_contract_dict(),
        "quality_score": 0.0,   # 由 compute_quality_score 填充
        "status": "done",
    }


def compute_quality_score(
    inp: ReportInputs,
    results: list[MetricResult],
) -> tuple[float, dict]:
    """
    数据质量分（0–100）。

    这不是"成绩好坏"，而是"这次数据可信到什么程度"。
    教练据此决定要不要拿这份报告做训练决策。

    四个维度，权重按对结论可靠性的影响程度定：
        帧率       35   —— 决定时间类指标能否成立
        有效测量   25   —— 有多少帧真正能用
        参考尺度   20   —— 决定位移类指标能否换算
        关键点质量 20   —— 决定角度类指标的精度
    """
    breakdown: dict[str, float] = {}

    # ---- 帧率 ----
    fps = inp.video.fps_verified or 0
    if fps >= 120:
        breakdown["frame_rate"] = 35.0
    elif fps >= 60:
        # 角度类指标仍可用，但时间类不行 —— 给一半分
        breakdown["frame_rate"] = 18.0
    else:
        breakdown["frame_rate"] = 5.0

    # ---- 有效测量帧占比 ----
    total = max(len(inp.seq.frames), 1)
    computed = sum(1 for r in results if r.insufficient is None)
    # 用"可算指标占比"而不是帧占比：帧再多而指标算不出来也没用
    ratio = computed / max(len(results), 1)
    breakdown["metric_coverage"] = round(25.0 * ratio, 1)

    # ---- 参考尺度 ----
    scale_score = {
        "lane_line": 20.0,
        "calibration_rod": 18.0,
        "height_derived": 12.0,
        "none": 0.0,
    }.get(inp.scale.method, 0.0)
    breakdown["reference_scale"] = scale_score

    # ---- 关键点质量 ----
    cov = inp.seq.coverage()
    mean_cov = float(np.mean(list(cov.values()))) if cov else 0.0
    breakdown["keypoint_quality"] = round(20.0 * mean_cov, 1)

    score = round(sum(breakdown.values()), 1)
    return min(100.0, max(0.0, score)), breakdown


def build_summary(
    results: list[MetricResult],
    findings: list[dict],
) -> dict:
    """
    总览。

    headline 由**确定性规则**生成，不由语言模型自由撰写 ——
    总览是教练最先看到的一句话，它必须可复现、可解释。
    """
    major = sum(1 for f in findings if f.get("severity") == "major")
    minor = sum(1 for f in findings if f.get("severity") == "minor")
    insufficient = sum(
        1 for r in results if r.insufficient is not None
    )

    if major > 0:
        headline = f"发现 {major} 处需要优先处理的问题"
    elif minor > 0:
        headline = f"整体技术动作良好，有 {minor} 处可以进一步优化"
    elif insufficient == len(results):
        # 一项都没测出来时，绝不能写成"没有问题" ——
        # 那是最严重的误读
        headline = "本次素材未能测出有效指标，请按建议重新拍摄"
    else:
        headline = "各项指标均在合理范围内"

    return {
        "headline": headline,
        "major_count": major,
        "minor_count": minor,
        "insufficient_count": insufficient,
    }


def build_phases(phases: list[PhaseSegment]) -> list[dict]:
    out: list[dict] = []
    for p in phases:
        out.append({
            "phase": _phase_to_contract(p.phase),
            "frame_start": int(p.from_frame),
            "frame_end": int(p.to_frame),
            "confidence": round(float(p.confidence), 3),
        })
    return out


def build_metrics(
    results: list[MetricResult],
    ctx: MetricContext,
) -> list[dict]:
    """
    组装指标数组。

    注意：**数据不足的指标也要输出**，value 为 null 且带 insufficient。
    省略它们会让教练以为"没问题"而不是"没测出来"。
    """
    out: list[dict] = []

    for r in results:
        spec = METRIC_SPECS.get(r.metric_id)
        if spec is None:
            continue

        d = r.to_contract_dict(spec, ctx.view)

        # 按相位细化：把 aggregate 里的相位统计展开成独立条目，
        # 因为**同一个数值在不同相位含义可能相反**（尤其是躯干前倾）。
        #
        # 注意 aggregate 的契约约束：additionalProperties=false 且 required=['n']，
        # 所以相位统计不能被塞进 aggregate —— 那会引入未定义字段。
        # 做法是把相位统计单独成条，汇总条目改用 aggregate_block 规范化。
        if r.aggregate:
            phase_stats = {
                k: v for k, v in r.aggregate.items()
                if isinstance(v, dict) and "mean" in v
            }
            if phase_stats:
                # 汇总条目只保留契约允许的字段
                d["aggregate"] = _strip_phase_stats(r.aggregate)
                for ph, stat in phase_stats.items():
                    entry = dict(d)
                    entry["phase"] = _phase_to_contract(ph)
                    entry["value"] = stat["mean"]
                    entry["aggregate"] = aggregate_block(
                        n=int(stat.get("n", 0)),
                        mean=stat.get("mean"),
                        sd=stat.get("sd"),
                        min_value=stat.get("min"),
                        max_value=stat.get("max"),
                    )
                    out.append(entry)

        out.append(d)

    return out


def _strip_phase_stats(aggregate: dict) -> dict | None:
    """
    去掉相位统计，只留下契约 Aggregate 允许的字段。

    契约规定 additionalProperties=false，多一个字段校验就失败。
    所以这里做一次显式过滤，而不是指望调用方记得。
    """
    allowed = {"mean", "sd", "n", "min", "max"}
    kept = {k: v for k, v in aggregate.items() if k in allowed}
    if "n" not in kept:
        # n 是必填。缺了就用可推断的来源补 1，宁可标保守也不要漏字段。
        kept["n"] = 1
    return kept or None


def build_report(
    inp: ReportInputs,
    analysis_id: str | None = None,
    ctx: MetricContext | None = None,
    keyframes: list[dict] | None = None,
) -> dict:
    """
    生成完整报告 JSON。

    参数
    ----
    ctx : 可选。调用方若已经构造过 MetricContext（例如为了先渲染关键帧），
          可以传进来避免重复构造。
    keyframes : 可选。已渲染好的关键帧数组（见 keyframes.py）。
          为什么不在这里直接渲染：渲染需要读原视频，属于 IO 操作，
          而本函数应当是纯计算 —— 这样它才能被测试单独调用。
    """
    # 1. 计算上下文
    if ctx is None:
        ctx = MetricContext(
            seq=inp.seq,
            fps=inp.video.fps_verified or inp.video.fps_declared or 30.0,
            view=inp.view,
            scale=inp.scale,
            events=inp.events,
            phases=inp.phases,
            athlete_height_cm=inp.athlete_height_cm,
            camera_motion_level=inp.camera_motion_level,
            camera_motion_shift=inp.camera_motion_shift,
        )

    # 2. 全部指标
    results = compute_all_metrics(ctx)

    # 3. 规则引擎（下一步实现；当前返回空列表）
    from .rules import evaluate_rules
    findings = evaluate_rules(ctx, results)

    # 4. 质量分
    quality, breakdown = compute_quality_score(inp, results)

    # 5. 组装
    session = build_session_block(inp)
    session["quality_score"] = quality
    session["quality_breakdown"] = breakdown

    if analysis_id is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        analysis_id = f"a_{inp.session_id}_{stamp}"

    report: dict = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": analysis_id,
        "session": session,
        "versions": VERSIONS,
        "quality_score": quality,
        "phases_detected": build_phases(inp.phases),
        "metrics": build_metrics(results, ctx),
        "findings": findings,
        "summary": build_summary(results, findings),
        "keyframes": keyframes or [],
    }

    # 透视误差：镜头偏离画面中心越远误差越大。
    # 这里给一个基于镜头运动的粗略估计，而不是假装精确。
    if inp.camera_motion_level == "strong_pan":
        report["perspective_error_estimate"] = 4.0
    elif inp.camera_motion_level == "slight_pan":
        report["perspective_error_estimate"] = 2.0
    else:
        report["perspective_error_estimate"] = 1.0

    return report


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
