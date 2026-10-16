"""
分析请求里的姿态模型参数：白名单解析。

服务端 /api/analyze 只接受这里的合法组合，避免任意路径或未知权重。
"""

from __future__ import annotations

from typing import Any

ALLOWED_ESTIMATORS = frozenset({"yolo", "rtm"})
ALLOWED_YOLO_MODELS = frozenset({
    "yolov8n-pose.pt",
    "yolov8s-pose.pt",
    "yolov8m-pose.pt",
    "yolov8l-pose.pt",
})
ALLOWED_IMGSZ = frozenset({640, 960, 1280})
ALLOWED_RTM_MODES = frozenset({"lightweight", "balanced", "performance"})

DEFAULT_ESTIMATOR = "yolo"
DEFAULT_MODEL = "yolov8n-pose.pt"
DEFAULT_IMGSZ = 960
DEFAULT_RTM_MODE = "lightweight"


class PoseOptionsError(ValueError):
    """参数不合法。"""


def pose_options_from_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """
    从 /api/analyze 的 JSON 解析姿态选项。

    返回键：estimator, model_name, imgsz, rtm_mode
    """
    p = params or {}

    raw_est = p.get("estimator")
    if raw_est is None or raw_est == "":
        estimator = DEFAULT_ESTIMATOR
    else:
        estimator = str(raw_est).strip().lower()
        if estimator not in ALLOWED_ESTIMATORS:
            raise PoseOptionsError(
                f"estimator 必须是 {sorted(ALLOWED_ESTIMATORS)} 之一，"
                f"收到 {raw_est!r}"
            )

    raw_model = p.get("model")
    if raw_model is None or raw_model == "":
        model_name = DEFAULT_MODEL
    else:
        model_name = str(raw_model).strip()
        if model_name not in ALLOWED_YOLO_MODELS:
            raise PoseOptionsError(
                f"model 不在允许列表中：{sorted(ALLOWED_YOLO_MODELS)}"
            )

    raw_imgsz = p.get("imgsz")
    if raw_imgsz is None or raw_imgsz == "":
        imgsz = DEFAULT_IMGSZ
    else:
        if isinstance(raw_imgsz, bool) or isinstance(raw_imgsz, float):
            raise PoseOptionsError("imgsz 必须是整数")
        try:
            imgsz = int(raw_imgsz)
        except (TypeError, ValueError, OverflowError) as e:
            raise PoseOptionsError("imgsz 必须是整数") from e
        if imgsz not in ALLOWED_IMGSZ:
            raise PoseOptionsError(
                f"imgsz 必须是 {sorted(ALLOWED_IMGSZ)} 之一"
            )

    raw_mode = p.get("rtm_mode")
    if raw_mode is None or raw_mode == "":
        rtm_mode = DEFAULT_RTM_MODE
    else:
        rtm_mode = str(raw_mode).strip().lower()
        if rtm_mode not in ALLOWED_RTM_MODES:
            raise PoseOptionsError(
                f"rtm_mode 必须是 {sorted(ALLOWED_RTM_MODES)} 之一"
            )

    if estimator == "rtm" and raw_model not in (None, ""):
        # 避免误以为 YOLO 权重会被 RTM 使用
        raise PoseOptionsError("estimator 为 rtm 时不要传 model")

    return {
        "estimator": estimator,
        "model_name": model_name,
        "imgsz": imgsz,
        "rtm_mode": rtm_mode,
    }
