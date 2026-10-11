"""
生成 App 图标。

用法：
    python scripts/gen_icons.py <源图片路径>

产出：
    Android  传统方形图标  mipmap-{mdpi..xxxhdpi}/ic_launcher.png
    Android  自适应图标前景/背景  mipmap-*/ic_launcher_foreground.png
                                  values/ic_launcher_background.xml
                                  mipmap-anydpi-v26/ic_launcher.xml
    Windows  window_icon.ico（多尺寸，供任务栏与标题栏使用）

为什么不能简单地"把图片缩成几个尺寸" —— Android 8.0 起图标分两层：

    背景层 background  +  前景层 foreground

系统按设备主题（圆形/方形/水滴形）自己裁切与动画。前景层的画布是
108×108 dp，但**只有中间 72×72 dp 会被显示**，外侧约 25% 是留给
裁切与视差的安全区。

所以如果直接把整张图当图标用，鱼鳍、秒表和下方的签名都会被切掉。
正确做法是：把画面内容缩到安全区内，四周用与背景一致的纯色补足。

这也是为什么自适应图标的背景层用纯色而不是原图：原图放大后会
在边缘露出补色的接缝，而纯色背景让系统裁切成任何形状都干净。
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ANDROID_RES = ROOT / "mobile" / "android" / "app" / "src" / "main" / "res"
WINDOWS_RUNNER = ROOT / "mobile" / "windows" / "runner" / "resources"

# 从原图取样的背景色。自适应图标用它做背景层，
# 保证系统裁切成任何形状时边缘都干净无接缝。
BACKGROUND = (157, 218, 254)  # #9DDAFE

# Android 传统图标（API < 26）的各密度尺寸。单位 px。
LEGACY_SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

# 自适应图标前景层画布尺寸。108 dp 基准，各密度对应如下。
# 可见区域是中间 72/108 ≈ 66.7%。
ADAPTIVE_SIZES = {
    "mipmap-mdpi": 108,
    "mipmap-hdpi": 162,
    "mipmap-xhdpi": 216,
    "mipmap-xxhdpi": 324,
    "mipmap-xxxhdpi": 432,
}

# 内容在画布中的占比。
# 自适应图标必须 <= 72/108 = 0.667，否则会被裁掉。
# 取 0.65 贴近上限：图标显示尺寸很小（桌面常见 48–72 px），
# 内容占比每降低一点，鱼的细节就模糊一分。
ADAPTIVE_CONTENT_RATIO = 0.65

# 传统方形图标没有裁切，可以铺满，但留一点边距更好看。
LEGACY_CONTENT_RATIO = 0.94


def load_square(src: Path) -> Image.Image:
    """读入，按内容实际边界居中裁成正方形。

    为什么要先检测内容边界，而不是直接用原图：

      1. 原图四周留白很多（实测内容只占 x:176–1209, y:332–1114），
         直接用会让主体偏小、图标显空。
      2. 右下角有一行手写签名。它在图标尺寸（48 px）下会糊成一团污迹，
         看起来很脏。裁掉留白正好把它排除在外 ——
         这是顺带的好处，不是为了去掉署名。

    裁切用**内容长边**定边长，再以内容中心对齐。不能用短边 ——
    那会切掉长边方向的两端（本图是秒表与鱼尾）。
    """
    im = Image.open(src).convert("RGB")

    # 非正方形先按中心裁切。拉伸会让画面变形，图标里的变形一眼可见。
    w, h = im.size
    if w != h:
        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        im = im.crop((left, top, left + side, top + side))

    bbox = _content_bbox(im)
    if bbox is None:
        return im  # 整幅都是背景色，退回原图

    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2

    # 边长按**长边**算，并留 6% 呼吸空间。
    #
    # 这里踩过一次坑：最初按"内容高度"定边长，想着跑步剪影是扁的、
    # 按宽度会把上下留白也吃进来。但那正好切掉了左右两端 ——
    # 而秒表在左端、鱼尾在右端。自适应图标再按圆形裁一次，
    # 画面里就只剩下鱼身了。
    #
    # 正确做法是取长边：宁可让主体小一点，也不能切掉内容。
    # 图标显示尺寸只有 48–72 px，缺一块比小一点严重得多。
    side = int(round(max(x1 - x0, y1 - y0) * 1.06))

    left = cx - side // 2
    top = cy - side // 2
    right, bottom = left + side, top + side

    # 越界时用纯背景色补，而不是把图往外挪 ——
    # 挪动会让主体偏离中心，图标看起来是歪的。
    out = Image.new("RGB", (side, side), BACKGROUND)
    src_box = (max(0, left), max(0, top), min(im.size[0], right),
               min(im.size[1], bottom))
    if src_box[2] > src_box[0] and src_box[3] > src_box[1]:
        patch = im.crop(src_box)
        out.paste(patch, (src_box[0] - left, src_box[1] - top))
    return out


def _content_bbox(im: Image.Image, tol: int = 40):
    """找出与背景色明显不同的像素范围。返回 (x0, y0, x1, y1)，全背景时 None。"""
    px = im.load()
    w, h = im.size
    bx, by, bz = BACKGROUND

    min_x, min_y, max_x, max_y = w, h, -1, -1
    # 逐行扫描足够快（1432² 的图约 200 万像素），且不引入 numpy 依赖
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if abs(r - bx) + abs(g - by) + abs(b - bz) > tol:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y

    if max_x < 0:
        return None
    return min_x, min_y, max_x, max_y


def fit_into(src: Image.Image, canvas: int, ratio: float,
             bg: tuple[int, int, int]) -> Image.Image:
    """把源图缩放后居中放到纯色画布上。

    缩放用 LANCZOS：图标缩小时用它保留细节最清楚，
    默认的 NEAREST/BILINEAR 会让线条发虚。
    """
    content = int(round(canvas * ratio))
    scaled = src.resize((content, content), Image.LANCZOS)

    out = Image.new("RGB", (canvas, canvas), bg)
    offset = (canvas - content) // 2
    out.paste(scaled, (offset, offset))
    return out


def write_png(im: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "PNG", optimize=True)


def gen_android(src: Image.Image) -> list[str]:
    made: list[str] = []

    # ---- 传统方形图标（API < 26 的设备走这套）----
    for folder, size in LEGACY_SIZES.items():
        im = fit_into(src, size, LEGACY_CONTENT_RATIO, BACKGROUND)
        p = ANDROID_RES / folder / "ic_launcher.png"
        write_png(im, p)
        made.append(str(p.relative_to(ROOT)))

    # ---- 自适应图标前景层（API >= 26）----
    #
    # 前景层**必须带透明通道**：系统要把背景层垫在它下面，
    # 再用主题形状做蒙版。如果这里填了不透明背景色，
    # 背景层就永远看不见，圆形主题下会露出方角。
    #
    # 做法：把内容缩到安全区，画布其余部分保持全透明。
    for folder, canvas in ADAPTIVE_SIZES.items():
        content = int(round(canvas * ADAPTIVE_CONTENT_RATIO))
        scaled = src.resize((content, content), Image.LANCZOS)

        fg = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        offset = (canvas - content) // 2
        fg.paste(scaled, (offset, offset))

        p = ANDROID_RES / folder / "ic_launcher_foreground.png"
        write_png(fg, p)
        made.append(str(p.relative_to(ROOT)))

    # ---- 背景层：纯色 ----
    values = ANDROID_RES / "values"
    values.mkdir(parents=True, exist_ok=True)
    bg_xml = values / "ic_launcher_background.xml"
    bg_xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- 自适应图标背景层。\n"
        "     用纯色而非原图：系统会把背景层裁成各种形状（圆形/方形/水滴），\n"
        "     原图在裁切后边缘会露出接缝，纯色则任何形状都干净。\n"
        "     颜色取自原图背景采样值 #9DDAFE。\n"
        "     由 scripts/gen_icons.py 生成，请勿手工修改。 -->\n"
        "<resources>\n"
        f'    <color name="ic_launcher_background">#{BACKGROUND[0]:02X}'
        f"{BACKGROUND[1]:02X}{BACKGROUND[2]:02X}</color>\n"
        "</resources>\n",
        encoding="utf-8",
    )
    made.append(str(bg_xml.relative_to(ROOT)))

    # ---- 自适应图标的组合声明 ----
    anydpi = ANDROID_RES / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    launcher_xml = anydpi / "ic_launcher.xml"
    launcher_xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Android 8.0+ 的自适应图标：背景层 + 前景层。\n"
        "     系统按设备主题裁切成圆形/方形/水滴形。\n"
        "     前景层的内容只在中间 72/108 区域可见，见 gen_icons.py 的说明。 -->\n"
        "<adaptive-icon xmlns:android=\"http://schemas.android.com/apk/res/android\">\n"
        '    <background android:drawable="@color/ic_launcher_background" />\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
        "</adaptive-icon>\n",
        encoding="utf-8",
    )
    made.append(str(launcher_xml.relative_to(ROOT)))

    return made


def gen_windows(src: Image.Image) -> list[str]:
    """Windows 用 .ico。

    多尺寸打包是必须的：任务栏用 32px、桌面快捷方式用 48px、
    高 DPI 与"超大图标"视图用 256px。只放一个尺寸会导致
    在没覆盖到的场景里被系统粗暴缩放，边缘发虚。
    """
    WINDOWS_RUNNER.mkdir(parents=True, exist_ok=True)
    p = WINDOWS_RUNNER / "app_icon.ico"

    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [fit_into(src, s, LEGACY_CONTENT_RATIO, BACKGROUND) for s in sizes]

    frames[-1].save(p, format="ICO", sizes=[(s, s) for s in sizes])
    return [str(p.relative_to(ROOT))]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    src_path = Path(sys.argv[1])
    if not src_path.exists():
        print(f"[FAIL] 源图片不存在：{src_path}")
        return 1

    src = load_square(src_path)
    print(f"源图：{src_path.name}  {src.size[0]}x{src.size[1]}")
    print(f"背景色：#{BACKGROUND[0]:02X}{BACKGROUND[1]:02X}{BACKGROUND[2]:02X}")
    print()

    made = gen_android(src) + gen_windows(src)
    for m in made:
        print(f"  + {m}")
    print()
    print(f"共 {len(made)} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
