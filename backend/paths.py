r"""
项目路径的唯一事实源。

## 为什么需要这个模块

这个项目的所有**生成物**（模型权重、缓存、上传的临时文件、分析输出）
都必须落在 YUcoach 文件夹**内部**，不散落到别处。

在引入本模块之前，路径散落在 7 个地方（3 个 py 文件里各写一遍模型缓存路径，
服务端另写一个上传目录）。后果：

  · 换一台机器要改 7 处，漏一处就往错的地方写
  · 没有任何地方能回答"这个项目到底会往哪些目录写文件"
  · 用户明确要求"不要存在该文件夹之外"，但没有单一位置可以保证这一点

现在全部收敛到这里。**要改路径只改这个文件。**

## 路径推导方式

全部以 `__file__` 为锚点向上推导，**不依赖当前工作目录**。

这一点很重要：服务端、CLI、pytest、脚本的 cwd 各不相同
（可能是 `D:\YUcoach`，也可能是 `D:\YUcoach\mobile`），
用相对路径会写到意料之外的地方。

## 目录约定

    YUcoach/
    ├── .cache/              缓存、账号与临时产物（清理前须区分数据）
    │   ├── models/          模型权重
    │   ├── torch/           PyTorch 权重缓存
    │   ├── ultralytics/     ultralytics 配置
    │   ├── huggingface/     HF 缓存
    │   ├── papers/          文献 PDF 缓存（开发期检索用）
    │   └── uploads/         服务端收到的上传文件（24 小时后自动清理）
    ├── output/              分析产物（报告 JSON、骨架视频、CSV）
    ├── backend/  mobile/  docs/  data/  samples/  scripts/
    └── ...

`.cache/` 以点开头是刻意的 —— 它表示"这是生成的基础设施，不是源码"，
在文件浏览器和 git 里都可以折叠起来。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 仓库根目录。parents[1] = backend/paths.py -> backend -> 仓库根
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

#: Reviewed videos, annotations and reports; not an expiring cache.
MANUAL_DATASET_DIR: Path = PROJECT_ROOT / "data" / "manual_timing"

#: 生成物根目录
CACHE_DIR: Path = PROJECT_ROOT / ".cache"

#: 模型权重目录
MODELS_DIR: Path = CACHE_DIR / "models"

#: PyTorch 权重缓存
TORCH_DIR: Path = CACHE_DIR / "torch"

#: ultralytics 配置目录。
#: ⚠️ 它默认写 C:\Users\<用户>\AppData\Roaming\Ultralytics —— 会污染系统盘。
ULTRALYTICS_DIR: Path = CACHE_DIR / "ultralytics"

#: HuggingFace 缓存
HF_DIR: Path = CACHE_DIR / "huggingface"

#: 文献 PDF 缓存（开发期做标准值检索时用，不属于运行时）
PAPERS_DIR: Path = CACHE_DIR / "papers"

#: 服务端上传文件的落地目录。
#: 服务端会在启动时创建，并按 STALE_UPLOAD_SECONDS 自动清理过期文件。
UPLOADS_DIR: Path = Path(
    os.environ.get("YUCOACH_UPLOAD_DIR", str(CACHE_DIR / "uploads"))
)

#: 分析产物目录（报告 JSON / 骨架视频 / 关键点 CSV）
OUTPUT_DIR: Path = PROJECT_ROOT / "output"

#: 账号与兑换码的存储文件。
#:
#: ⚠️ 虽然放在 .cache/ 下，它不是可再生缓存；
#:    删掉之后所有账号和兑换码都会丢失，清理前须备份。
#:    开发期这样很方便；真要上线应当移到不会被清理的位置，
#:    并换成数据库（见 backend/server/accounts.py 的说明）。
ACCOUNTS_FILE: Path = CACHE_DIR / "accounts.json"


def ensure_cache_dirs() -> None:
    """
    创建所有缓存目录（幂等）。

    在进程启动早期调用。为什么不在 import 时就创建：
        导入模块不该有副作用 —— 连 `import backend.paths` 都会建目录
        会让测试和只读场景变得难以推理。
    """
    for d in (MODELS_DIR, TORCH_DIR, ULTRALYTICS_DIR, HF_DIR, UPLOADS_DIR,
              CACHE_DIR / "datasets", CACHE_DIR / "runs",
              CACHE_DIR / "tmp", CACHE_DIR / "pip-cache",
              CACHE_DIR / "torchinductor"):
        d.mkdir(parents=True, exist_ok=True)


def apply_env_defaults() -> None:
    """
    把缓存路径写进环境变量。

    ⚠️ 必须是**强制赋值**，不能是 `setdefault`。这是一个真实踩过的坑：

        开发早期按旧方案设置过**用户级环境变量**
        `YOLO_CONFIG_DIR=D:\\model_cache\\ultralytics`。
        后来路径改成项目内，代码里却用 setdefault 设置 ——
        结果用户级那个旧值优先，ultralytics 又把配置写到了项目外
        （表现为项目根目录莫名出现一个 `Ultralytics/` 文件夹）。

    "生成物必须在项目内"现在是硬要求，不是"如果没有就设成这个"。
    所以这里直接覆盖，让代码不依赖开发机上残留的环境变量。

    ⚠️ 必须在**导入 torch / ultralytics 之前**调用：
        这两个库在 import 时就读环境变量决定缓存位置。
        晚一步，它们已经把文件写到别处了 —— 而且不会报错。

    2026-10-11 补充：本机 D 盘根目录带
        `Mandatory Label\\High Mandatory Level:(NW)`
    的完整性策略，**禁止在 D:\\ 根下创建子目录**；系统 TEMP（C 盘）同样不可写。
    于是 pip / torch 找不到可写的临时目录，会**回退到当前工作目录** ——
    表现为项目根目录堆出上百个 `pip-*` / `torchinductor_*` 文件夹。

    所以这里把临时目录也一并接管到项目内，不依赖机器上的环境变量。
    """
    tmp = CACHE_DIR / "tmp"
    pipecache = CACHE_DIR / "pip-cache"
    inductor = CACHE_DIR / "torchinductor"

    os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_DIR)
    os.environ["TORCH_HOME"] = str(TORCH_DIR)
    os.environ["HF_HOME"] = str(HF_DIR)

    # 临时目录：不接管的话，构建类操作会污染当前工作目录
    os.environ["TEMP"] = str(tmp)
    os.environ["TMP"] = str(tmp)
    os.environ["PIP_CACHE_DIR"] = str(pipecache)
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(inductor)


def configure_ultralytics_settings() -> None:
    """
    修正 ultralytics 自己 settings.json 里的三个目录。

    ⚠️ 这些字段**不受环境变量控制**，它默认往当前工作目录建文件夹：

        datasets_dir   默认 <cwd>/datasets
        weights_dir    默认 "weights"   ->  <cwd>/weights
        runs_dir       默认 "runs"      ->  <cwd>/runs

    不处理的话，跑一次分析就会在项目根目录冒出三个无关文件夹。

    必须在 `import ultralytics` **之后**调用（那时才有 settings 对象）。
    失败时静默 —— 这是"整洁性"问题，不该让分析失败。
    """
    try:
        from ultralytics import settings as ul_settings

        ul_settings.update({
            "datasets_dir": str(CACHE_DIR / "datasets"),
            "weights_dir": str(MODELS_DIR),
            "runs_dir": str(CACHE_DIR / "runs"),
        })
    except Exception:
        pass


def describe() -> str:
    """人类可读的路径清单。用于启动时打印和自检脚本。"""
    lines = [f"项目根   {PROJECT_ROOT}", f"生成物   {CACHE_DIR}"]
    for label, d in (
        ("模型", MODELS_DIR), ("上传", UPLOADS_DIR),
        ("产物", OUTPUT_DIR),
    ):
        exists = "存在" if d.exists() else "待创建"
        lines.append(f"  {label:4s} {d}  [{exists}]")
    return "\n".join(lines)
