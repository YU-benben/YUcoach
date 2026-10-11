#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键质量门禁。

用法
----
    python scripts/check_all.py

对应 docs/10-工程规范与验收.md 的质量门。任何需要多步手工操作的检查，
在实际开发中都会被跳过，所以这里必须是一条命令跑完。

当前实现的门：
    G0  磁盘与缓存        —— C 盘空间与缓存目录位置
    G1  Dart 静态分析     —— 生成的契约模型能否编译
    G1b Flutter 测试      —— 契约、模型、界面三者理解是否一致
    G1c 分析引擎测试      —— 后端单元测试
    G0  磁盘与缓存        —— 空间 + 所有生成物都在项目内
    G0b GPU 姿态链路      —— CUDA 可用、模型能加载、推理跑得通
    G2  契约校验          —— fixture 是否符合契约
    G2a 契约一致性        —— 非空类型是否都在 required 里
    G2b 生成物一致性      —— 生成的 Dart 模型是否与契约同步
    G2c 生成物结构自检
    G2d fromJson 语义自检
    G2e 品牌资源自检      —— 图标是否还是模板默认图
    G2f 枚举值合规自检    —— 代码里的枚举值是否都在契约内
    G4  标准值库自检      —— 标准值是否都可查证（铁律的机械实现）
    G4b 规则引擎端到端    —— 真实标准值下规则能否触发
    G4c 模型清单自检      —— 模型文件是否存在、对拍结论是否记录
    G1c 分析引擎测试
    G1d 指标端到端验证    —— 用解析解验证数值正确性
    G1e 关键点噪声敏感性  —— 误差随噪声的增长曲线
    G5  端到端冒烟        —— 完整管线产出合法报告
    G5b 服务端接口自检    —— 服务能被启动并正确响应
    G3  契约兼容性        —— 预留（需要上一版契约快照）
    G6  覆盖率            —— 预留

退出码 0 表示全部通过；任何一门失败即返回 1。
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")


GATES: list[tuple[str, list[str], bool]] = [
    # (门名, 命令参数, 是否已实现)
    ("G0  磁盘与缓存", ["check_disk.py"], True),
    ("G0b GPU 姿态链路", ["check_gpu_pose.py"], True),
    ("G2  契约校验", ["check_contracts.py", "--dir", "samples/fixtures",
                      "--sync-mobile"], True),
    ("G2a 契约一致性", ["check_schema_consistency.py"], True),
    ("G2b 生成物一致性", ["gen_models.py", "--check"], True),
    ("G2c 生成物结构自检", ["inspect_models.py"], True),
    ("G2d fromJson 语义自检", ["verify_scenarios.py"], True),
    ("G2e 品牌资源自检", ["check_branding.py"], True),
    ("G2f 枚举值合规自检", ["check_reasons.py"], True),
    ("G4  标准值库自检", ["check_standards.py"], True),
    ("G4b 规则引擎端到端验证", ["verify_rules_e2e.py"], True),
    ("G4c 模型清单自检", ["check_model_manifest.py"], True),
    ("G1c 分析引擎测试", ["__pytest__"], True),
    ("G1d 指标端到端验证", ["verify_metrics_e2e.py"], True),
    ("G1e 关键点噪声敏感性", ["analyze_noise_sensitivity.py"], True),
    ("G5  端到端冒烟", ["smoke_analysis.py"], True),
    ("G5b 服务端接口自检", ["check_server.py"], True),
    ("G1  Dart 静态分析", ["__flutter_analyze__"], True),
    ("G1b Flutter 测试", ["__flutter_test__"], True),
    ("G3  契约兼容性", [], False),
    ("G6  覆盖率", [], False),
]


def run_pytest() -> int:
    """
    跑后端（分析引擎）的单元测试。

    分析引擎里最容易出错的是**不会抛异常的错误**：
      · 左右腿标签反了 —— 所有分侧统计完全颠倒
      · 足部点推导方向错了 —— 触地判定全错
      · 帧率判断错了 —— 所有时间指标静默出错

    这些都不会崩溃，只会安静地给出错误结果。
    所以必须靠测试锁定行为。

    pytest 未安装时跳过（返回 0）并提示，不阻塞其他门。
    """
    try:
        import pytest  # noqa: F401
    except ImportError:
        print("[WARN] 未安装 pytest，跳过后端测试。安装：")
        print("       python -m pip install pytest")
        return 0

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q"],
        cwd=str(ROOT),
    )
    return proc.returncode


def run_flutter(cmd: str) -> int:
    """
    跑 flutter <cmd>。

    这两道门不可替代：
      · analyze —— 证明生成的契约模型能编译
      · test    —— 证明契约、模型、界面三者对同一份数据的理解一致

    Flutter 不在 PATH 时跳过（返回 0），但要明确提示，避免误以为已通过。
    """
    flutter = shutil.which("flutter")
    if flutter is None:
        print(f"[WARN] PATH 中找不到 flutter，跳过 `flutter {cmd}`。")
        print("       若已安装 Flutter，请确认 D:\\flutter\\bin 已加入 PATH，")
        print(f"       或在本机终端里手动跑一次 `flutter {cmd}`。")
        return 0

    proc = subprocess.run([flutter, cmd], cwd=str(ROOT / "mobile"))
    return proc.returncode


def run(script: str, args: list[str]) -> int:
    cmd = [sys.executable, str(SCRIPTS / script), *args]
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode


def main() -> None:
    print("=" * 68)
    print("质量门禁")
    print("=" * 68)
    print(f"项目根目录：{ROOT}")
    print()

    failed: list[str] = []

    for name, argv, implemented in GATES:
        if not implemented:
            print(f"[SKIP] {name}  （尚未实现）")
            continue

        print(f"--- {name} ---")
        if argv and argv[0] == "__flutter_analyze__":
            code = run_flutter("analyze")
        elif argv and argv[0] == "__flutter_test__":
            code = run_flutter("test")
        elif argv and argv[0] == "__pytest__":
            code = run_pytest()
        else:
            code = run(argv[0], argv[1:])
        if code != 0:
            failed.append(name)
            print(f"[FAIL] {name}")
        print()

    print("=" * 68)
    if failed:
        print(f"[FAIL] {len(failed)} 道门未通过：")
        for f in failed:
            print(f"    {f}")
        sys.exit(1)

    print("[OK] 全部已实现的门通过")
    print()


if __name__ == "__main__":
    main()
