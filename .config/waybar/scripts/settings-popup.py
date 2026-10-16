#!/usr/bin/env python3
# 设置弹窗：点击 waybar 的设置模块（齿轮）时，从模块上方淡入显示
#
# 做法和其他弹窗（brightness-popup.py 等）相同：
# · 常驻后台（平时隐藏），收到 SIGUSR1 时 显示 ⇄ 隐藏（由 settings-popup-toggle.sh 发送）
# · gtk-layer-shell 的图层，图层名 “settings-menu”；淡入淡出 FADE_MS（0.2 秒）由程序自己做，
#   mango 那边对这个图层设置 no_animation:1
# · 点击外面自动关闭（后面铺一层完全透明的全屏图层 “settings-menu-catcher”）
# · 打开时查一下模块现在的位置，弹窗的右边对准模块的右边（popup_anchor.py）
#
# 画面：
# · 显示器：每块连接着的屏幕的缩放比例；外接屏放在内置屏的哪一边
#   以后要加别的设置时，在 build() 里加新的分区
#
# 显示器的设置写在 ~/.config/mango/local.conf（config.conf 用 source_optional 读入，不放进 dotfiles 仓库）。
# mango 发现文件变了会自动重新加载，所以点了按钮马上生效。
# · 每块屏幕写一条 monitor_rule（缩放 + 位置）。位置按“缩放后的大小”算好，屏幕之间不会空出一段
# · 程序在后台用 mmsg watch all-monitors 看着屏幕的连接：插上 / 拔掉显示器时，按记住的设置重新排列
# · local.conf 里 MARK_BEGIN ～ MARK_END 之间由这个程序写入；其余的内容（手动加的设置）保留不动
#   （monitor_rule 只能由这个程序写：同一块屏幕有多条规则时，启动时和重新加载时用到的不是同一条）

import json
import os
import re
import signal
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLibUnix", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, GLibUnix, Gtk, GtkLayerShell  # noqa: E402

# 弹窗位置的计算（和其他弹窗共用，popup_anchor.py）
sys.dont_write_bytecode = True  # 不在 scripts 目录里生成 __pycache__
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import popup_anchor  # noqa: E402

# ---------- 设置 ----------
FADE_MS = 200           # 淡入 / 淡出的时间（毫秒）
WIDTH = 440             # 弹窗宽度
MARGIN_RIGHT = 6        # 离屏幕右边的距离（只在查不到模块位置时使用，见 place）
MARGIN_BOTTOM = 8       # 离 waybar 的距离
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)
POSITIONS = (("right", "右边"), ("left", "左边"), ("above", "上边"))
INTERNAL = re.compile(r"^eDP")   # 笔记本内置屏的接口名
NAMESPACE = "settings-menu"

