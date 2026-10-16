#!/usr/bin/env python3
# 亮度弹窗：点击 waybar 的亮度模块时，从模块上方淡入显示
#
# 做法和音量弹窗（volume-popup.py）相同：
# · 常驻后台（平时隐藏），收到 SIGUSR1 时 显示 ⇄ 隐藏（由 brightness-popup-toggle.sh 发送）
# · gtk-layer-shell 的图层，图层名 “brightness-menu”；淡入淡出 FADE_MS（0.2 秒）由程序自己做，
#   mango 那边对这个图层设置 no_animation:1
# · 点击外面自动关闭（后面铺一层完全透明的全屏图层 “brightness-menu-catcher”）
# · 打开时查一下模块现在的位置，弹窗的右边对准模块的右边（popup_anchor.py）
#
# 画面：亮度滑块 + 百分比、常用亮度的按钮（25 / 50 / 75 / 100%）
#
# 亮度的修改：/sys/class/backlight/*/brightness 只有 root 可以写，所以通过 systemd-logind 的
# SetBrightness（DBus）修改，和 ~/.config/mango/scripts/brightness.sh（亮度键用）相同。
# 打开期间每 POLL_MS 读一次现在的亮度，用亮度键改了亮度时，滑块也会跟着变。
# 操作：← → / ↑ ↓ → 调亮度  Esc / 点外面 / 再点一次亮度模块 → 关闭

import glob
import os
import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLibUnix", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, GLibUnix, Gtk, GtkLayerShell  # noqa: E402

# 弹窗位置的计算（和其他弹窗共用，popup_anchor.py）
sys.dont_write_bytecode = True  # 不在 scripts 目录里生成 __pycache__
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import popup_anchor  # noqa: E402

# ---------- 设置 ----------
FADE_MS = 200           # 淡入 / 淡出的时间（毫秒）
WIDTH = 360             # 弹窗宽度
MARGIN_RIGHT = 189      # 离屏幕右边的距离（只在查不到模块位置时使用，见 place）
MARGIN_BOTTOM = 8       # 离 waybar 的距离
MIN_PERCENT = 5         # 最低亮度（%），防止屏幕完全变黑看不见（和 brightness.sh 相同）
PRESETS = (25, 50, 75, 100)
SET_INTERVAL_MS = 40    # 拖动滑块时，最多每隔多少毫秒实际设置一次亮度
POLL_MS = 300           # 打开期间读取现在亮度的间隔
NAMESPACE = "brightness-menu"

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
PIDFILE = os.path.join(RUNTIME, f"brightness-popup-{os.environ.get('WAYLAND_DISPLAY', 'wayland-0')}.pid")

ICONS = ["󰃞", "󰃟", "󰃠"]  # 暗 / 中 / 亮

CSS = """
window, window.background { background-color: transparent; }
#panel {
    background-color: rgba(31, 26, 61, 0.94);
    border: 3px solid #f5a0c8;
    border-radius: 10px;
    padding: 12px;
}
* { font-family: "JetBrainsMono Nerd Font", "Noto Sans CJK SC"; font-size: 13pt; color: #c9b9f2; }
#title {
    background-color: #f5a0c8; color: #1f1a3d;
    border-radius: 8px; padding: 4px 12px; font-weight: bold;
}
.sub { color: #8e8c9e; font-size: 10pt; }
.percent { min-width: 48px; }
.icon { min-width: 32px; font-size: 15pt; color: #f5a0c8; }
/* transition: none —— 关掉系统主题（Adwaita）给按钮加的过渡动画（和其他弹窗一样） */
button {
    background-color: #3a3470; background-image: none; color: #c9b9f2;
    border: none; border-radius: 8px; box-shadow: none; text-shadow: none;
    padding: 4px 8px; min-height: 0; transition: none;
}
button label { color: #c9b9f2; font-size: 11pt; }
button:hover { background-color: #6c5cc4; }
button.current { background-color: #f5a0c8; }
button.current label { color: #1f1a3d; font-weight: bold; }
scale { padding: 0 4px; min-height: 0; }
scale trough {
    background-color: #3a3470; background-image: none; border: none;
    border-radius: 4px; min-height: 6px; box-shadow: none;
}
scale highlight { background-color: #f5a0c8; background-image: none; border: none; border-radius: 4px; }
scale slider {
    background-color: #f5a0c8; background-image: none; border: 2px solid #1f1a3d;
    border-radius: 10px; min-width: 18px; min-height: 18px; box-shadow: none; margin: -7px 0;
}
"""


