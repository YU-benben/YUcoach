"""
从 PDF 里粗提取文本，用于检索文献数值。

为什么不装 pdfplumber / pypdf：
    本项目的开发机系统盘紧张，而这些包会拉进一串依赖。
    本脚本只用于**一次性文献检索**，不是运行时依赖 ——
    为它装一个包不划算。

做法：
    PDF 的正文通常在 FlateDecode 压缩流里。用 zlib 解压后，
    提取 Tj / TJ 操作符里的字符串。这对文本型 PDF 足够，
    对扫描件（图片型）无效 —— 那种情况直接放弃并说明。

⚠️ 提取结果是**原始文本片段**，不是结构化表格。
   表格的列对齐信息会丢失，所以脚本会把上下文一起打印出来，
   由人来判断数字属于哪一列。
"""

from __future__ import annotations

import re
import sys
import urllib.request
import zlib
from pathlib import Path

# parents[2] = scripts/literature/extract_pdf_text.py -> literature -> scripts -> 仓库根
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.paths import PAPERS_DIR  # noqa: E402

# 控制台编码兜底。PDF 里提取出的字符五花八门（latin-1 范围内的各种符号），
# 在 Windows 的 GBK 控制台下打印会直接崩 —— 而崩在 print 上会把
# 真正的输出全部盖掉。
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 1000:
        print(f"已存在：{dest.name}（{dest.stat().st_size / 1024:.0f} KB）")
        return True
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; YUcoachLiterature/1.0)",
        })
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
    except Exception as e:
        print(f"[FAIL] 下载失败：{e}")
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"已下载：{dest.name}（{len(data) / 1024:.0f} KB）")
    return True


def extract_text(pdf: Path) -> str:
    """从 PDF 字节里粗提取文本。"""
    raw = pdf.read_bytes()
    chunks: list[str] = []

    # 找出所有流对象并尝试解压
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        blob = m.group(1)
        try:
            data = zlib.decompress(blob)
        except zlib.error:
            continue

        # 提取 Tj / TJ 里的字符串
        # TJ 是数组形式：(text) -100 (text) ...
        for tm in re.finditer(rb"\((?:\\.|[^\\()])*\)", data):
            s = tm.group(0)[1:-1]
            # 处理转义
            s = s.replace(b"\\(", b"(").replace(b"\\)", b")")
            s = s.replace(b"\\\\", b"\\")
            try:
                chunks.append(s.decode("latin-1"))
            except Exception:
                continue
        # 换行提示：Td / TD / T* 表示换行
        if re.search(rb"\bT[dD*]\b", data):
            chunks.append("\n")

    return "".join(chunks)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    url = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "doc.pdf"
    # 关键词过滤（可选）
    keyword = sys.argv[3] if len(sys.argv) > 3 else None

    dest = PAPERS_DIR / name
    if not download(url, dest):
        return 1

    text = extract_text(dest)
    print(f"提取到 {len(text)} 个字符")
    print()

    if keyword:
        print(f"=== 含「{keyword}」的上下文 ===")
        lo = keyword.lower()
        found = 0
        for m in re.finditer(re.escape(lo), text.lower()):
            a = max(0, m.start() - 350)
            b = min(len(text), m.end() + 650)
            print("-" * 60)
            print(text[a:b].replace("\n", " "))
            print()
            found += 1
            if found >= 6:
                print("（已达 6 处上限）")
                break
        if not found:
            print("未找到该关键词。可能是扫描件（图片型 PDF），或关键词不同。")
    else:
        print(text[:4000])

    return 0


if __name__ == "__main__":
    sys.exit(main())
