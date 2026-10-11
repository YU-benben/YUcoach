"""
对运行中的分析服务做端到端验证。

用法：
    1. 先启动服务：python -m backend.server.app --port 8770
    2. 再跑本脚本：python scripts/verify_server_e2e.py [--base-url ...]

与 backend/tests/test_server.py 的分工：
    test_server.py          自起服务实例、用合成视频，快，进 CI
    本脚本                  连**真实运行的服务**、用**真实素材**，慢，人工跑

为什么两者都要：
    测试用合成视频是为了不依赖素材文件（CI 上没有）。
    但合成视频里的人形色块 YOLO 未必稳定检出 ——
    真正验证"App 上传真实素材能得到报告"必须用真素材。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _get(base: str, path: str, timeout: int = 20):
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _post_json(base: str, path: str, payload: dict, timeout: int = 60):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8770")
    ap.add_argument("--video", type=Path,
                    default=ROOT / "samples" / "videos" / "训练素材刘珉宇.mp4")
    ap.add_argument("--athlete-name", default="刘珉宇")
    ap.add_argument("--athlete-id", default="at00007")
    ap.add_argument("--height", type=float, default=178.0)
    ap.add_argument("--view", default="side")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")

    print("=" * 68)
    print("分析服务端到端验证")
    print("=" * 68)
    print(f"服务      {base}")
    print(f"素材      {args.video.name}")
    print()

    # ---- 1. 健康检查 ----
    try:
        code, h = _get(base, "/api/health")
    except Exception as e:
        print(f"[FAIL] 连不上服务：{e}")
        print("       请先在另一个终端启动：")
        print("       python -m backend.server.app --port 8770")
        return 1

    if code != 200 or not h.get("ok"):
        print(f"[FAIL] 服务状态异常：HTTP {code} {h}")
        return 1

    engine = h.get("engine", {})
    print(f"[OK] 服务在线 v{h['version']}")
    print(f"     设备 {engine.get('gpu') or 'CPU'}"
          f"（CUDA {'可用' if engine.get('cuda_available') else '不可用'}）")
    print()

    if not args.video.exists():
        print(f"[FAIL] 素材不存在：{args.video}")
        return 1

    # ---- 2. 上传 ----
    size_mb = args.video.stat().st_size / 1024**2
    print(f"[1/4] 上传 {size_mb:.1f} MB ...")
    req = urllib.request.Request(
        base + "/api/videos", data=args.video.read_bytes(), method="POST")
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("X-Filename", urllib.parse.quote(args.video.name))

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            up = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[FAIL] 上传失败 HTTP {e.code}：{e.read().decode()[:300]}")
        return 1

    upload_s = time.time() - t0
    speed = size_mb / upload_s if upload_s > 0 else 0
    print(f"      video_id={up['video_id']}  "
          f"用时 {upload_s:.1f}s（{speed:.1f} MB/s）")
    print()

    # ---- 3. 提交 ----
    print("[2/4] 提交分析 ...")
    code, job = _post_json(base, "/api/analyze", {
        "video_id": up["video_id"],
        "athlete_id": args.athlete_id,
        "athlete_name": args.athlete_name,
        "height_cm": args.height,
        "view": args.view,
        "test_type": "block_start",
    })
    if code != 202:
        print(f"[FAIL] 提交失败 HTTP {code}：{job}")
        return 1
    job_id = job["job_id"]
    print(f"      job_id={job_id}")
    print()

    # ---- 4. 轮询 ----
    print("[3/4] 等待分析 ...")
    t0 = time.time()
    last_line = ""
    final = None

    while time.time() - t0 < 900:
        try:
            _, st = _get(base, f"/api/jobs/{job_id}")
        except Exception as e:
            print(f"      轮询出错（继续重试）：{e}")
            time.sleep(2)
            continue

        line = (f"      {st['status']:8s} "
                f"{st['progress'] * 100:5.1f}%  {st['stage']}")
        if line != last_line:
            print(line, flush=True)
            last_line = line

        if st["status"] in ("done", "failed"):
            final = st
            break
        time.sleep(0.5)

    if final is None:
        print("[FAIL] 分析超时")
        return 1

    print()

    # ---- 5. 检查结果 ----
    print("[4/4] 检查报告 ...")
    if final["status"] == "failed":
        print(f"[FAIL] 分析失败：{final.get('error')}")
        print((final.get("error_detail") or "")[:2000])
        return 1

    report = final["report"]

    # 结构检查
    required = ["schema_version", "analysis_id", "session", "versions",
                "quality_score", "metrics", "findings", "summary",
                "phases_detected", "keyframes"]
    missing = [k for k in required if k not in report]
    if missing:
        print(f"[FAIL] 报告缺字段：{missing}")
        return 1
    print(f"      [OK] 根字段齐全（{len(required)} 项）")

    if not report["metrics"]:
        print("[FAIL] metrics 为空")
        return 1

    computed = [m for m in report["metrics"] if not m.get("insufficient")]
    skipped = [m for m in report["metrics"] if m.get("insufficient")]
    print(f"      [OK] 指标 {len(computed)}/{len(report['metrics'])} 算出数值")

    # 用真实契约校验报告
    out = ROOT / "output" / "_server_e2e_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    import subprocess
    check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_contracts.py"),
         "--fixture", str(out), "--schema", "analysis"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check.returncode != 0:
        print("[FAIL] 报告不符合契约：")
        for line in (check.stdout or "").splitlines()[-12:]:
            print(f"      {line}")
        return 1
    print("      [OK] 报告通过 analysis 契约校验")

    print()
    print("=" * 68)
    print("结果摘要")
    print("=" * 68)
    print(f"  质量分    {report['quality_score']}")
    print(f"  总览      {report['summary']['headline']}")
    print(f"  分析耗时  {final['elapsed_s']}s")
    print()

    if computed:
        print("  算出数值：")
        for m in computed[:10]:
            flag = "" if m["reliable"] else "  (低置信)"
            print(f"    [OK] {m['name_zh']:16s} {m['value']} {m['unit']}{flag}")
        if len(computed) > 10:
            print(f"    ... 另有 {len(computed) - 10} 项")
        print()

    if skipped:
        print("  数据不足：")
        for m in skipped[:8]:
            ins = m["insufficient"]
            print(f"    [--] {m['name_zh']:16s} {ins['actual'][:40]}")
        if len(skipped) > 8:
            print(f"    ... 另有 {len(skipped) - 8} 项")
        print()

    print(f"  报告已保存到 {out.relative_to(ROOT)}")
    print()
    print("[OK] 端到端验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
