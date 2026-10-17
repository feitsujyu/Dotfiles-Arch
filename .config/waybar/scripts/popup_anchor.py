# 弹窗位置的计算：wifi-popup.py / volume-popup.py / bluetooth-popup.py / brightness-popup.py 共用
#
# 点击 waybar 的模块打开弹窗时，查一下“现在”这个模块在哪里，让弹窗的右边对准模块的右边。
# （模块的位置会随右边模块的文字宽度变化，例如电池 100% ⇄ 99%，所以不能写死）
#
# 1. mmsg get cursorpos  → 鼠标的位置和所在的屏幕（点击时鼠标就在模块上）
# 2. mmsg get monitor    → 这块屏幕的位置、大小、缩放
# 3. barprobe（~/.config/waybar/barprobe，C 写的小工具）→ 截取栏中间的 1 行像素，找出鼠标所在模块的左右边界
# 合计约 20～25ms。任何一步失败（鼠标不在栏上、mmsg 不能用等）时返回 None，弹窗用固定的位置（MARGIN_RIGHT）。

import json
import os
import re
import subprocess

from gi.repository import Gdk

WAYBAR_CONFIG = os.path.expanduser("~/.config/waybar/config.jsonc")
BARPROBE = os.path.expanduser("~/.config/waybar/barprobe/barprobe")


def bar_height():
    """waybar 的高度：每次从 config.jsonc 的 "height" 读取（栏在屏幕下边），读不到时用 40"""
    try:
        with open(WAYBAR_CONFIG) as f:
            m = re.search(r'"height"\s*:\s*(\d+)', f.read())
        return int(m.group(1)) if m else 40
    except OSError:
        return 40


def _mmsg(*args):
    r = subprocess.run(["mmsg", "get", *args], capture_output=True, text=True, timeout=0.5)
    return json.loads(r.stdout)


def gdk_monitor(x, y):
    """mango 的屏幕（左上角的坐标）→ GTK 的 Gdk.Monitor"""
    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        m = display.get_monitor(i)
        g = m.get_geometry()
        if g.x == x and g.y == y:
            return m
    return None


def locate():
    """返回 (Gdk.Monitor, 离屏幕右边的距离)；查不到时返回 None"""
    try:
        cur = _mmsg("cursorpos")
        mon = _mmsg("monitor", cur["monitor"])
        x, y = cur["x"] - mon["x"], cur["y"] - mon["y"]
        width, height = mon["width"], mon["height"]
        bar = bar_height()
        if not (height - bar <= y <= height and 0 <= x < width):
            return None  # 鼠标不在栏上（例如手机发起蓝牙配对时自动打开）
        r = subprocess.run([BARPROBE, cur["monitor"], str(width), str(mon.get("scale", 1)),
                            str(height - bar // 2), str(int(x))],
                           capture_output=True, text=True, timeout=0.5)
        if r.returncode != 0:
            return None
        left, right = map(int, r.stdout.split())
        return gdk_monitor(mon["x"], mon["y"]), max(0, width - right)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None
