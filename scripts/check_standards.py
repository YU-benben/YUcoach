"""
G4 标准值库自检。

为什么这道门不可替代：

    docs/04-参考标准值规范.md §1 写得很清楚：

        标准值编造是**全项目唯一无法通过测试发现的错误类型**。
        指标算错可以对比真值，契约写错有 Schema 校验，
        规则写错有用例验证 —— 而标准值编造没有任何自动检测手段。

    这道门就是补上那个缺口。它检查的每一条都对应一种
    "看起来正常但实际错误"的标准值。

与 backend/tests/test_standards.py 的分工：
    测试验证**校验逻辑本身**是否正确（用临时文件造各种坏数据）。
    这道门验证**仓库里真实的标准值库**是否合规。

    两者都需要：只测逻辑，真实文件里的问题发现不了；
    只查文件，校验逻辑本身写错了也发现不了。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

from backend.standards.loader import load_standards  # noqa: E402


def main() -> int:
    print("=" * 68)
    print("标准值库自检")
    print("=" * 68)
    print()

    lib = load_standards()

    print(f"版本        {lib.version or '（未声明）'}")
    print(f"可用条目    {len(lib.entries)}")
    print(f"待补条目    {len(lib.pending)}")
    print()

    # ---- 不合规条目：必须为零 ----
    if lib.problems:
        print("[FAIL] 以下条目不合规，已被拒绝加载：")
        for p in lib.problems:
            print(f"       {p}")
        print()
        print("不合规的条目不会被使用 —— 运行时会表现为「不做偏离判断」。")
        print("但这说明有人试图写入无法查证的标准值，必须修正。")
        return 1

    print("  [OK] 全部条目通过机械校验")

    # ---- 逐条列出可用标准值 ----
    if lib.entries:
        print()
        print("可用标准值：")
        for e in lib.entries:
            print(f"  · {e.metric_id}  [{e.view}/{e.phase}]  "
                  f"{e.low}–{e.high}  (n={e.n})")
            print(f"      出处：{e.display_source()}")
    else:
        print()
        print("  [WARN] 当前没有任何可用标准值 —— 报告将只输出测量值，")
        print("         不做任何偏离判断。这是设计如此，不是故障。")

    # ---- 待补清单 ----
    if lib.pending:
        print()
        print(f"待补条目（{len(lib.pending)} 项）—— 刻意留空，等文献检索：")
        for p in lib.pending:
            mid = p.get("metric_id", "?")
            ph = p.get("phase", "?")
            needed = (p.get("needed") or "")[:40]
            print(f"  · {mid} [{ph}]  {needed}")

    # ---- 覆盖度 ----
    from backend.analysis.metrics_base import METRIC_SPECS

    have = {e.metric_id for e in lib.entries}
    pending_ids = {p.get("metric_id") for p in lib.pending}
    total = len(METRIC_SPECS)

    print()
    print(f"标准值覆盖度：{len(have)}/{total} 个指标有可用标准值"
          f"（另有 {len(pending_ids - have)} 个在待补清单里）")

    missing = set(METRIC_SPECS) - have - pending_ids
    if missing:
        print()
        print(f"  [WARN] 以下 {len(missing)} 个指标既无标准值也不在待补清单里：")
        for mid in sorted(missing):
            print(f"         {mid}")
        print("         建议把它们加入 pending，记下需要什么数据、去哪里找 ——")
        print("         留空是有意的，但『不知道为什么留空』不是。")

    print()
    print("[OK] 标准值库自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
