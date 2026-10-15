#!/usr/bin/env python3
# 壁纸缓存生成（wallpaperd 调用）：
#   wallpaper-cache.py <宽> <高> <图片1> [<图片2> ...]
# 把每张图片按 <宽>x<高>（屏幕的实际像素尺寸）等比铺满 + 居中裁剪（和 swaybg -m fill 一样），
# 保存成可以直接显示的原始像素（BGRX，每像素 4 字节），每张输出一行缓存文件路径（失败时输出空行）。
# 已经有缓存时直接输出路径；原图改过（修改时间 / 大小变了）时会重新生成。
import hashlib
import os
import sys

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

CACHE = os.path.expanduser("~/.cache/mango-wallpaper-cache")


def make(path, width, height):
    st = os.stat(path)
    tag = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:12]
    base = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(CACHE, f"{base}-{width}x{height}-{tag}.bgrx")
    if os.path.exists(out) and os.path.getsize(out) == width * height * 4:
        return out
    os.makedirs(CACHE, exist_ok=True)
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    w, h = pb.get_width(), pb.get_height()
    s = max(width / w, height / h)
    sw, sh = max(width, round(w * s)), max(height, round(h * s))
    if (sw, sh) != (w, h):
        pb = pb.scale_simple(sw, sh, GdkPixbuf.InterpType.HYPER)
    pb = pb.new_subpixbuf((sw - width) // 2, (sh - height) // 2, width, height).copy()
    n, stride = pb.get_n_channels(), pb.get_rowstride()
    src = pb.get_pixels()
    rgb = bytearray(width * height * n)
    for y in range(height):  # 去掉每行末尾的填充字节
        rgb[y * width * n:(y + 1) * width * n] = src[y * stride:y * stride + width * n]
    buf = bytearray(width * height * 4)
    buf[0::4] = rgb[2::n]  # B
    buf[1::4] = rgb[1::n]  # G
    buf[2::4] = rgb[0::n]  # R
    buf[3::4] = b"\xff" * (width * height)
    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(buf)
    os.replace(tmp, out)
    return out


def main():
    width, height = int(sys.argv[1]), int(sys.argv[2])
    for path in sys.argv[3:]:
        try:
            print(make(path, width, height), flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"wallpaper-cache: {path}: {e}", file=sys.stderr)
            print("", flush=True)


if __name__ == "__main__":
    main()
