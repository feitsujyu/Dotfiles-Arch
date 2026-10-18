#!/usr/bin/env python3
# Typeless 的浮动条（透明的窗口）：空白的地方让鼠标“穿过去”，点到后面的窗口（常驻，mango 的 exec_once 启动）
#
# Typeless 在 Linux 上用 X11 的 shape 只把按钮等的部分设成窗口的形状（bounding shape），其他地方是“没有窗口”。
# 纯 X11 里这样鼠标就会穿过去，但 XWayland 告诉 mango“哪里接收鼠标”时只看 input shape（一直是整个窗口），
# 所以 mango 以为整个浮动条都接收鼠标：鼠标一移上去焦点就到了浮动条，点击、滚动都到不了后面的窗口。
# 这里每隔 INTERVAL 秒把浮动条的 input shape 设成和 bounding shape 一样（按钮等的部分照常能点）。
#
#   Typeless 在运行时才连接 XWayland（连接会让 mango 启动 XWayland，也会让它不自动退出）
#   和 XWayland 的连接断了（XWayland 重新启动等）时，重新连接

import ctypes
import ctypes.util
import fcntl
import os
import subprocess
import sys
import time

BAR_CLASS = b"Typeless-floating-bar"  # 浮动条的 WM_CLASS
INTERVAL = 0.1  # 秒：检查的间隔（按钮出现 / 消失后最多这么久就能点 / 穿过去）
RESCAN = 2.0  # 秒：重新找浮动条的窗口、检查 Typeless 还在不在的间隔
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/typeless-clickthrough-{os.getuid()}"
LOCK = os.path.join(RUNTIME, "typeless-clickthrough.lock")

SHAPE_BOUNDING, SHAPE_INPUT, SHAPE_SET = 0, 2, 0


def running(name):
    return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0


class Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("w", ctypes.c_ushort), ("h", ctypes.c_ushort)]


class ClassHint(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


def sync():
    """连接 XWayland，Typeless 运行期间一直同步。XWayland 断开时这个进程会结束（由 main 重新启动）"""
    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    xext = ctypes.CDLL(ctypes.util.find_library("Xext"))
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                               ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                               ctypes.POINTER(ctypes.c_uint)]
    x11.XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ClassHint)]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    xext.XShapeGetRectangles.restype = ctypes.POINTER(Rect)
    xext.XShapeGetRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                         ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    xext.XShapeCombineShape.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]

    # 窗口已经关掉等的错误（BadWindow）不理会（默认的处理会结束程序）
    error_handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda *_: 0)
    x11.XSetErrorHandler(error_handler)

    display = x11.XOpenDisplay(None)
    if not display:
        return
    root = x11.XDefaultRootWindow(display)

    def find_bars():
        bars = []
        r, p, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_uint()
        children = ctypes.POINTER(ctypes.c_ulong)()
        if not x11.XQueryTree(display, root, ctypes.byref(r), ctypes.byref(p), ctypes.byref(children), ctypes.byref(n)):
            return bars
        for i in range(n.value):
            hint = ClassHint()
            if x11.XGetClassHint(display, children[i], ctypes.byref(hint)):
                if ctypes.string_at(hint.res_class) == BAR_CLASS:
                    bars.append(children[i])
                x11.XFree(hint.name)
                x11.XFree(hint.res_class)
        if children:
            x11.XFree(children)
        return bars

    def rects(window, kind):
        count, ordering = ctypes.c_int(), ctypes.c_int()
        p = xext.XShapeGetRectangles(display, window, kind, ctypes.byref(count), ctypes.byref(ordering))
        result = [(p[i].x, p[i].y, p[i].w, p[i].h) for i in range(count.value)]
        if p:
            x11.XFree(p)
        return result

    bars, scanned = [], 0.0
    while True:
        now = time.monotonic()
        if now - scanned >= RESCAN:
            if not running("typeless"):
                return
            bars, scanned = find_bars(), now
        for window in bars:
            if rects(window, SHAPE_INPUT) != rects(window, SHAPE_BOUNDING):
                xext.XShapeCombineShape(display, window, SHAPE_INPUT, 0, 0, window, SHAPE_BOUNDING, SHAPE_SET)
                x11.XFlush(display)
        time.sleep(INTERVAL)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "sync":
        sync()
        return
    os.makedirs(RUNTIME, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)  # 已经在运行
    # Typeless 和 XWayland 都在运行时启动同步的进程；它结束（Typeless 退出、XWayland 断开）后再等
    while True:
        if running("typeless") and running("Xwayland"):
            subprocess.run([sys.executable, os.path.abspath(__file__), "sync"])
        time.sleep(RESCAN)


if __name__ == "__main__":
    main()