LOCAL_CONF = os.path.expanduser("~/.config/mango/local.conf")
MARK_BEGIN = "# >>> 显示器（由 waybar 的设置弹窗 settings-popup.py 写入，请在弹窗里修改）"
MARK_END = "# <<< 显示器"

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
PIDFILE = os.path.join(RUNTIME, f"settings-popup-{os.environ.get('WAYLAND_DISPLAY', 'wayland-0')}.pid")

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
.section { color: #f5a0c8; font-weight: bold; }
.sub { color: #8e8c9e; font-size: 10pt; }
.name { font-weight: bold; }
.key { color: #8e8c9e; font-size: 11pt; min-width: 40px; }
.card { background-color: rgba(58, 52, 112, 0.45); border-radius: 8px; padding: 8px 10px; }
/* transition: none —— 关掉系统主题（Adwaita）给按钮加的过渡动画（和其他弹窗一样） */
button {
    background-color: #3a3470; background-image: none; color: #c9b9f2;
    border: none; border-radius: 8px; box-shadow: none; text-shadow: none;
    padding: 3px 6px; min-height: 0; transition: none;
}
button label { color: #c9b9f2; font-size: 11pt; }
button:hover { background-color: #6c5cc4; }
button.current { background-color: #f5a0c8; }
button.current label { color: #1f1a3d; font-weight: bold; }
"""


# ---------- 屏幕的信息（mango） ----------
def mmsg_monitors():
    """连接着的屏幕：[{name, width, height（缩放后）, scale, x, y}]；取不到时返回 None"""
    try:
        r = subprocess.run(["mmsg", "get", "all-monitors"], capture_output=True, text=True, timeout=1)
        return json.loads(r.stdout)["monitors"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


def physical_size(m):
    """缩放前的分辨率（mmsg 给的是缩放后的大小）"""
    s = m.get("scale", 1) or 1
    return round(m["width"] * s), round(m["height"] * s)


def logical(px, scale):
    """缩放后的大小：和 wlroots 一样舍去小数"""
    return int(px / scale)


def is_internal(name):
    return bool(INTERNAL.match(name))


def fmt_scale(s):
    return f"{round(s * 100)}%"


# ---------- local.conf 的读写 ----------
RULE_RE = re.compile(r"^monitor_rule=name:\^(.+?)\$,(.*)$")
POS_RE = re.compile(r"^# 位置：(\S+)=(\S+)$")


def read_local():
    """local.conf → ({屏幕名: 缩放}, {屏幕名: 位置}, 其余的行)"""
    try:
        lines = open(LOCAL_CONF).read().splitlines()
    except OSError:
        lines = []
    scales, positions, rest = {}, {}, []
    inside = False
    for line in lines:
        if line == MARK_BEGIN:
            inside = True
            continue
        if line == MARK_END:
            inside = False
            continue
        m = RULE_RE.match(line)
        if m:  # 区块外面手写的 monitor_rule 也读进来（下次写入时并到区块里）
            opts = dict(kv.split(":", 1) for kv in m.group(2).split(",") if ":" in kv)
            try:
                scales[m.group(1)] = float(opts.get("scale", 1))
            except ValueError:
                pass
            continue
        p = POS_RE.match(line)
        if inside and p:
            positions[p.group(1)] = p.group(2)
            continue
        if not inside:
            rest.append(line)
    while rest and rest[-1] == "":
        rest.pop()
    return scales, positions, rest


def layout(monitors, scales, positions):
    """连接着的屏幕的位置 {屏幕名: (x, y)}
    内置屏（没有的话是第一块）放在 (0,0)，其他屏幕按记住的位置（右边 / 左边 / 上边）紧挨着排，
    最后整体平移，让左上角是 (0,0)。上下边对齐的方式：左右排列时上边对齐，放在上边时左右居中。"""
    if not monitors:
        return {}
    ordered = sorted(monitors, key=lambda m: (not is_internal(m["name"]), m["name"]))
    size = {}
    for m in ordered:
        pw, ph = physical_size(m)
        s = scales.get(m["name"], 1.0)
        size[m["name"]] = (logical(pw, s), logical(ph, s))
    first = ordered[0]["name"]
    pos = {first: (0, 0)}
    fw, fh = size[first]
    left, right, top = 0, fw, 0
    for m in ordered[1:]:
        n = m["name"]
        w, h = size[n]
        where = positions.get(n, "right")
        if where == "left":
            pos[n] = (left - w, 0)
            left -= w
        elif where == "above":
            pos[n] = ((fw - w) // 2, top - h)
            top -= h
        else:
            pos[n] = (right, 0)
            right += w
    minx = min(x for x, _ in pos.values())
    miny = min(y for _, y in pos.values())
    return {n: (x - minx, y - miny) for n, (x, y) in pos.items()}


def render_local(monitors, scales, positions, rest):
    """local.conf 的内容。连接着的屏幕写缩放 + 位置；现在没连接、但设置过的屏幕只写缩放
    （下次插上时先由 mango 自动排列，再由这个程序按记住的位置重新排）"""
    pos = layout(monitors, scales, positions)
    connected = {m["name"] for m in monitors}
    out = list(rest)
    if out:
        out.append("")
    out.append(MARK_BEGIN)
    for n in sorted(set(scales) | connected, key=lambda n: (not is_internal(n), n)):
        s = scales.get(n, 1.0)
        line = f"monitor_rule=name:^{n}$,scale:{s:g}"
        if n in pos:
            line += f",x:{pos[n][0]},y:{pos[n][1]}"
        out.append(line)
    for n in sorted(positions):
        out.append(f"# 位置：{n}={positions[n]}")
    out.append(MARK_END)
    return "\n".join(out) + "\n"


def write_local(text):
    """内容没变时不写（写了 mango 就会重新加载一次）"""
    try:
        if open(LOCAL_CONF).read() == text:
            return False
    except OSError:
        pass
    tmp = LOCAL_CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, LOCAL_CONF)
    return True


class SettingsPopup:
    def __init__(self):
        self.visible = False
        self.fade_target = 0.0
        self.monitors = mmsg_monitors() or []
        self.names = None          # 上一次看到的“连接着的屏幕”
        self.watch_proc = None

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = self.make_window(NAMESPACE, catcher=False)
        self.catcher = self.make_window(NAMESPACE + "-catcher", catcher=True)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, name="panel")
        self.panel.set_size_request(WIDTH, -1)
        self.win.add(self.panel)
        self.win.connect("key-press-event", self.on_key)
        self.build()
        self.panel.set_opacity(0.0)
        self.start_watch()

    # ---------- 画面 ----------
    def build(self):
        for child in self.panel.get_children():
            self.panel.remove(child)
        head = Gtk.Box(spacing=8)
        head.pack_start(Gtk.Label(label="设置", name="title"), False, False, 0)
        self.panel.pack_start(head, False, False, 0)
        self.build_monitors()
        self.panel.show_all()

    def build_monitors(self):
        sec = Gtk.Label(label="显示器", xalign=0)
        sec.get_style_context().add_class("section")
        self.panel.pack_start(sec, False, False, 0)
        if not self.monitors:
            msg = Gtk.Label(label="取不到屏幕的信息（mmsg 不能用）", xalign=0)
            msg.get_style_context().add_class("sub")
            self.panel.pack_start(msg, False, False, 0)
            return
        scales, positions, _ = read_local()
        ordered = sorted(self.monitors, key=lambda m: (not is_internal(m["name"]), m["name"]))
        first = ordered[0]["name"]
        for m in ordered:
            n = m["name"]
            pw, ph = physical_size(m)
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.get_style_context().add_class("card")

            title = Gtk.Box(spacing=8)
            name = Gtk.Label(label=n, xalign=0)
            name.get_style_context().add_class("name")
            info = Gtk.Label(label=("内置 · " if is_internal(n) else "") + f"{pw}×{ph}", xalign=0)
            info.get_style_context().add_class("sub")
            title.pack_start(name, False, False, 0)
            title.pack_start(info, False, False, 0)
            card.pack_start(title, False, False, 0)

            cur = scales.get(n, m.get("scale", 1.0))
            card.pack_start(self.button_row("缩放", [(s, fmt_scale(s)) for s in SCALES], cur,
                                            lambda v, n=n: self.set_scale(n, v)), False, False, 0)
            if n != first and len(ordered) > 1:
                where = positions.get(n, "right")
                label = f"在 {first} 的"
                card.pack_start(self.button_row(label, POSITIONS, where,
                                                lambda v, n=n: self.set_position(n, v)), False, False, 0)
            self.panel.pack_start(card, False, False, 0)

    def button_row(self, key, items, current, on_click):
        row = Gtk.Box(spacing=6)
        k = Gtk.Label(label=key, xalign=0)
        k.get_style_context().add_class("key")
        row.pack_start(k, False, False, 0)
        btns = Gtk.Box(spacing=6, homogeneous=True)
        for value, text in items:
            b = Gtk.Button(label=text)
            same = abs(value - current) < 1e-6 if isinstance(value, float) else value == current
            if same:
                b.get_style_context().add_class("current")
            b.connect("clicked", lambda _b, v=value: on_click(v))
            btns.pack_start(b, True, True, 0)
        row.pack_start(btns, True, True, 0)
        return row

    # ---------- 修改 ----------
    def set_scale(self, name, value):
        scales, positions, rest = read_local()
        for m in self.monitors:  # 还没写进 local.conf 的屏幕：先记下现在的缩放
            scales.setdefault(m["name"], m.get("scale", 1.0))
        scales[name] = value
        self.apply(scales, positions, rest)

    def set_position(self, name, value):
        scales, positions, rest = read_local()
        for m in self.monitors:
            scales.setdefault(m["name"], m.get("scale", 1.0))
        positions[name] = value
        self.apply(scales, positions, rest)

    def apply(self, scales, positions, rest):
        self.monitors = mmsg_monitors() or self.monitors
        write_local(render_local(self.monitors, scales, positions, rest))
        self.build()
        # mango 重新加载后屏幕的大小会变：稍后再读一次，更新画面上的数值
        GLib.timeout_add(600, self.refresh)

    def refresh(self):
        mons = mmsg_monitors()
        if mons is not None:
            self.monitors = mons
            if self.visible:
                self.build()
        return False

    # ---------- 插上 / 拔掉显示器 ----------
    def start_watch(self):
        """mmsg watch all-monitors：屏幕有变化时输出一行 JSON（mango 重启后自动重连）"""
        try:
            self.watch_proc = subprocess.Popen(["mmsg", "watch", "all-monitors"], stdout=subprocess.PIPE,
                                               stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            GLib.timeout_add_seconds(5, lambda: (self.start_watch(), False)[1])
            return
        ch = GLib.IOChannel.unix_new(self.watch_proc.stdout.fileno())
        GLib.io_add_watch(ch, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP,
                          self.on_watch)

    def on_watch(self, ch, cond):
        line = self.watch_proc.stdout.readline() if cond & GLib.IOCondition.IN else ""
        if not line:
            self.watch_proc.wait()
            GLib.timeout_add_seconds(3, lambda: (self.start_watch(), False)[1])
            return False
        try:
            mons = json.loads(line)["monitors"]
        except (ValueError, KeyError):
            return True
        names = sorted(m["name"] for m in mons)
        if names != self.names:
            self.names = names
            self.monitors = mons
            self.rearrange()
            if self.visible:
                self.build()
        return True

    def rearrange(self):
        """按记住的设置重新排列连接着的屏幕（local.conf 里还没有这个程序写的区块时什么都不做）"""
        try:
            if MARK_BEGIN not in open(LOCAL_CONF).read():
                return
        except OSError:
            return
        scales, positions, rest = read_local()
        write_local(render_local(self.monitors, scales, positions, rest))

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
        self.monitors = mmsg_monitors() or self.monitors
        self.build()
        self.place()
        self.catcher.show()
        self.win.show()
        self.win.resize(WIDTH, 1)
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
            self.hide()
            return True
        return False


def main():
    show_now = "--show" in sys.argv
    try:
        pid = int(open(PIDFILE).read())
        if pid != os.getpid() and "settings-popup.py" in open(f"/proc/{pid}/cmdline").read():
            os.kill(pid, signal.SIGUSR1)
            return
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    popup = SettingsPopup()
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
        if popup.watch_proc and popup.watch_proc.poll() is None:
            popup.watch_proc.terminate()
        try:
            if open(PIDFILE).read().strip() == str(os.getpid()):
                os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
