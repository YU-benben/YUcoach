"""
G0 磁盘空间与文件落盘位置自检。

## 为什么这算一道门禁

两件事都不是"某个功能坏了"，而是**会静默恶化**的问题：

  1. **系统盘被写满**
     Windows 在系统盘接近满时会出现各种难以归因的不稳定。
     而本项目的工具链（PyTorch / Ultralytics / Gradle / pip）
     默认全部往 C 盘写 —— 一个 CUDA 版 torch 就 2.5 GB。
     这类问题不会在开发中报错，只会在一段时间后突然爆发。

  2. **生成物散落到项目外**
     项目要求所有运行时文件都落在 YUcoach 文件夹内。
     但路径一旦在代码里写错、或者某个库有自己的默认位置，
     文件就会悄悄跑到别处 —— 同样不报错，只有去翻盘符才发现。

## 判据

  · C 盘可用 < 15 GB 警告，< 8 GB 失败
  · D 盘可用 < 5 GB 警告
  · backend.paths 里声明的每个目录都必须在项目根之内
  · 已知会落盘的项目外目录不应存在

## 与旧版的关系

旧版检查"缓存环境变量是否指向 D 盘"。改成项目内落盘之后，
那个判据不再成立 —— 现在的正确答案是"在 YUcoach 里面"，
而不是"在 D 盘上"（D 盘只是恰好装了 YUcoach）。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from backend.paths import (  # noqa: E402
    CACHE_DIR,
    HF_DIR,
    MODELS_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    TORCH_DIR,
    ULTRALYTICS_DIR,
    UPLOADS_DIR,
)

WARN_FREE_GB = 15.0
FAIL_FREE_GB = 8.0

#: 本项目曾经在项目外落盘的位置。
#: 保留这份清单是为了**发现回归** —— 如果哪天代码又写回这些地方，
#: 这里会报出来。历史上确实用过 `D:\model_cache` 和 `D:\yucoach_uploads`。
FORBIDDEN_OUTSIDE: tuple[Path, ...] = (
    Path(r"D:\yucoach_uploads"),
    Path(r"D:\model_cache"),
)


def check_disk_space() -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []

    if sys.platform != "win32":
        print("  (非 Windows，跳过盘符检查)")
        return failures, warnings

    for letter, warn, fail in (("C", WARN_FREE_GB, FAIL_FREE_GB),
                               ("D", 5.0, 2.0)):
        try:
            usage = shutil.disk_usage(f"{letter}:/")
        except OSError:
            continue
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        print(f"  {letter} 盘  总计 {total_gb:6.1f} GB   "
              f"可用 {free_gb:6.1f} GB")

        if free_gb < fail:
            failures.append(
                f"{letter} 盘仅剩 {free_gb:.1f} GB（低于 {fail} GB）。"
                + ("系统盘这么紧会开始不稳定，请立即清理。"
                   if letter == "C" else "缓存很快会写不下。")
            )
        elif free_gb < warn:
            warnings.append(
                f"{letter} 盘可用 {free_gb:.1f} GB，低于建议的 {warn} GB"
            )

    return failures, warnings


def check_paths_inside_project() -> tuple[list[str], list[str]]:
    """
    确认 backend.paths 声明的每个目录都落在项目根之内。

    ⚠️ 这条检查是"文件不许落在项目外"这个要求的机械实现。
       光靠人记得改代码不可靠 —— 路径写错不会报错，
       只会安静地往别处写文件。
    """
    failures: list[str] = []
    root = PROJECT_ROOT.resolve()

    print("  目录归属：")
    for label, d in (
        ("模型权重", MODELS_DIR),
        ("torch 缓存", TORCH_DIR),
        ("ultralytics", ULTRALYTICS_DIR),
        ("HF 缓存", HF_DIR),
        ("上传目录", UPLOADS_DIR),
        ("分析产物", OUTPUT_DIR),
        ("缓存根", CACHE_DIR),
    ):
        try:
            resolved = d.resolve()
        except OSError:
            failures.append(f"{label} 路径无法解析：{d}")
            continue

        inside = resolved == root or root in resolved.parents
        if inside:
            rel = resolved.relative_to(root)
            print(f"    [OK]  {label:12s} {rel}")
        else:
            failures.append(
                f"{label} 落在项目外：{resolved}。"
                f"所有生成物必须在 {root} 之内。"
            )
            print(f"    [FAIL] {label:12s} {resolved}  <- 在项目外")

    return failures, []


def check_no_forbidden_dirs() -> tuple[list[str], list[str]]:
    """检查历史遗留的项目外目录没有复活。"""
    warnings: list[str] = []
    print("  项目外落盘回归检查：")
    for p in FORBIDDEN_OUTSIDE:
        if p.exists():
            warnings.append(
                f"{p} 重新出现了。这说明有代码又往项目外写文件 —— "
                f"请检查 backend/paths.py 的使用。"
            )
            print(f"    [!!]  {p}  重新出现")
        else:
            print(f"    [OK]  {p}  不存在")
    return [], warnings


def main() -> int:
    print("=" * 68)
    print("磁盘空间与落盘位置自检")
    print("=" * 68)
    print()

    failures: list[str] = []
    warnings: list[str] = []

    print("磁盘空间：")
    f, w = check_disk_space()
    failures += f
    warnings += w
    print()

    f, w = check_paths_inside_project()
    failures += f
    warnings += w
    print()

    f, w = check_no_forbidden_dirs()
    failures += f
    warnings += w
    print()

    for x in warnings:
        print(f"[WARN] {x}")
    for x in failures:
        print(f"[FAIL] {x}")

    if failures:
        print()
        print(f"[FAIL] {len(failures)} 项需要处理")
        return 1

    if warnings:
        print()
        print(f"[WARN] {len(warnings)} 项建议处理，但不阻塞")
        return 0

    print("[OK] 磁盘空间充足，所有生成物都在项目内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