def backlight_device():
    devs = sorted(glob.glob("/sys/class/backlight/*"))
    return devs[0] if devs else None


def read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def brightness_icon(pct):
    return ICONS[0 if pct < 34 else 1 if pct < 67 else 2]


class Backlight:
    """亮度的读取（sysfs）和修改（logind 的 SetBrightness）"""

    def __init__(self):
        self.dev = backlight_device()
        self.name = os.path.basename(self.dev) if self.dev else None
        self.max = read_int(os.path.join(self.dev, "max_brightness")) if self.dev else None
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.session = "/org/freedesktop/login1/session/auto"
        sid = os.environ.get("XDG_SESSION_ID")
        if sid:  # mango 所在的登录会话（从别的终端启动时，auto 不一定是这个会话）
            try:
                r = self.bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1",
                                       "org.freedesktop.login1.Manager", "GetSession",
                                       GLib.Variant("(s)", (sid,)), GLib.VariantType("(o)"),
                                       Gio.DBusCallFlags.NONE, 2000, None)
                self.session = r.unpack()[0]
            except GLib.Error:
                pass

    def ok(self):
        return bool(self.dev and self.max)

    def percent(self):
        cur = read_int(os.path.join(self.dev, "brightness"))
        return None if cur is None else round(cur * 100 / self.max)

    def set_percent(self, pct):
        pct = max(MIN_PERCENT, min(100, int(pct)))
        self.bus.call("org.freedesktop.login1", self.session, "org.freedesktop.login1.Session",
                      "SetBrightness", GLib.Variant("(ssu)", ("backlight", self.name, self.max * pct // 100)),
                      None, Gio.DBusCallFlags.NONE, 2000, None, None)


class BrightnessPopup:
    def __init__(self):
        self.visible = False
        self.fade_target = 0.0
        self.last_user = 0.0     # 用户最后一次动滑块的时间
        self.pending = None
        self.timer = None
        self.poll_id = None
        self.bl = Backlight()

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = self.make_window(NAMESPACE, catcher=False)
        self.catcher = self.make_window(NAMESPACE + "-catcher", catcher=True)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, name="panel")
        self.panel.set_size_request(WIDTH, -1)
        self.build()
        self.win.add(self.panel)
        self.win.connect("key-press-event", self.on_key)
        self.panel.show_all()
        self.panel.set_opacity(0.0)

    # ---------- 画面 ----------
    def build(self):
        head = Gtk.Box(spacing=8)
        head.pack_start(Gtk.Label(label="亮度", name="title"), False, False, 0)
        sub = Gtk.Label(label="内置屏幕" if self.bl.ok() else "没有找到可以调亮度的屏幕", xalign=0)
        sub.get_style_context().add_class("sub")
        head.pack_start(sub, True, True, 0)
        self.panel.pack_start(head, False, False, 0)

        line = Gtk.Box(spacing=6)
        self.icon = Gtk.Label()
        self.icon.get_style_context().add_class("icon")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, MIN_PERCENT, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_increments(1, 5)
        self.scale.set_hexpand(True)
        self.handler = self.scale.connect("value-changed", self.changed)
        self.label = Gtk.Label(xalign=1)
        self.label.get_style_context().add_class("percent")
        line.pack_start(self.icon, False, False, 0)
        line.pack_start(self.scale, True, True, 0)
        line.pack_start(self.label, False, False, 0)
        self.panel.pack_start(line, False, False, 0)

        presets = Gtk.Box(spacing=8, homogeneous=True)
        self.preset_btns = {}
        for p in PRESETS:
            b = Gtk.Button(label=f"{p}%")
            b.connect("clicked", lambda _b, p=p: self.scale.set_value(p))
            presets.pack_start(b, True, True, 0)
            self.preset_btns[p] = b
        self.panel.pack_start(presets, False, False, 0)
        self.panel.set_sensitive(self.bl.ok())

    def update_labels(self, pct):
        self.icon.set_text(brightness_icon(pct))
        self.label.set_text(f"{pct}%")
        for p, b in self.preset_btns.items():
            ctx = b.get_style_context()
            (ctx.add_class if p == pct else ctx.remove_class)("current")

    def sync(self):
        """现在的亮度 → 画面（拖动中不更新滑块位置，否则滑块会被拉回去）"""
        if not self.bl.ok():
            return
        pct = self.bl.percent()
        if pct is None:
            return
        if time.monotonic() - self.last_user > 0.4 and self.pending is None:
            self.scale.handler_block(self.handler)
            self.scale.set_value(max(MIN_PERCENT, pct))
            self.scale.handler_unblock(self.handler)
            self.update_labels(pct)

    def poll(self):
        if not self.visible:
            self.poll_id = None
            return False
        self.sync()
        return True

    def changed(self, scale):
        v = int(round(scale.get_value()))
        self.last_user = time.monotonic()
        self.update_labels(v)
        self.pending = v
        if self.timer is None:  # 限制频率：最多每 SET_INTERVAL_MS 实际设置一次
            self.flush()
            self.timer = GLib.timeout_add(SET_INTERVAL_MS, self.tick)

    def tick(self):
        if self.pending is None:
            self.timer = None
            return False
        self.flush()
        return True

    def flush(self):
        v, self.pending = self.pending, None
        if v is not None and self.bl.ok():
            self.bl.set_percent(v)

    # ---------- 窗口（和其他弹窗相同的做法） ----------
    def make_window(self, namespace, catcher):
        win = Gtk.Window()
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        win.set_app_paintable(True)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, namespace)
        if catcher:
            GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
            for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                      GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(win, e, True)
            GtkLayerShell.set_exclusive_zone(win, -1)
            GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
            win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            win.connect("button-press-event", lambda *_: self.hide())
        else:
            GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(win, GtkLayerShell.Edge.BOTTOM, MARGIN_BOTTOM)
            GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT, MARGIN_RIGHT)
            GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        win.connect("delete-event", lambda *_: (self.hide(), True)[1])
        return win

    def place(self):
        """查一下“现在”模块在哪里，弹窗的右边对准模块的右边，显示在点击的那块屏幕上
        （查不到时保持上一次的位置，第一次是 MARGIN_RIGHT）"""
        pos = popup_anchor.locate()
        if pos is None:
            return
        monitor, margin = pos
        if monitor is not None:
            for w in (self.win, self.catcher):
                GtkLayerShell.set_monitor(w, monitor)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.RIGHT, margin)

    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()
        return False

    def show(self):
        if self.visible:
            return
        self.visible = True
        self.place()
        self.last_user = 0.0
        self.sync()
        self.catcher.show()
        self.win.show()
        self.scale.grab_focus()  # ← → / ↑ ↓ 可以直接调亮度
        self.win.resize(WIDTH, 1)
        self.fade_to(1.0)
        if self.poll_id is None:
            self.poll_id = GLib.timeout_add(POLL_MS, self.poll)

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.fade_to(0.0)

    def fade_to(self, target):
        self.fade_target = target
        start = self.panel.get_opacity()
        t0 = time.monotonic()

        def tick(widget, clock):
            if self.fade_target != target:
                return False
            p = min(1.0, (time.monotonic() - t0) * 1000 / FADE_MS) if FADE_MS > 0 else 1.0
            ease = 1 - (1 - p) ** 2
            self.panel.set_opacity(start + (target - start) * ease)
            if p >= 1.0:
                if target == 0.0:
                    self.win.hide()
                    self.catcher.hide()
                return False
            return True
        self.panel.add_tick_callback(tick)

    def on_key(self, win, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False


def main():
    show_now = "--show" in sys.argv
    try:
        pid = int(open(PIDFILE).read())
        if pid != os.getpid() and "brightness-popup.py" in open(f"/proc/{pid}/cmdline").read():
            os.kill(pid, signal.SIGUSR1)
            return
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    popup = BrightnessPopup()
    # 不能在信号的回调里直接显示窗口（会卡在 gtk-layer-shell 显示图层的地方），所以交给 idle
    GLibUnix.signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1,
                        lambda: (GLib.idle_add(popup.toggle), True)[1])
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (Gtk.main_quit(), False)[1])
    if show_now:
        GLib.idle_add(lambda: (popup.show(), False)[1])
    try:
        Gtk.main()
    finally:
        try:
            if open(PIDFILE).read().strip() == str(os.getpid()):
                os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
