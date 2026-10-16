"""
完整分析管线：视频 -> 分析报告。

两个入口共用同一个 run_pipeline()：
    · CLI   `python -m backend.analysis.analyze <视频>`
    · 服务端 backend/server/app.py 在后台线程里调用

共用是刻意的：如果 CLI 与服务端各写一套流程，两者迟早会演化出
不一致的行为（一边加了帧率校验、另一边忘了），而这类差异极难发现。

⚠️ 关于模块内相对导入（from .metrics import ...）：
    本模块**必须作为包的一部分**被导入，不能直接 `python analyze.py` 运行。
    直接运行会因为缺少父包上下文而报 "attempted relative import"。
    CLI 用法是 `python -m backend.analysis.analyze`，
    从任意目录跑则由 `-m` 的搜索路径决定 —— 见文件末尾的路径引导。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ..paths import apply_env_defaults, ensure_cache_dirs

# ⚠️ 必须在导入 torch / ultralytics 之前设置缓存路径 ——
#    它们在 import 时就读环境变量决定往哪写，晚一步就已经写到 C 盘了，
#    而且不会报错。
apply_env_defaults()
ensure_cache_dirs()

from .metrics import MetricContext, compute_all_metrics
from .phases import detect_gait_events, detect_phases
from .pose_estimator import YoloPoseEstimator
from .reference_scale import estimate_reference_scale
from .report import ReportInputs, build_report, write_report
from .video_io import estimate_camera_motion, iter_frames, read_video_info

# 进度回调签名：(0–1 的比例, 阶段说明)
ProgressFn = Callable[[float, str], None]


def _build_estimator(
    which: str,
    model_name: str,
    imgsz: int,
    *,
    rtm_mode: str = "lightweight",
):
    """
    按名字构造姿态提取器。

    为什么要有这一层：姿态模型是本项目最可能被替换的一环
    （见 pose_types.PoseEstimator 的说明）。集中在一处选择，
    将来加新模型只改这里的表，不动主管线。

    ⚠️ 默认仍是 'yolo'。换模型会改变数值结果，
       所以必须**显式指定** —— 不能让历史报告的数字被静默改变。

    可选值
    ------
    'yolo' : YOLOv8-pose，COCO-17，**无足部点**（由几何推导）
    'rtm'  : rtmlib 的 RTMPose + Halpe26，**含实测足部点**
    """
    if which in ("yolo", "yolov8", "yolov8-pose"):
        return YoloPoseEstimator(model_name=model_name, imgsz=imgsz)
    if which in ("rtm", "rtmpose", "halpe26"):
        # 延迟导入：rtmlib 是换模型时的可选依赖，
        # 没装也不该影响默认路径（否则整个引擎都起不来）。
        from .pose_estimator_rtm import RtmPoseEstimator
        return RtmPoseEstimator(mode=rtm_mode)
    raise ValueError(
        f"未知的姿态提取器 '{which}'。可选：yolo（默认，无足部点）、"
        f"rtm（rtmlib Halpe26，含足部点）。"
    )


def run_pipeline(
    video_path: Path,
    *,
    athlete_id: str = "at_local",
    athlete_name: str = "未署名",
    gender: str = "male",
    event: str = "100m",
    level: str = "college",
    height_cm: float | None = None,
    athlete_age: float | None = None,
    running_condition: str | None = None,
    load_protocol: str | None = None,
    complete_run: bool = False,
    population_confirmed: bool = False,
    view: str = "side",
    test_type: str = "acceleration",
    camera_distance_m: float | None = None,
    camera_height_m: float | None = None,
    has_lane_line: bool | None = None,
    camera_followed: bool | None = None,
    session_id: str | None = None,
    team_id: str = "t_local",
    model_name: str = "yolov8n-pose.pt",
    imgsz: int = 960,
    estimator: str = "yolo",
    rtm_mode: str = "lightweight",
    manual_review: dict | None = None,
    target_selection: dict | None = None,
    max_frames: int | None = None,
    keyframe_dir: Path | str | None = None,
    keyframe_url_prefix: str = "keyframes",
    progress: ProgressFn | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    """
    跑完整分析，返回报告 dict。

    参数
    ----
    keyframe_dir : 关键帧图片输出目录。为 None 时不生成关键帧图
                   （报告里 keyframes 为空数组）。
    keyframe_url_prefix : 写进 image_url 的路径前缀。
                   服务端负责把它拼成完整 URL —— 分析引擎不知道
                   也不该知道自己被哪个地址访问。
    progress : 进度回调，用于服务端向 App 报告进度。
               不传则静默运行（CLI 用 print 自己处理）。
    log : 日志回调。服务端把日志收进任务记录供排查。

    异常
    ----
    视频无法读取、模型加载失败等会抛异常，由调用方决定怎么呈现。
    """
    def emit(pct: float, stage: str) -> None:
        if progress is not None:
            progress(pct, stage)

    def say(msg: str) -> None:
        if log is not None:
            log(msg)

    t_start = time.time()
    p = Path(video_path)

    # ---- 1. 视频信息与帧率校验 ----
    emit(0.02, "读取视频信息")
    info = read_video_info(p)
    say(f"视频 {info.resolution_label} {info.frame_count} 帧 "
        f"{info.duration_s:.1f} 秒，帧率校验 {info.fps_verification.status}")

    target = None
    if target_selection is not None:
        from .target_lock import validate_target
        target = validate_target(target_selection, info.frame_count)
        if view != "side" or camera_followed is not False:
            raise ValueError("人物锁定首版仅支持固定侧面；请确认没有跟拍")
        if max_frames is not None and target["end_frame"] >= max_frames:
            raise ValueError("分析帧数上限未覆盖所选人物区间")

    if manual_review is not None:
        from .manual_timing import inspect_video, validate_review
        from .pose_types import PoseSequence
        from .phases import GaitEvents
        from .reference_scale import ScaleEstimate
        metadata = inspect_video(p)
        labels = validate_review(manual_review, metadata, view=view, camera_followed=camera_followed)
        if target is not None and any(not target["frame"] <= e["frame"] <= target["end_frame"] for e in labels):
            raise ValueError("人工事件超出选定人物的分析区间")
        fps = metadata["fps"]
        info.fps_verified = fps
        info.duration_s = metadata["frame_count"] / fps
        info.fps_verification.verified = fps
        info.fps_verification.status = "verified"
        # No model selection, inferred feet, geometry, scale or inferred phase
        # enters the manual timing path.
        seq = PoseSequence(estimator_name="manual-contact", estimator_version="1.0.0")
        events = GaitEvents(touchdowns=[e["frame"] for e in labels if e["type"] == "touchdown"],
                            toe_offs=[e["frame"] for e in labels if e["type"] == "toe_off"],
                            method="manual_side_v1")
        scale = ScaleEstimate(method="none", valid_per_frame=False)
        phases = []
        motion_level, motion_shift = "fixed", 0.0
        emit(.85, "按人工确认事件计算时间指标")
    else:
        # ---- 2. 镜头运动 ----
        emit(0.08, "检测镜头运动")
        motion_level, motion_shift, motion_notes = estimate_camera_motion(p)
        for n in motion_notes:
            say(n)

        # ---- 3. 姿态提取（耗时最长，占整体 90% 以上）----
        emit(0.12, "加载姿态模型")
        est = _build_estimator(estimator, model_name, imgsz, rtm_mode=rtm_mode)
        say(f"姿态提取器 {est.name}，推理设备 {getattr(est, 'device', '?')}")
        if est.provides_foot_keypoints:
            say("该模型提供实测足部关键点（heel/toe 不再几何推导）")

        frames_iter = iter_frames(
            p, start=target["frame"] if target else 0,
            end=target["end_frame"]+1 if target else max_frames)

        if target is not None:
            from .target_lock import AthleteLock
            est.target_lock = AthleteLock(target)

        emit(0.20, "提取姿态")
        extraction_complete = False
        try:
            seq = est.estimate_sequence(frames_iter)
            if target is not None:
                expected = target["end_frame"] - target["frame"] + 1
                if len(est.target_lock.records) != expected:
                    raise ValueError("解码提前结束，未覆盖完整选人区间，不生成报告")
            extraction_complete = True
        finally:
            if target is not None and keyframe_dir is not None:
                import json
                dest = Path(keyframe_dir)
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "target_tracking.json").write_text(json.dumps({
                    "selection": target, "method": "position_velocity_hsv_v1",
                    "frames": est.target_lock.records,
                    "status": "lost" if est.target_lock.failed else ("completed" if extraction_complete else "incomplete"),
                }, ensure_ascii=False, indent=2), encoding="utf-8")
        if target is not None:
            seq.model_config += "; target_lock=position_velocity_hsv_v1"
        say(f"姿态提取完成：{len(seq)} 帧")

        # ---- 4. 参考尺度 ----
        emit(0.75, "估计参考尺度")
        # 采样若干帧用于分道线检测 —— 不必每帧都检，检测本身有开销，
        # 而分道线是静态参照物，采样足够。
        sample_idx = {
            f.frame_index for f in seq.frames[::max(1, len(seq) // 20)]
        }
        sample_frames: dict = {}
        for idx, bgr in iter_frames(
                p, end=None if max_frames is None else max_frames):
            if idx in sample_idx:
                sample_frames[idx] = bgr

        scale = estimate_reference_scale(
            seq, athlete_height_cm=height_cm, frames_by_index=sample_frames)
        say(f"参考尺度来源：{scale.method}")

        # ---- 5. 事件与相位 ----
        emit(0.85, "检测步态事件与相位")
        fps = info.fps_verified or info.fps_declared or 30.0
        events = detect_gait_events(seq, fps=fps)
        phases, phase_notes = detect_phases(seq, fps=fps)
        say(f"检出支撑中期 {len(events.midstances)} 次、"
            f"着地 {len(events.touchdowns)} 次；划分相位 {len(phases)} 段")

    # ---- 6. 组装报告 ----
    emit(0.88, "计算指标")
    inputs = ReportInputs(
        video=info,
        seq=seq,
        scale=scale,
        events=events,
        phases=phases,
        camera_motion_level=motion_level,
        camera_motion_shift=motion_shift,
        athlete_id=athlete_id,
        athlete_name=athlete_name,
        athlete_gender=gender,
        athlete_event=event,
        athlete_level=level,
        athlete_height_cm=height_cm,
        athlete_age=athlete_age,
        running_condition=running_condition,
        load_protocol=load_protocol,
        complete_run=complete_run and max_frames is None and target is None,
        population_confirmed=population_confirmed,
        session_id=session_id or f"s_{p.stem}",
        team_id=team_id,
        test_type=test_type,
        view=view,
        camera_distance_m=camera_distance_m,
        camera_height_m=camera_height_m,
        has_lane_line=has_lane_line,
        camera_followed=camera_followed,
    )

    # 先建上下文与指标 —— 关键帧需要指标值来画角度标注，
    # 所以这一步必须排在渲染之前。上下文随后传给 build_report 复用，
    # 避免重复构造（compute_all_metrics 是整条链路里第二耗时的步骤）。
    ctx = MetricContext(
        seq=seq, fps=fps, view=view, scale=scale,
        events=events, phases=phases,
        athlete_height_cm=height_cm,
        camera_motion_level=motion_level,
        camera_motion_shift=motion_shift,
    )
    ctx.athlete_gender = gender if population_confirmed else None
    ctx.athlete_event = event if population_confirmed else None
    ctx.athlete_level = level if population_confirmed else None
    ctx.athlete_age = athlete_age
    ctx.running_condition = running_condition
    ctx.load_protocol = load_protocol
    ctx.complete_run = complete_run and max_frames is None and target is None
    ctx.manual_events = labels if manual_review is not None else None
    metric_results = compute_all_metrics(ctx)

    # ---- 7. 关键帧图片 ----
    kf: list[dict] = []
    if keyframe_dir is not None and manual_review is not None:
        from .manual_timing import read_frame
        dest = Path(keyframe_dir)
        dest.mkdir(parents=True, exist_ok=True)
        # Show original event frames, never a guessed skeleton or angle.
        for e in labels[:12]:
            name = f"f{e['frame']:06d}_{e['type']}.jpg"
            (dest / name).write_bytes(read_frame(p, e["frame"]))
            kf.append({"frame_index": e["frame"], "event": e["type"],
                       "side": "L" if e["side"] == "left" else "R",
                       "phase": "whole_run", "annotations": [],
                       "image_url": f"{keyframe_url_prefix}/{name}"})
    if keyframe_dir is not None and manual_review is None:
        emit(0.94, "生成关键帧图")
        try:
            from .keyframes import render_keyframes
            kf = render_keyframes(
                ctx, p, Path(keyframe_dir),
                metric_results=metric_results,
                url_prefix=keyframe_url_prefix,
            )
            say(f"生成关键帧 {len(kf)} 张")
        except Exception as e:      # noqa: BLE001
            # 关键帧是**锦上添花**，不该让整条分析失败。
            # 报告里保留空数组，App 那边会显示"本次未生成关键帧图"。
            say(f"关键帧生成失败（不影响报告）：{type(e).__name__}: {e}")

    emit(0.97, "组装报告")
    report = build_report(inputs, ctx=ctx, keyframes=kf)
    if target is not None:
        previous_note = report["session"]["camera_motion"].get("note", "")
        report["session"]["camera_motion"]["note"] = previous_note + (
            f" 人工选定运动员及区间 {target['frame']}–{target['end_frame']} 帧。"
            + ("人工计时，身份由标注者逐帧核对，未运行自动跟踪。" if manual_review is not None
               else "采用位置、运动连续性与衣着直方图关联；不是身份识别认证。"))

    # ⚠️ 不要把耗时之类的服务端诊断信息塞进 report。
    #
    # 契约对 analysis 用了 additionalProperties: false，多一个字段就校验失败。
    # 而且从设计上也不该混：report 是"分析结论"，属于契约数据；
    # 耗时是服务端的运行信息，由 /api/jobs 的 elapsed_s 返回。
    #
    # 这一点是契约校验抓出来的 —— 曾经加了 server_elapsed_s 字段。
    emit(1.0, "完成")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="视频 -> 完整跑姿分析报告 JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, default=Path("output"))
    ap.add_argument("--model", default="yolov8n-pose.pt")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument(
        "--estimator", default="yolo",
        choices=["yolo", "rtm"],
        help="姿态提取器。yolo=YOLOv8-pose（无足部点，默认）；"
             "rtm=rtmlib Halpe26（含实测趾尖/足跟，换它会改变数值结果）",
    )
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--rtm-mode", default="lightweight",
                    choices=["lightweight", "balanced", "performance"])

    ap.add_argument("--athlete-id", default="at_local")
    ap.add_argument("--athlete-name", default="未署名")
    ap.add_argument("--gender", default=None, choices=["male", "female"])
    ap.add_argument("--event", default=None)
    ap.add_argument("--level", default=None,
                    choices=["elite", "sub_elite", "college",
                             "high_school", "amateur"])
    ap.add_argument("--height", type=float, default=None,
                    help="身高 cm。位移类指标需要它，或让分道线入镜")
    ap.add_argument("--athlete-age", type=float, default=None)
    ap.add_argument("--running-condition", choices=["unloaded", "resisted", "assisted"])
    ap.add_argument("--load-protocol", default=None, help="具体负荷方案，与参考库标识一致")
    ap.add_argument("--complete-run", action="store_true", help="确认素材涵盖完整专项距离")

    ap.add_argument("--view", default="side",
                    choices=["side", "front", "back"])
    ap.add_argument("--test-type", default="acceleration",
                    choices=["block_start", "acceleration",
                             "max_velocity", "speed_endurance"])
    ap.add_argument("--camera-distance", type=float, default=None)
    ap.add_argument("--camera-height", type=float, default=None)
    ap.add_argument("--has-lane-line", action="store_true", default=None)
    ap.add_argument("--camera-followed", action="store_true", default=None)

    ap.add_argument("--session-id", default=None)
    ap.add_argument("--team-id", default="t_local")
    ap.add_argument("--quiet", action="store_true")

    args = ap.parse_args()

    def out(msg: str = "") -> None:
        if not args.quiet:
            print(msg)

    if not args.video.exists():
        print(f"[FAIL] 视频不存在：{args.video}")
        return 1

    # 计时放在这里而不是复用 run_pipeline 内部的 t_start ——
    # 后者是那个函数作用域里的局部变量。
    # （重构时曾经漏掉这一处，报 NameError，而错误信息被控制台编码问题盖住了。）
    t_start = time.time()

    out("=" * 68)
    out("跑姿分析")
    out("=" * 68)
    out()

    last_stage = [""]

    def on_progress(pct: float, stage: str) -> None:
        if stage != last_stage[0]:
            last_stage[0] = stage
            out(f"  [{pct * 100:3.0f}%] {stage}")

    try:
        report = run_pipeline(
            video_path=args.video,
            athlete_id=args.athlete_id,
            athlete_name=args.athlete_name,
            gender=args.gender or "male",
            event=args.event or "100m",
            level=args.level or "college",
            population_confirmed=all((args.gender, args.event, args.level)),
            height_cm=args.height,
            athlete_age=args.athlete_age,
            running_condition=args.running_condition,
            load_protocol=args.load_protocol,
            complete_run=args.complete_run,
            view=args.view,
            test_type=args.test_type,
            camera_distance_m=args.camera_distance,
            camera_height_m=args.camera_height,
            has_lane_line=args.has_lane_line,
            camera_followed=args.camera_followed,
            session_id=args.session_id,
            team_id=args.team_id,
            model_name=args.model,
            imgsz=args.imgsz,
            estimator=args.estimator,
            rtm_mode=args.rtm_mode,
            max_frames=args.max_frames,
            progress=on_progress,
            log=lambda s: out(f"        {s}"),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {type(e).__name__}: {e}")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / f"{args.video.stem}_analysis.json"
    write_report(report, json_path)

    out()
    out(f"已写出 {json_path}")
    out()

    # ---- 摘要 ----
    out("=" * 68)
    out("结果摘要")
    out("=" * 68)
    out()
    out(f"数据质量分：{report['quality_score']}")
    out(f"总览：{report['summary']['headline']}")
    out()

    computed = [m for m in report["metrics"] if not m.get("insufficient")]
    skipped = [m for m in report["metrics"] if m.get("insufficient")]

    if computed:
        out(f"算出数值的指标（{len(computed)} 项）：")
        for m in computed:
            flag = "" if m["reliable"] else "  (低置信)"
            out(f"  [OK] {m['name_zh']:16s} {m['value']} {m['unit']}{flag}")
        out()

    if skipped:
        out(f"数据不足的指标（{len(skipped)} 项）：")
        for m in skipped:
            ins = m["insufficient"]
            out(f"  [--] {m['name_zh']:16s} {ins['actual'][:44]}")
        out()

    if report["findings"]:
        out(f"结论（{len(report['findings'])} 条）：")
        for f in report["findings"]:
            out(f"  [{f['severity']}] {f['title']}")
    else:
        out("结论：无（没有可用标准值，或各项均在参考区间内）")
    out()
    out(f"总耗时 {time.time() - t_start:.1f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
