#!/usr/bin/env python3
# 音量弹窗：点击 waybar 的音量模块时，从模块上方淡入显示
#
# 做法和 Wi-Fi 弹窗（wifi-popup.py）相同：
# · 常驻后台（平时隐藏），收到 SIGUSR1 时 显示 ⇄ 隐藏（由 volume-popup-toggle.sh 发送）
# · gtk-layer-shell 的图层，图层名 “volume-menu”；淡入淡出 FADE_MS（0.2 秒）由程序自己做，
#   mango 那边对这个图层设置 no_animation:1
# · 点击外面自动关闭（后面铺一层完全透明的全屏图层 “volume-menu-catcher”）
#
# 画面：
# · 主画面：静音按钮 + 音量滑块 + 百分比、输出设备选择、“各个程序单独音量” 按钮
# · 各程序音量画面：正在播放声音的程序，每个一行（静音按钮 + 滑块 + 百分比），“‹ 返回” 回到主画面
#
# 音量的读取 / 设置用 pactl（PipeWire 的 pipewire-pulse 提供兼容接口）；
# `pactl subscribe` 监听变化，音量键等从别处改了音量时，弹窗里的滑块也会马上跟着变。
# 操作：Esc → 在各程序音量画面时回到主画面，在主画面时关闭；点外面 / 再点一次音量模块 → 关闭

import json
import os
import signal
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLibUnix", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, GLibUnix, Gtk, GtkLayerShell, Pango  # noqa: E402

# 弹窗位置的计算（和其他弹窗共用，popup_anchor.py）
sys.dont_write_bytecode = True  # 不在 scripts 目录里生成 __pycache__
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import popup_anchor  # noqa: E402

# ---------- 设置 ----------
FADE_MS = 200           # 淡入 / 淡出的时间（毫秒）
WIDTH = 400             # 弹窗宽度
MARGIN_RIGHT = 191      # 离屏幕右边的距离（对准 waybar 的音量模块）
#   每次打开时会查模块的实际位置（place），这个值只在查不到时使用
MARGIN_BOTTOM = 8       # 离 waybar 的距离
MAX_VOLUME = 100        # 滑块的最大值（%）
SET_INTERVAL_MS = 40    # 拖动滑块时，最多每隔多少毫秒实际设置一次音量
NAMESPACE = "volume-menu"

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
PIDFILE = os.path.join(RUNTIME, f"volume-popup-{os.environ.get('WAYLAND_DISPLAY', 'wayland-0')}.pid")

