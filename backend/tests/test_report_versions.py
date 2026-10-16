"""
报告版本信息的测试。

## 这一段锁定一个真实缺陷（2026-10-11）

`report.py` 里的 `VERSIONS["model_version"]` 曾经**硬编码** "yolov8n-pose"。
于是用 `--estimator rtm` 跑分析时，报告里仍然写着 `yolov8n-pose` ——
**报告谎报了用了哪个模型**。

这违反 P12（一切版本化）。那个字段存在的意义就写在它自己的注释里：

    写入报告用于回答"为什么这次和上次不一样"

报错的版本号等于回答不了这个问句。
更糟的是它**不会报错** —— 报告看起来完全正常。

讽刺的是 `PoseSequence` 本来就带着 `estimator_name` / `estimator_version`，
信息一直在手边，只是没接上。

## 附带一个契约问题

`build_versions()` 在没有提取器信息时返回 "unknown"，
而契约 `analysis.schema.json` 的 `model_version` 是 `type: string` 且无枚举限制
—— 所以 "unknown" 是合法的，不会触发契约门失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis.pose_types import PoseSequence  # noqa: E402
from backend.analysis.report import VERSIONS, build_versions  # noqa: E402


def test_model_version_comes_from_sequence():
    """model_version 必须来自实际使用的提取器。"""
    seq = PoseSequence(estimator_name="rtmpose-halpe26",
                       estimator_version="0.0.16")
    v = build_versions(seq)
    assert v["model_version"] == "rtmpose-halpe26 0.0.16"


def test_model_config_distinguishes_weights_resolution_and_rtm_mode():
    configs = ["weights=yolov8n-pose.pt; imgsz=960",
               "weights=yolov8s-pose.pt; imgsz=960",
               "weights=yolov8n-pose.pt; imgsz=1280",
               "mode=lightweight", "mode=balanced"]
    versions = [build_versions(PoseSequence(
        estimator_name="pose", estimator_version="1", model_config=c
    ))["model_version"] for c in configs]
    assert len(set(versions)) == len(configs)
    for config, version in zip(configs, versions):
        assert config in version


def test_switching_estimator_changes_model_version():
    """
    换提取器，报告里的 model_version 必须跟着变。

    这是缺陷的核心：旧实现下两次跑出来的 model_version 一模一样，
    尽管实际用的是两个不同的模型。
    """
    yolo = PoseSequence(estimator_name="yolov8-pose",
                        estimator_version="8.4.173")
    rtm = PoseSequence(estimator_name="rtmpose-halpe26",
                       estimator_version="0.0.16")
    assert build_versions(yolo)["model_version"] != \
        build_versions(rtm)["model_version"]


def test_unknown_when_no_estimator_recorded():
    """
    没有提取器信息时写 unknown，**不冒充某个具体模型**。

    宁可说"不知道"也不要填一个看起来合理但是猜的值 ——
    这正是 P10 的取向。
    """
    seq = PoseSequence()
    v = build_versions(seq)
    assert v["model_version"] == "unknown"
    # 不能退化成硬编码的某个模型名
    assert "yolov8" not in v["model_version"]
    assert "rtm" not in v["model_version"]


def test_name_only_estimator():
    """只有名字没有版本号时，不该输出多余空格。"""
    seq = PoseSequence(estimator_name="some-model", estimator_version="")
    assert build_versions(seq)["model_version"] == "some-model"


def test_blank_name_is_unknown():
    """名字是空白字符串时也算 unknown。"""
    seq = PoseSequence(estimator_name="   ", estimator_version="1.0")
    assert build_versions(seq)["model_version"] == "unknown"


def test_other_versions_still_present():
    """algo / rule / std 版本不受影响，仍是原有常量。"""
    v = build_versions(PoseSequence(estimator_name="x", estimator_version="1"))
    for key in ("algo_version", "rule_version", "std_version"):
        assert v[key] == VERSIONS[key], key


def test_versions_dict_no_longer_hardcodes_model():
    """
    VERSIONS 本身不该再含 model_version —— 它是常量表，
    放进去就必然与实例脱节。
    """
    assert "model_version" not in VERSIONS, (
        "model_version 必须来自实例（PoseSequence），不能放常量表里"
    )
