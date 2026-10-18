#!/usr/bin/env python3
# 把 mango 的“有焦点的屏幕”和“可用区域”（屏幕去掉 waybar 的部分）告诉 X11 程序（XWayland）
#
# X11 程序从 XWayland 的 _NET_WORKAREA 知道可用区域，但 mango 不设置它，于是 X11 程序以为整个屏幕都能用。
# Typeless（X11 程序）按“可用区域的最下面”放浮动条、Ask Anything 等的卡片，
# 窗口大小变化、鼠标移到别的屏幕时还会重新这样放，所以下面一截会被 waybar 挡住。
#
# 这个程序常驻（mango 的 exec_once 启动），屏幕或焦点有变化时、XWayland 重新启动后：
#   1. XWayland 的主屏幕（XRandR 的 primary）设成 mango 里有焦点的屏幕
#   2. _NET_WORKAREA 设成那块屏幕的可用区域（Chromium / Electron 的程序只对主屏幕使用 _NET_WORKAREA）
#   typeless-windows.py 按 _NET_WORKAREA 把 Typeless 的浮动条、回答卡片移到有焦点的屏幕上
#
#   waybar 的位置和高度：从 waybar 的 config.jsonc 读（position、height）
#   哪些屏幕上有 waybar：mmsg get all-layers
#   XWayland 没有在运行时不去连接它（连接会让 mango 启动 XWayland）

import ctypes
import ctypes.util
import fcntl
import json
import os
import re
import select
import subprocess
import sys

WAYBAR_CONFIG = os.path.expanduser("~/.config/waybar/config.jsonc")
CHECK_INTERVAL = 5  # 秒：没有屏幕变化时也每隔这么久检查一次（XWayland 重新启动后值会消失）
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/xwayland-workarea-{os.getuid()}"
LOCK = os.path.join(RUNTIME, "xwayland-workarea.lock")


def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def mmsg_json(*args):
    try:
        return json.loads(run("mmsg", *args))
    except ValueError:
        return None


def waybar_size():
    """(位置, 高度)。读不到时高度是 0"""
    try:
        with open(WAYBAR_CONFIG) as f:
            text = f.read()
    except OSError:
        return "top", 0
    position = re.search(r'"position"\s*:\s*"(\w+)"', text)
    height = re.search(r'"height"\s*:\s*(\d+)', text)
    return (position.group(1) if position else "top"), (int(height.group(1)) if height else 0)


class ScreenResources(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("configTimestamp", ctypes.c_ulong),
                ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("noutput", ctypes.c_int), ("outputs", ctypes.POINTER(ctypes.c_ulong))]


class OutputInfo(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("crtc", ctypes.c_ulong),
                ("name", ctypes.c_char_p), ("nameLen", ctypes.c_int)]


class XWayland:
    """XWayland 的连接（用完就关：一直连着的话 XWayland 不会在没有 X11 程序时自动退出）"""

    def __init__(self):
        self.x11 = x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        self.xrandr = xrandr = ctypes.CDLL(ctypes.util.find_library("Xrandr"))
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        xrandr.XRRGetOutputPrimary.restype = ctypes.c_ulong
        xrandr.XRRGetOutputPrimary.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrandr.XRRSetOutputPrimary.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        xrandr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(ScreenResources)
        xrandr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrandr.XRRGetOutputInfo.restype = ctypes.POINTER(OutputInfo)
        xrandr.XRRGetOutputInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ScreenResources), ctypes.c_ulong]
        xrandr.XRRFreeOutputInfo.argtypes = [ctypes.POINTER(OutputInfo)]
        xrandr.XRRFreeScreenResources.argtypes = [ctypes.POINTER(ScreenResources)]
        self.display = x11.XOpenDisplay(None)
        self.root = x11.XDefaultRootWindow(self.display) if self.display else 0

    def close(self):
        if self.display:
            self.x11.XCloseDisplay(self.display)
            self.display = None

    def outputs(self):
        """{名字: output}（正在使用的屏幕。名字和 mango 的屏幕名一样）"""
        result = {}
        resources = self.xrandr.XRRGetScreenResourcesCurrent(self.display, self.root)
        if not resources:
            return result
        try:
            for i in range(resources.contents.noutput):
                output = resources.contents.outputs[i]
                info = self.xrandr.XRRGetOutputInfo(self.display, resources, output)
                if not info:
                    continue
                if info.contents.crtc:
                    result[info.contents.name.decode(errors="replace")] = output
                self.xrandr.XRRFreeOutputInfo(info)
        finally:
            self.xrandr.XRRFreeScreenResources(resources)
        return result

    def set_primary(self, name):
        output = self.outputs().get(name)
        if output and self.xrandr.XRRGetOutputPrimary(self.display, self.root) != output:
            self.xrandr.XRRSetOutputPrimary(self.display, self.root, output)
            self.x11.XSync(self.display, 0)



def workarea(monitor, with_bar):
    """屏幕的可用区域 (x, y, 宽, 高)"""
    x, y, w, h = monitor["x"], monitor["y"], monitor["width"], monitor["height"]
    if monitor["name"] in with_bar:
        position, size = waybar_size()
        if position == "bottom":
            h -= size
        elif position == "top":
            y += size
            h -= size
        elif position == "left":
            x += size
            w -= size
        elif position == "right":
            w -= size
    return x, y, w, h


def current():
    out = run("xprop", "-root", "_NET_WORKAREA")
    values = [int(v) for v in re.findall(r"\d+", out.partition("=")[2])]
    return tuple(values[:4]) if len(values) >= 4 else None


def update():
    if not run("pgrep", "-x", "Xwayland"):
        return
    data = mmsg_json("get", "all-monitors")
    layers = mmsg_json("get", "all-layers")
    if not isinstance(data, dict):
        return
    monitors = [m for m in data.get("monitors", []) if m.get("width", 0) > 0 and m.get("height", 0) > 0]
    active = next((m for m in monitors if m.get("active")), monitors[0] if monitors else None)
    if active is None:
        if current() is not None:
            run("xprop", "-root", "-remove", "_NET_WORKAREA")
        return
    layers = layers.get("layers", []) if isinstance(layers, dict) else (layers or [])
    with_bar = {layer.get("monitor") for layer in layers if layer.get("name") == "waybar"}

    xwl = XWayland()
    if not xwl.display:
        return
    try:
        if len(monitors) > 1:
            xwl.set_primary(active["name"])
        area = workarea(active, with_bar)
        if current() != area:
            run("xprop", "-root", "-f", "_NET_WORKAREA", "32c", "-set", "_NET_WORKAREA", ", ".join(map(str, area)))
    finally:
        xwl.close()


def main():
    os.makedirs(RUNTIME, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)  # 已经在运行

    # 屏幕、焦点有变化时 mmsg 输出一行；mango 退出时 mmsg 也结束，这个程序跟着结束
    watch = subprocess.Popen(["mmsg", "watch", "all-monitors"], stdout=subprocess.PIPE, text=True)
    update()
    while True:
        ready, _, _ = select.select([watch.stdout], [], [], CHECK_INTERVAL)
        if ready and not watch.stdout.readline():
            sys.exit(0)
        update()


if __name__ == "__main__":
    main()
