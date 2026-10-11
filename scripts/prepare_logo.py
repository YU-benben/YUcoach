"""
清理品牌图：去掉右下角的手写签名，产出干净的图标源图。

用法：
    python scripts/prepare_logo.py <源图片> [输出路径]

产出（默认）：
    mobile/assets/branding/logo.png

为什么需要这一步：
    原始品牌图右下角有一行手写署名。在 1400 px 下看是细节，
    但在图标尺寸（桌面常见 48–72 px）下会糊成一团污迹，
    让整个图标显得脏。

    署名本身不该去掉 —— 那是作者的信息。这里只是为**图标**产出
    一份干净版本，原图保持不动。

为什么用"背景色补一块"而不是抠图算法：
    署名所在的右下角区域是平坦的浅蓝背景，没有渐变或纹理。
    这种情况下用背景色填一块与原图完全一致，不会留下可见接缝。
    引入抠图/inpainting 反而会带来色差与新的人工痕迹。
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "mobile" / "assets" / "branding" / "logo.png"

# 背景色：从原图四角采样得到的均值
BACKGROUND = (157, 218, 254)  # #9DDAFE

# 署名所在的区域（源图坐标，1432×1432 下的实测值）。
#
# 定位方法：在候选区内用"暗度阈值"找墨迹像素的包围盒。
# 该区域只有浅蓝背景与深色墨迹，没有渐变，所以这个判据很可靠。
#
# 实测结果：
#     y 977–1055   署名"笨笨鱼"三个字（x 990–1194）
#     y 1065 起    地面草线
# 两者之间有约 10 px 的干净分界，所以矩形下边界取 1060。
#
# 踩过的两次坑，记录下来免得重蹈：
#   1. 第一次订 (935, 950, 1090, 1040)：横向起点太靠左（那里是空白），
#      终点 1090 又只到第一个字的右缘 —— 结果只擦掉半个字。
#   2. 第二次订 (1080, 966, 1198, 1037)：起点 1080 把左边两个字整个漏掉，
#      下边界 1037 又切在字的中间 —— 图标上留下一块可见的灰色方块。
#
# 根本教训：不能靠"看一眼估个矩形"。署名与草线在垂直方向只差 10 px，
# 必须用像素统计定边界。
SIGNATURE_BOX = (984, 971, 1200, 1060)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT

    if not src.exists():
        print(f"[FAIL] 源图片不存在：{src}")
        return 1

    im = Image.open(src).convert("RGB")
    print(f"源图：{src.name}  {im.size[0]}x{im.size[1]}")

    x0, y0, x1, y1 = SIGNATURE_BOX
    if x1 > im.size[0] or y1 > im.size[1]:
        print(f"[FAIL] 署名区域 {SIGNATURE_BOX} 超出图片范围 {im.size}")
        return 1

    # 填充色从矩形**正上方**采样，而不是用全局平均背景色。
    #
    # 原因：JPEG 压缩会让背景出现细微不均匀，全局平均值与局部实际值
    # 差几个色阶 —— 肉眼就能看出一块淡矩形。用紧邻区域的真实颜色
    # 填充，色差降到看不见。
    #
    # 取正上方是因为那里确定是纯背景：下方是地面草线，左右是鱼的尾鳍。
    sample_y = max(0, y0 - 12)
    samples = [im.getpixel((x, sample_y))
               for x in range(x0 + 4, x1 - 4, 8)]
    fill = tuple(
        sum(s[i] for s in samples) // len(samples) for i in range(3)
    )
    print(f"局部背景采样色（y={sample_y}）：RGB{fill}  "
          f"#{fill[0]:02X}{fill[1]:02X}{fill[2]:02X}")
    print(f"全局背景色：RGB{BACKGROUND}  "
          f"#{BACKGROUND[0]:02X}{BACKGROUND[1]:02X}{BACKGROUND[2]:02X}  "
          f"（差值 {sum(abs(fill[i] - BACKGROUND[i]) for i in range(3))}）")

    # 不做羽化 —— 区域内部是纯色，硬边反而更干净；
    # 羽化会在边缘带进一点半透明，在纯色背景上表现为一圈淡影。
    im.paste(fill, (x0, y0, x1, y1))

    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "PNG", optimize=True)

    print(f"已去除签名区域 {SIGNATURE_BOX}")
    print(f"  + {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
