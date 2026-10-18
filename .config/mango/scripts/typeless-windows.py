#!/usr/bin/env python3
# Typeless 的浮动条、回答卡片的整理（常驻，mango 的 exec_once 启动）
#
# 1. 浮动条（透明的窗口）的空白处让鼠标“穿过去”，点到后面的窗口
#    Typeless 在 Linux 上用 X11 的 shape 只把按钮等的部分设成窗口的形状（bounding shape），其他地方是“没有窗口”。
#    纯 X11 里这样鼠标就会穿过去，但 XWayland 告诉 mango“哪里接收鼠标”时只看 input shape（一直是整个窗口），
#    所以 mango 以为整个浮动条都接收鼠标：鼠标一移上去焦点就到了浮动条，点击、滚动都到不了后面的窗口。
#    这里把浮动条的 input shape 设成和 bounding shape 一样（按钮等的部分照常能点）。
# 2. 接了外接显示器时，浮动条、回答卡片放到 mango 里有焦点的屏幕上
#    Typeless 本来会放在“鼠标所在的屏幕”，但它只在鼠标经过它自己的窗口时才知道鼠标的位置（XWayland 的限制），
#    所以一直以为鼠标在原来的屏幕上。这里把它们移到有焦点的屏幕（和 Typeless 自己放的位置一样：
#    浮动条在可用区域的最下面、回答卡片再往上 20 像素，水平居中）。
#    浮动条不在这个位置就移（拔掉屏幕时 mango 会把它移到别的地方）；回答卡片只在它不在有焦点的屏幕上时移（可以自己拖动）
#    有焦点的屏幕和它的可用区域：xwayland-workarea.py 设置的 _NET_WORKAREA
#    回答卡片在内容变化时 Typeless 会按它以为的屏幕重新放，所以回答出来的过程中可能会跳回去一下（这里马上再移过来）
#
#   每隔 INTERVAL 秒检查一次。Typeless 在运行时才连接 XWayland（连接会让 mango 启动 XWayland，也会让它不自动退出）
#   和 XWayland 的连接断了（XWayland 重新启动等）时，重新连接

import ctypes
import ctypes.util
import fcntl
import os
import subprocess
import sys
import time

BAR_CLASS = b"Typeless-floating-bar"  # 浮动条的 WM_CLASS
CARD_CLASS = b"Typeless"  # 回答卡片的 WM_CLASS（和主窗口一样）
CARD_TITLES = {b"Status", b"AI result"}  # 回答卡片的标题（主窗口是 Typeless）
CARD_BOTTOM_MARGIN = 20  # 像素：回答卡片的下边离可用区域的下边（和 Typeless 一样）
INTERVAL = 0.1  # 秒：检查的间隔
RESCAN = 2.0  # 秒：检查 Typeless 还在不在的间隔
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/typeless-windows-{os.getuid()}"
LOCK = os.path.join(RUNTIME, "typeless-windows.lock")

SHAPE_BOUNDING, SHAPE_INPUT, SHAPE_SET = 0, 2, 0
XA_CARDINAL = 6
IS_VIEWABLE = 2


def running(name):
    return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0


class Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("w", ctypes.c_ushort), ("h", ctypes.c_ushort)]


