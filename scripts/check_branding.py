"""
G2e 品牌资源自检。

检查 App 图标与品牌图是否就位、是否还是模板自带的占位图。

为什么需要这道门禁：
    图标出问题只会在**装到手机上之后**才被发现 —— 本地跑 `flutter run`
    用的是模板默认图标，看不出来。而 `flutter clean`、
    重新 `flutter create`、或误删 res 目录都会让它悄悄退回默认图标，
    没有任何报错。

    这属于"静默失败"，正是门禁该拦的东西。

判据说明：
    不用固定哈希（重新生成会变），而是用**尺寸与文件大小**区分：
    Flutter 模板自带的 ic_launcher.png 是按密度 48/72/96/144/192 的
    纯色 Android 机器人，压缩后只有几百字节到 2 KB；
    真实图标有渐变与细节，同尺寸下明显更大。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "mobile" / "android" / "app" / "src" / "main" / "res"
BRANDING = ROOT / "mobile" / "assets" / "branding" / "logo.png"
WIN_ICON = ROOT / "mobile" / "windows" / "runner" / "resources" / "app_icon.ico"

# Android 各密度下的传统图标尺寸（px）
LEGACY = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

# 模板默认图标在 192px 下的体积上限（字节）。
# 实测模板图约 1–2 KB，真实品牌图在 10 KB 以上，区分度足够。
TEMPLATE_SIZE_CEILING = 3000


def _png_size(path: Path):
    """只读 PNG 头部拿宽高，避免为一个尺寸检查引入 Pillow 依赖。"""
    with path.open("rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w = int.from_bytes(head[16:20], "big")
    h = int.from_bytes(head[20:24], "big")
    return w, h


def main() -> int:
    ok_count = 0
    failures: list[str] = []

    print("=" * 68)
    print("品牌资源自检")
    print("=" * 68)
    print()

    # ---- Android 传统图标 ----
    for folder, expect in LEGACY.items():
        p = RES / folder / "ic_launcher.png"
        if not p.exists():
            failures.append(f"缺少 {folder}/ic_launcher.png（装到手机上将显示默认图标）")
            continue

        size = _png_size(p)
        if size is None:
            failures.append(f"{folder}/ic_launcher.png 不是合法 PNG")
            continue
        if size != (expect, expect):
            failures.append(
                f"{folder}/ic_launcher.png 尺寸是 {size[0]}x{size[1]}，应为 {expect}x{expect}"
            )
            continue

        # 只有最大那档才判断体积 —— 小尺寸下真实图标也可能很小
        if folder == "mipmap-xxxhdpi":
            kb = p.stat().st_size
            if kb < TEMPLATE_SIZE_CEILING:
                failures.append(
                    f"mipmap-xxxhdpi/ic_launcher.png 只有 {kb} 字节，"
                    f"像是模板默认图标而不是真实品牌图。"
                    f"跑 `python scripts/gen_icons.py <源图>` 重新生成。"
                )
                continue

        print(f"  [OK] {folder}/ic_launcher.png  {size[0]}x{size[1]}")
        ok_count += 1

    # ---- Android 自适应图标 ----
    # 前景层：必须存在，且必须带透明通道（否则圆形主题下会露出方角）
    for folder in LEGACY:
        fg = RES / folder / "ic_launcher_foreground.png"
        if not fg.exists():
            failures.append(
                f"缺少 {folder}/ic_launcher_foreground.png"
                f"（Android 8+ 的自适应图标前景层）"
            )
            continue

        # 自适应图标画布是 108dp 基准，前景层比同密度传统图标大 2.25 倍
        expect = int(LEGACY[folder] * 108 / 48)
        size = _png_size(fg)
        if size is None or size != (expect, expect):
            got = f"{size[0]}x{size[1]}" if size else "非法 PNG"
            failures.append(
                f"{folder}/ic_launcher_foreground.png 尺寸是 {got}，应为 {expect}x{expect}"
            )
            continue

        # 检查 PNG 颜色类型是否含 alpha（类型 6 = RGBA，4 = 灰度+alpha）
        with fg.open("rb") as f:
            head = f.read(26)
        color_type = head[25]
        if color_type not in (4, 6):
            failures.append(
                f"{folder}/ic_launcher_foreground.png 不含透明通道"
                f"（PNG color type={color_type}）。"
                f"自适应图标的前景层必须透明，否则圆形主题下会露出方角。"
            )
            continue

        print(f"  [OK] {folder}/ic_launcher_foreground.png  {size[0]}x{size[1]}  含透明通道")
        ok_count += 1

    # ---- 自适应图标的组合声明与背景色 ----
    launcher = RES / "mipmap-anydpi-v26" / "ic_launcher.xml"
    if not launcher.exists():
        failures.append("缺少 mipmap-anydpi-v26/ic_launcher.xml（自适应图标声明）")
    else:
        text = launcher.read_text(encoding="utf-8")
        for need, why in [
            ("<adaptive-icon", "不是自适应图标声明"),
            ("@color/ic_launcher_background", "未引用背景色资源"),
            ("@mipmap/ic_launcher_foreground", "未引用前景层"),
        ]:
            if need not in text:
                failures.append(f"ic_launcher.xml {why}（找不到 {need}）")
                break
        else:
            print("  [OK] mipmap-anydpi-v26/ic_launcher.xml  背景层 + 前景层")
            ok_count += 1

    bg_xml = RES / "values" / "ic_launcher_background.xml"
    if not bg_xml.exists():
        failures.append("缺少 values/ic_launcher_background.xml（背景层颜色）")
    else:
        print("  [OK] values/ic_launcher_background.xml")
        ok_count += 1

    # ---- Windows 图标 ----
    if not WIN_ICON.exists():
        failures.append("缺少 windows/runner/resources/app_icon.ico")
    else:
        kb = WIN_ICON.stat().st_size
        # 多尺寸 .ico 体积在几十 KB 以上；单尺寸的模板图很小
        if kb < 5000:
            failures.append(
                f"app_icon.ico 只有 {kb} 字节，可能只含单一尺寸。"
                f"多尺寸打包是必须的：任务栏用 32px、桌面用 48px、"
                f"高 DPI 用 256px，缺哪个都会在该场景下被粗暴缩放。"
            )
        else:
            print(f"  [OK] windows/runner/resources/app_icon.ico  {kb // 1024} KB")
            ok_count += 1

    # ---- App 内品牌图 ----
    if not BRANDING.exists():
        failures.append(
            "缺少 assets/branding/logo.png（登录页与关于页的品牌形象）"
        )
    else:
        size = _png_size(BRANDING)
        if size is None:
            failures.append("assets/branding/logo.png 不是合法 PNG")
        elif min(size) < 256:
            failures.append(
                f"assets/branding/logo.png 只有 {size[0]}x{size[1]}，"
                f"在高分屏上会糊。至少 256px。"
            )
        else:
            print(f"  [OK] assets/branding/logo.png  {size[0]}x{size[1]}")
            ok_count += 1

    print()
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        print()
        print(f"[FAIL] 品牌资源有 {len(failures)} 处问题")
        return 1

    print(f"[OK] 品牌资源全部就位（{ok_count} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
