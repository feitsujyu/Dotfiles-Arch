#!/usr/bin/env python3
# 告诉 X11 程序（XWayland）“可用区域”：屏幕去掉 waybar 的部分
#
# X11 程序从 XWayland 的 _NET_WORKAREA 知道可用区域，但 mango 不设置它，于是 X11 程序以为整个屏幕都能用。
# Typeless（X11 程序）按“可用区域的最下面”放浮动条、Ask Anything 等的卡片，
# 窗口大小变化、鼠标移到别的屏幕时还会重新这样放，所以下面一截会被 waybar 挡住。
# 这个程序常驻（mango 的 exec_once 启动），屏幕有变化时、XWayland 重新启动后，重新设置 _NET_WORKAREA。
#
#   waybar 的位置和高度：从 waybar 的 config.jsonc 读（position、height）
#   哪些屏幕上有 waybar：mmsg get all-layers
#   多块屏幕时：_NET_WORKAREA 只能是一个长方形，Chromium / Electron 的程序（Typeless 等）只把它用在 XWayland 的
#     主屏幕上（其他屏幕当作整块都能用），所以设置成主屏幕的可用区域
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


def xwayland_primary():
    """XWayland 的主屏幕的名字（和 mango 的屏幕名一样）。没有设置主屏幕时是第一块屏幕（和 Chromium 一样）"""
    try:
        x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        xrandr = ctypes.CDLL(ctypes.util.find_library("Xrandr"))
    except OSError:
        return None
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xrandr.XRRGetOutputPrimary.restype = ctypes.c_ulong
    xrandr.XRRGetOutputPrimary.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

    class ScreenResources(ctypes.Structure):
        _fields_ = [("timestamp", ctypes.c_ulong), ("configTimestamp", ctypes.c_ulong),
                    ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                    ("noutput", ctypes.c_int), ("outputs", ctypes.POINTER(ctypes.c_ulong))]

    class OutputInfo(ctypes.Structure):
        _fields_ = [("timestamp", ctypes.c_ulong), ("crtc", ctypes.c_ulong),
                    ("name", ctypes.c_char_p), ("nameLen", ctypes.c_int)]

    xrandr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(ScreenResources)
    xrandr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xrandr.XRRGetOutputInfo.restype = ctypes.POINTER(OutputInfo)
    xrandr.XRRGetOutputInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ScreenResources), ctypes.c_ulong]
    xrandr.XRRFreeOutputInfo.argtypes = [ctypes.POINTER(OutputInfo)]
    xrandr.XRRFreeScreenResources.argtypes = [ctypes.POINTER(ScreenResources)]

    display = x11.XOpenDisplay(None)
    if not display:
        return None
    try:
        root = x11.XDefaultRootWindow(display)
        resources = xrandr.XRRGetScreenResourcesCurrent(display, root)
        if not resources:
            return None
        try:
            outputs = [resources.contents.outputs[i] for i in range(resources.contents.noutput)]
            primary = xrandr.XRRGetOutputPrimary(display, root)
            for output in ([primary] if primary else []) + outputs:
                info = xrandr.XRRGetOutputInfo(display, resources, output)
                if not info:
                    continue
                try:
                    if info.contents.crtc:  # 正在使用的屏幕
                        return info.contents.name.decode(errors="replace")
                finally:
                    xrandr.XRRFreeOutputInfo(info)
            return None
        finally:
            xrandr.XRRFreeScreenResources(resources)
    finally:
        x11.XCloseDisplay(display)


def workarea():
    """XWayland 的主屏幕的可用区域 (x, y, 宽, 高)；算不出来时 None"""
    try:
        monitors = json.loads(run("mmsg", "get", "all-monitors"))["monitors"]
        layers = json.loads(run("mmsg", "get", "all-layers"))
        layers = layers.get("layers", []) if isinstance(layers, dict) else layers
    except (ValueError, KeyError, TypeError):
        return None
    with_bar = {layer.get("monitor") for layer in layers if layer.get("name") == "waybar"}
    position, size = waybar_size()
    primary = xwayland_primary()

    for m in monitors:
        x, y, w, h = m["x"], m["y"], m["width"], m["height"]
        if m["name"] != primary or w <= 0 or h <= 0:
            continue
        if m["name"] in with_bar:
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
    return None


def current():
    out = run("xprop", "-root", "_NET_WORKAREA")
    values = [int(v) for v in re.findall(r"\d+", out.partition("=")[2])]
    return tuple(values[:4]) if len(values) >= 4 else None


def update():
    if not run("pgrep", "-x", "Xwayland"):
        return
    area = workarea()
    if area is None:
        if current() is not None:
            run("xprop", "-root", "-remove", "_NET_WORKAREA")
        return
    if current() != area:
        run("xprop", "-root", "-f", "_NET_WORKAREA", "32c", "-set", "_NET_WORKAREA", ", ".join(map(str, area)))


def main():
    os.makedirs(RUNTIME, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)  # 已经在运行

    # 屏幕有变化时 mmsg 输出一行；mango 退出时 mmsg 也结束，这个程序跟着结束
    watch = subprocess.Popen(["mmsg", "watch", "all-monitors"], stdout=subprocess.PIPE, text=True)
    update()
    while True:
        ready, _, _ = select.select([watch.stdout], [], [], CHECK_INTERVAL)
        if ready and not watch.stdout.readline():
            sys.exit(0)
        update()


if __name__ == "__main__":
    main()