class ClassHint(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class WindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


def sync():
    """连接 XWayland，Typeless 运行期间一直整理。XWayland 断开时这个进程会结束（由 main 重新启动）"""
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
    x11.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
    x11.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(WindowAttributes)]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
                                       ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                       ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    x11.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
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
    net_workarea = x11.XInternAtom(display, b"_NET_WORKAREA", 0)

    def text(pointer):
        value = ctypes.string_at(pointer) if pointer else b""
        if pointer:
            x11.XFree(pointer)
        return value

    def windows():
        """(浮动条, 回答卡片) 的窗口（只要显示着的）"""
        bars, cards = [], []
        r, p, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_uint()
        children = ctypes.POINTER(ctypes.c_ulong)()
        if not x11.XQueryTree(display, root, ctypes.byref(r), ctypes.byref(p), ctypes.byref(children), ctypes.byref(n)):
            return bars, cards
        for i in range(n.value):
            window, hint = children[i], ClassHint()
            if not x11.XGetClassHint(display, window, ctypes.byref(hint)):
                continue
            text(hint.name)
            res_class = text(hint.res_class)
            if res_class == BAR_CLASS:
                bars.append(window)
            elif res_class == CARD_CLASS:
                name = ctypes.c_void_p()
                x11.XFetchName(display, window, ctypes.byref(name))
                if text(name.value) in CARD_TITLES:
                    cards.append(window)
        if children:
            x11.XFree(children)
        return bars, cards

    def geometry(window):
        """显示着的话 (x, y, 宽, 高)，否则 None"""
        attributes = WindowAttributes()
        if not x11.XGetWindowAttributes(display, window, ctypes.byref(attributes)):
            return None
        if attributes.map_state != IS_VIEWABLE:
            return None
        return attributes.x, attributes.y, attributes.width, attributes.height

    def workarea():
        """有焦点的屏幕的可用区域（_NET_WORKAREA）"""
        actual_type, actual_format = ctypes.c_ulong(), ctypes.c_int()
        count, remaining, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        status = x11.XGetWindowProperty(display, root, net_workarea, 0, 4, 0, XA_CARDINAL, ctypes.byref(actual_type),
                                        ctypes.byref(actual_format), ctypes.byref(count), ctypes.byref(remaining),
                                        ctypes.byref(data))
        if status != 0 or not data.value:
            return None
        values = ctypes.cast(data, ctypes.POINTER(ctypes.c_long))
        area = tuple(values[i] for i in range(4)) if count.value >= 4 else None
        x11.XFree(data)
        return area

    def rects(window, kind):
        count, ordering = ctypes.c_int(), ctypes.c_int()
        p = xext.XShapeGetRectangles(display, window, kind, ctypes.byref(count), ctypes.byref(ordering))
        result = [(p[i].x, p[i].y, p[i].w, p[i].h) for i in range(count.value)]
        if p:
            x11.XFree(p)
        return result

    def follow(window, area, bottom_margin, exact):
        """移到可用区域的最下面（往上 bottom_margin 像素）、水平居中（和 Typeless 自己放的位置一样）
        exact：不在这个位置就移（浮动条）；否则只在窗口的中心不在可用区域里时移（回答卡片：可以自己拖到别的地方）"""
        box = geometry(window)
        if box is None:
            return
        x, y, w, h = box
        ax, ay, aw, ah = area
        target = (ax + (aw - w) // 2, max(ay, ay + ah - bottom_margin - h))
        if exact:
            if (x, y) == target:
                return
        else:
            cx, cy = x + w // 2, y + h // 2
            if ax <= cx < ax + aw and ay <= cy < ay + ah:
                return
        x11.XMoveWindow(display, window, *target)

    bars, cards, scanned = [], [], 0.0
    while True:
        now = time.monotonic()
        if now - scanned >= RESCAN:
            if not running("typeless"):
                return
            scanned = now
        # 回答卡片随时会出现，所以每次都重新找
        bars, cards = windows()
        area = workarea()
        for window in bars:
            if rects(window, SHAPE_INPUT) != rects(window, SHAPE_BOUNDING):
                xext.XShapeCombineShape(display, window, SHAPE_INPUT, 0, 0, window, SHAPE_BOUNDING, SHAPE_SET)
            if area:
                follow(window, area, 0, exact=True)
        if area:
            for window in cards:
                follow(window, area, CARD_BOTTOM_MARGIN, exact=False)
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
    # Typeless 和 XWayland 都在运行时启动整理的进程；它结束（Typeless 退出、XWayland 断开）后再等
    while True:
        if running("typeless") and running("Xwayland"):
            subprocess.run([sys.executable, os.path.abspath(__file__), "sync"])
        time.sleep(RESCAN)


if __name__ == "__main__":
    main()
