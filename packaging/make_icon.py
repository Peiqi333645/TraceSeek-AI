"""由 packaging/appicon.png 生成桌面应用图标(.icns + .ico)。

本地一次性工具(在 macOS 上跑, 需要 Pillow + 系统自带 iconutil/sips):
    python packaging/make_icon.py
产物已提交进仓库, CI 打包直接用, 不在 CI 里重生成。
品牌 PNG 是唯一源文件，桌面、安装程序与控制台共同使用。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
SIZE = 1024
def _master() -> Image.Image:
    source = HERE / "appicon.png"
    return Image.open(source).convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def main() -> int:
    master = _master()
    # .ico (Windows)
    ico = HERE / "appicon.ico"
    master.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", ico)

    # .icns (macOS), 需要 iconutil
    iconset = HERE / "appicon.iconset"
    iconset.mkdir(exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = base * scale
            name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
            master.resize((px, px), Image.Resampling.LANCZOS).save(iconset / name)
    try:
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "appicon.icns")],
                       check=True)
        print("wrote", HERE / "appicon.icns")
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        # Linux 开发环境没有 iconutil，Pillow 可直接生成供 CI 使用的 icns。
        master.save(HERE / "appicon.icns", format="ICNS")
        print(f"wrote {HERE / 'appicon.icns'} (Pillow fallback: {e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