ICON_MUTED = "󰝟"
ICON_LEVELS = ["󰕿", "󰖀", "󰕾"]  # 小 / 中 / 大
CHECK = "󰄬"

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
.section { color: #8e8c9e; font-size: 11pt; margin-top: 4px; }
.sub { color: #8e8c9e; font-size: 10pt; }
.percent { min-width: 48px; }
/* transition: none —— 关掉系统主题（Adwaita）给按钮、行加的过渡动画（和 Wi-Fi 弹窗一样） */
button {
    background-color: transparent; background-image: none; color: #c9b9f2;
    border: none; border-radius: 8px; box-shadow: none; text-shadow: none;
    padding: 4px 8px; min-height: 0; transition: none;
}
button label { color: #c9b9f2; }
button:hover { background-color: rgba(58, 52, 112, 0.85); }
button.mute { min-width: 32px; font-size: 15pt; }
button.mute.muted label { color: #f07a9a; }
button.nav { background-color: #3a3470; padding: 6px 10px; }
button.nav:hover { background-color: #6c5cc4; }
button.nav label { color: #c9b9f2; }
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
scale.muted highlight, scale.muted slider { background-color: #8e8c9e; }
list, scrolledwindow, viewport { background-color: transparent; border: none; }
row { padding: 4px 8px; border-radius: 8px; background-color: transparent; outline: none; transition: none; }
row:hover { background-color: rgba(58, 52, 112, 0.85); }
row:selected, row:selected:hover { background-color: transparent; }
row.current label { color: #f5a0c8; }
row.current { background-color: rgba(108, 92, 196, 0.35); }
separator { background-color: rgba(108, 92, 196, 0.5); min-height: 1px; margin: 4px 0; }
#empty { color: #8e8c9e; padding: 12px; }
"""


# ---------- pactl ----------

def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True)


def pactl_json(kind):
    r = subprocess.run(["pactl", "-f", "json", "list", kind], capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "[]")
    except ValueError:
        return []


def percent(vol):
    """pactl 的 volume（每个声道一个值）→ 百分比（取最大的声道）"""
    vals = []
    for ch in (vol or {}).values():
        try:
            vals.append(int(str(ch.get("value_percent", "0")).rstrip("%")))
        except ValueError:
            pass
    return max(vals) if vals else 0


def load_state():
    """在后台线程里读取：默认设备、所有设备、各程序的声音"""
    default = pactl("get-default-sink").stdout.strip()
    sinks = [{
        "name": s["name"],
        "desc": s.get("description") or s["name"],
        "volume": percent(s.get("volume")),
        "mute": bool(s.get("mute")),
        "index": s["index"],
    } for s in pactl_json("sinks")]
    apps = []
    for i in pactl_json("sink-inputs"):
        props = i.get("properties", {})
        name = (props.get("application.name") or props.get("application.process.binary")
                or props.get("media.name") or f"#{i['index']}")
        media = props.get("media.name", "")
        apps.append({
            "index": i["index"],
            "name": name,
            "media": media if media and media != name else "",
            "volume": percent(i.get("volume")),
            "mute": bool(i.get("mute")),
        })
    return default, sinks, apps


def run_bg(func, done=None, *args):
    def work():
        try:
            res = func(*args)
        except Exception as e:  # noqa: BLE001
            res = e
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=work, daemon=True).start()


def volume_icon(vol, mute):
    if mute or vol == 0:
        return ICON_MUTED
    return ICON_LEVELS[0 if vol < 34 else 1 if vol < 67 else 2]


class VolumeControl(Gtk.Box):
    """静音按钮 + 滑块 + 百分比（主音量、各程序音量共用）"""

    def __init__(self, on_volume, on_mute):
        super().__init__(spacing=6)
        self.on_volume, self.on_mute = on_volume, on_mute
        self.last_user = 0.0  # 用户最后一次动滑块的时间
        self.pending = None
        self.timer = None
        self.mute = False
        self.btn = Gtk.Button()
        self.btn.get_style_context().add_class("mute")
        self.btn.connect("clicked", lambda *_: self.on_mute(not self.mute))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, MAX_VOLUME, 1)
        self.scale.set_draw_value(False)
        self.scale.set_increments(1, 5)
        self.scale.set_hexpand(True)
        self.handler = self.scale.connect("value-changed", self.changed)
        self.label = Gtk.Label(xalign=1)
        self.label.get_style_context().add_class("percent")
        self.pack_start(self.btn, False, False, 0)
        self.pack_start(self.scale, True, True, 0)
        self.pack_start(self.label, False, False, 0)

    def update(self, vol, mute):
        """外部的值 → 画面（拖动中不更新滑块位置）"""
        self.mute = mute
        self.btn.set_label(volume_icon(vol, mute))
        for w in (self.btn, self.scale):
            ctx = w.get_style_context()
            (ctx.add_class if mute else ctx.remove_class)("muted")
        # 用户正在拖动（最后一次操作后 0.4 秒内）时不更新滑块位置，否则滑块会被拉回去
        if time.monotonic() - self.last_user > 0.4 and self.pending is None:
            self.scale.handler_block(self.handler)
            self.scale.set_value(min(vol, MAX_VOLUME))
            self.scale.handler_unblock(self.handler)
            self.label.set_text(f"{vol}%")

    def changed(self, scale):
        v = int(round(scale.get_value()))
        self.last_user = time.monotonic()
        self.label.set_text(f"{v}%")
        self.btn.set_label(volume_icon(v, self.mute))
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
        if v is not None:
            run_bg(self.on_volume, None, v)


class AppRow(Gtk.ListBoxRow):
    def __init__(self, app):
        super().__init__()
        self.index = app["index"]
        self.set_activatable(False)
        self.set_selectable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        top = Gtk.Box(spacing=8)
        name = Gtk.Label(label=app["name"], xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        top.pack_start(name, True, True, 0)
        box.pack_start(top, False, False, 0)
        if app["media"]:
            media = Gtk.Label(label=app["media"], xalign=0)
            media.set_ellipsize(Pango.EllipsizeMode.END)
            media.get_style_context().add_class("sub")
            box.pack_start(media, False, False, 0)
        idx = self.index
        self.control = VolumeControl(
            lambda v: pactl("set-sink-input-volume", str(idx), f"{v}%"),
            lambda m: run_bg(lambda: pactl("set-sink-input-mute", str(idx), "1" if m else "0")))
        box.pack_start(self.control, False, False, 0)
        self.add(box)
        self.control.update(app["volume"], app["mute"])
        self.show_all()


class VolumePopup:
    def __init__(self):
        self.visible = False
        self.fade_target = 0.0
        self.default = ""
        self.refresh_pending = False

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = self.make_window(NAMESPACE, catcher=False)
        self.catcher = self.make_window(NAMESPACE + "-catcher", catcher=True)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, name="panel")
        self.panel.set_size_request(WIDTH, -1)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.stack.set_vhomogeneous(False)
        self.stack.set_hhomogeneous(True)
        self.stack.add_named(self.build_main(), "main")
        self.stack.add_named(self.build_apps(), "apps")
        self.panel.pack_start(self.stack, True, True, 0)
        self.win.add(self.panel)
        self.win.connect("key-press-event", self.on_key)
        self.panel.show_all()
        self.panel.set_opacity(0.0)

        threading.Thread(target=self.watch, daemon=True).start()

    # ---------- 画面 ----------
    def build_main(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        head = Gtk.Box(spacing=8)
        head.pack_start(Gtk.Label(label="音量", name="title"), False, False, 0)
        self.dev_label = Gtk.Label(xalign=0)
        self.dev_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.dev_label.get_style_context().add_class("sub")
        head.pack_start(self.dev_label, True, True, 0)
        page.pack_start(head, False, False, 0)

        self.master = VolumeControl(
            lambda v: pactl("set-sink-volume", self.default, f"{v}%"),
            lambda m: run_bg(lambda: pactl("set-sink-mute", self.default, "1" if m else "0")))
        page.pack_start(self.master, False, False, 0)

        sec = Gtk.Label(label="输出设备", xalign=0)
        sec.get_style_context().add_class("section")
        page.pack_start(sec, False, False, 0)
        self.devices = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.devices.connect("row-activated", self.on_device)
        page.pack_start(self.devices, False, False, 0)

        page.pack_start(Gtk.Separator(), False, False, 0)
        self.apps_btn = Gtk.Button(label="各个程序单独音量  ›")
        self.apps_btn.get_style_context().add_class("nav")
        self.apps_btn.connect("clicked", lambda *_: self.switch_page("apps"))
        page.pack_start(self.apps_btn, False, False, 0)
        return page

    def build_apps(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        head = Gtk.Box(spacing=8)
        back = Gtk.Button(label="‹ 返回")
        back.get_style_context().add_class("nav")
        back.connect("clicked", lambda *_: self.switch_page("main"))
        head.pack_start(back, False, False, 0)
        head.pack_start(Gtk.Label(label="各个程序的音量", name="title"), False, False, 0)
        page.pack_start(head, False, False, 0)
        self.apps = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.apps_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.apps_scroll.set_propagate_natural_height(True)
        self.apps_scroll.set_max_content_height(360)
        self.apps_scroll.add(self.apps)
        page.pack_start(self.apps_scroll, True, True, 0)
        self.apps_empty = Gtk.Label(label="现在没有正在播放声音的程序", name="empty")
        page.pack_start(self.apps_empty, False, False, 0)
        return page

    def switch_page(self, name):
        self.stack.set_visible_child_name(name)
        if name == "main":
            self.apps_btn.grab_focus()
        self.fit_size()

    def fit_size(self):
        def do():
            if self.stack.get_visible_child_name() == "apps":
                rows = self.apps.get_children()
                h = sum(r.get_preferred_height()[1] for r in rows)
                self.apps_scroll.set_min_content_height(min(h, 360))
            self.win.resize(WIDTH, 1)  # 按内容重新计算大小（GTK3 的窗口不会自动跟着内容变大 / 变小）
            return False
        GLib.idle_add(do)

    # ---------- 数据 ----------
    def watch(self):
        """后台线程：pactl subscribe，有变化时刷新（音量键等从别处改了音量时也会马上反映）"""
        while True:
            try:
                p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
                for line in p.stdout:
                    if any(k in line for k in ("sink", "server", "card")):
                        GLib.idle_add(self.schedule_refresh)
            except OSError:
                pass
            time.sleep(2)  # pactl 退出了（比如 PipeWire 重启）→ 稍后重新监听

    def schedule_refresh(self):
        # 短时间内的多次变化合并成一次刷新；隐藏中不刷新（显示时会刷新）
        if self.visible and not self.refresh_pending:
            self.refresh_pending = True
            GLib.timeout_add(60, self.refresh)
        return False

    def refresh(self):
        self.refresh_pending = False
        run_bg(load_state, self.fill)
        return False

    def fill(self, res):
        if isinstance(res, Exception):
            self.dev_label.set_text(str(res))
            return
        self.default, sinks, apps = res
        cur = next((s for s in sinks if s["name"] == self.default), sinks[0] if sinks else None)
        if cur:
            self.default = cur["name"]
            self.dev_label.set_text(cur["desc"])
            self.master.update(cur["volume"], cur["mute"])

        # 输出设备列表（设备的组合没变时不重建）
        keys = [(s["name"], s["desc"], s["name"] == self.default) for s in sinks]
        if keys != getattr(self, "dev_keys", None):
            self.dev_keys = keys
            for r in self.devices.get_children():
                self.devices.remove(r)
            for name, desc, is_cur in keys:
                row = Gtk.ListBoxRow()
                row.sink_name = name
                box = Gtk.Box(spacing=8)
                mark = Gtk.Label(label=CHECK if is_cur else " ")
                mark.set_size_request(20, -1)
                lbl = Gtk.Label(label=desc, xalign=0)
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                box.pack_start(mark, False, False, 0)
                box.pack_start(lbl, True, True, 0)
                row.add(box)
                if is_cur:
                    row.get_style_context().add_class("current")
                self.devices.add(row)
            self.devices.show_all()
            self.fit_size()

        # 各程序（程序的组合没变时只更新数值，不重建）
        app_keys = [(a["index"], a["name"], a["media"]) for a in apps]
        if app_keys != getattr(self, "app_keys", None):
            self.app_keys = app_keys
            for r in self.apps.get_children():
                self.apps.remove(r)
            for a in apps:
                self.apps.add(AppRow(a))
            self.apps_empty.set_visible(not apps)
            self.apps_scroll.set_visible(bool(apps))
            self.fit_size()
        else:
            for r, a in zip(self.apps.get_children(), apps):
                r.control.update(a["volume"], a["mute"])
        self.apps_btn.set_label(f"各个程序单独音量（{len(apps)}）  ›" if apps else "各个程序单独音量  ›")

    def on_device(self, lb, row):
        name = row.sink_name

        def work():
            pactl("set-default-sink", name)
            # 正在播放的程序也一起移到新设备上（和 Windows 切换默认设备时一样）
            for a in pactl_json("sink-inputs"):
                pactl("move-sink-input", str(a["index"]), name)
        run_bg(work, lambda _: self.refresh())

    # ---------- 窗口（和 wifi-popup.py 相同的做法） ----------
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

    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()
        return False

    def place(self):
        """查一下“现在”模块在哪里，弹窗的右边对准模块的右边，显示在点击的那块屏幕上
        （约 20～25ms；查不到时保持上一次的位置，第一次是 MARGIN_RIGHT）"""
        pos = popup_anchor.locate()
        if pos is None:
            return
        monitor, margin = pos
        if monitor is not None:
            for w in (self.win, self.catcher):
                GtkLayerShell.set_monitor(w, monitor)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.RIGHT, margin)

    def show(self):
        if self.visible:
            return
        self.visible = True
        self.place()
        self.stack.set_visible_child_name("main")
        self.refresh()
        self.catcher.show()
        self.win.show()
        self.master.scale.grab_focus()  # ← → / ↑ ↓ 可以直接调主音量
        self.fit_size()
        self.fade_to(1.0)

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
            if self.stack.get_visible_child_name() == "apps":
                self.switch_page("main")
            else:
                self.hide()
            return True
        return False


def main():
    show_now = "--show" in sys.argv
    try:
        pid = int(open(PIDFILE).read())
        if pid != os.getpid() and "volume-popup.py" in open(f"/proc/{pid}/cmdline").read():
            os.kill(pid, signal.SIGUSR1)
            return
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    popup = VolumePopup()
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
