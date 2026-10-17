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
# 画面：两层
# · 第一层：设置的分类，每个分类一行（右边是现在设定的摘要）；点一下进入这个分类的第二层
# · 第二层：这个分类的设置。标题栏左边的 ‹ 或 Esc 回到第一层
# 分类：
# · 显示器：每块连接着的屏幕的缩放比例；外接屏放在内置屏的哪一边、怎么对齐
# · 电源模式：性能 / 平衡 / 节能（power-profiles-daemon，通过 DBus 切换，不需要 root）
#   以后要加别的分类时，写“建第二层画面”和“摘要”两个函数，加到 SettingsPopup.categories 里
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
from gi.repository import Gdk, Gio, GLib, GLibUnix, Gtk, GtkLayerShell, Pango  # noqa: E402

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
POSITIONS = (("right", "右边"), ("left", "左边"), ("above", "上边"), ("below", "下边"))
# 对齐方式：外接屏在左右时是上下方向的对齐，在上下时是左右方向的对齐（默认居中）
ALIGNS = {
    "side": (("start", "上对齐"), ("center", "居中"), ("end", "下对齐")),   # 在右边 / 左边
    "stack": (("start", "左对齐"), ("center", "居中"), ("end", "右对齐")),  # 在上边 / 下边
}
# 两层之间切换的动画时间（毫秒）
SLIDE_MS = 150          # 滑动：内容向左 / 向右滑、返回按钮“‹”展开 / 收起
RESIZE_MS = 250         # 伸展：弹窗的高度、粉色标题后面的“ › 分类名”
INTERNAL = re.compile(r"^eDP")   # 笔记本内置屏的接口名
# power-profiles-daemon 的 DBus 名字、路径、接口
PPD = ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
       "org.freedesktop.UPower.PowerProfiles")
# 电源模式：(power-profiles-daemon 里的名字, 按钮上的文字, 说明)
PROFILES = (
    ("performance", "性能", "性能优先，风扇和耗电会增加"),
    ("balanced", "平衡", "一般使用"),
    ("power-saver", "节能", "降低性能，延长电池时间"),
)
# 性能模式暂时受限的原因（power-profiles-daemon 的 PerformanceDegraded）
DEGRADED = {
    "lap-detected": "检测到电脑放在腿上",
    "high-operating-temperature": "温度太高",
}
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
    background-color: #f5a0c8;
    border-radius: 8px; padding: 4px 12px;
}
#title label { color: #1f1a3d; font-weight: bold; }
.section { color: #f5a0c8; font-weight: bold; }
.sub { color: #8e8c9e; font-size: 10pt; }
.name { font-weight: bold; }
.key { color: #8e8c9e; font-size: 11pt; min-width: 40px; }
/* 包着两层内容的 ScrolledWindow（只用来在动画时裁切高度）：不要背景、边框和滚动边缘的阴影 */
scrolledwindow, viewport { background-color: transparent; border: none; }
scrolledwindow undershoot, scrolledwindow overshoot { background: none; }
.card { background-color: rgba(58, 52, 112, 0.45); border-radius: 8px; padding: 8px 10px; }
#back { padding: 2px 10px; }
#back label { font-size: 13pt; }
button.item { background-color: rgba(58, 52, 112, 0.45); padding: 8px 10px; }
button.item:hover { background-color: #3a3470; }
.item-icon { color: #f5a0c8; font-size: 15pt; min-width: 28px; }
.item-name { font-size: 13pt; font-weight: bold; }
.arrow { color: #8e8c9e; }
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
    """local.conf → ({屏幕名: 缩放}, {屏幕名: (位置, 对齐)}, 其余的行)"""
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
            where, _, align = p.group(2).partition(",")
            positions[p.group(1)] = (where, align or "center")
            continue
        if not inside:
            rest.append(line)
    while rest and rest[-1] == "":
        rest.pop()
    return scales, positions, rest


def layout(monitors, scales, positions):
    """连接着的屏幕的位置 {屏幕名: (x, y)}
    内置屏（没有的话是第一块）放在 (0,0)，其他屏幕按记住的位置（右边 / 左边 / 上边 / 下边）紧挨着排，
    最后整体平移，让左上角是 (0,0)。
    对齐（和内置屏比）：左右排列时 上对齐 / 居中 / 下对齐，上下排列时 左对齐 / 居中 / 右对齐。"""
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
    left, right, top, bottom = 0, fw, 0, fh
    for m in ordered[1:]:
        n = m["name"]
        w, h = size[n]
        where, align = positions.get(n, ("right", "center"))
        # 和内置屏对齐：start = 上 / 左，center = 居中，end = 下 / 右
        ay = {"start": 0, "end": fh - h}.get(align, (fh - h) // 2)
        ax = {"start": 0, "end": fw - w}.get(align, (fw - w) // 2)
        if where == "left":
            pos[n] = (left - w, ay)
            left -= w
        elif where == "above":
            pos[n] = (ax, top - h)
            top -= h
        elif where == "below":
            pos[n] = (ax, bottom)
            bottom += h
        else:
            pos[n] = (right, ay)
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
        out.append(f"# 位置：{n}={positions[n][0]},{positions[n][1]}")
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

        # 分类：(名字, 图标, 标题, 建第二层画面的函数, 摘要的函数)
        self.categories = [
            ("monitors", "󰍹", "显示器", self.build_monitors, self.monitors_summary),
            ("power", "󰓅", "电源模式", self.build_power, self.power_summary),
        ]
        self.ppd = self.connect_ppd()
        self.page = "home"

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, name="panel")
        self.panel.set_size_request(WIDTH, -1)
        self.panel.pack_start(self.make_head(), False, False, 0)
        self.stack = Gtk.Stack()
        self.stack.set_vhomogeneous(False)        # 高度跟着现在这一层变
        self.stack.set_transition_duration(SLIDE_MS)
        self.pages = {}
        for key in ["home"] + [c[0] for c in self.categories]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            self.pages[key] = box
            self.stack.add_named(box, key)
        # 高度的动画（RESIZE_MS）比滑动（SLIDE_MS）长，所以不用 Stack 自带的高度插值，
        # 而是把 Stack 放进一个 ScrolledWindow：平时高度跟着内容（NEVER），
        # 动画期间改成 EXTERNAL（不显示滚动条、超出的部分被裁掉），由 follow_size 每一帧设置它的高度
        self.clip = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       vscrollbar_policy=Gtk.PolicyType.NEVER)
        self.clip.add(self.stack)
        self.panel.pack_start(self.clip, False, False, 0)
        self.resize_anim = None    # 高度的动画：(开始的高度, 目标高度, 开始的时间)
        self.win.add(self.panel)
        self.win.connect("key-press-event", self.on_key)
        self.build()
        self.panel.set_opacity(0.0)
        self.start_watch()

    # ---------- 画面 ----------
    def build(self):
        """重建标题栏和所有的层（数值变了时调用；现在显示的是哪一层不变）"""
        self.build_head()
        for key, box in self.pages.items():
            for child in box.get_children():
                box.remove(child)
        self.build_home(self.pages["home"])
        for key, _icon, _title, build, _summary in self.categories:
            build(self.pages[key])
        self.panel.show_all()
        self.stack.set_visible_child_name(self.page)

    def make_head(self):
        """标题栏：‹（返回）+ 粉色的“设置 › 分类名”
        返回按钮和“ › 分类名”各放在一个 Gtk.Revealer 里：进入分类时向右展开，回到第一层时收起"""
        head = Gtk.Box()
        back = Gtk.Button(label="‹", name="back", margin_end=8)
        back.connect("clicked", lambda _b: self.go("home"))
        self.back_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT,
                                     transition_duration=SLIDE_MS)
        self.back_rev.add(back)
        pill = Gtk.Box(name="title")
        self.crumb = Gtk.Label()
        # SLIDE_LEFT：从文字的左边开始露出（“ › 显”→“ › 显示器”），看起来像粉色背景往右伸长
        self.crumb_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT,
                                      transition_duration=RESIZE_MS)
        self.crumb_rev.add(self.crumb)
        pill.pack_start(Gtk.Label(label="设置"), False, False, 0)
        pill.pack_start(self.crumb_rev, False, False, 0)
        head.pack_start(self.back_rev, False, False, 0)
        head.pack_start(pill, False, False, 0)
        return head

    def build_head(self, animate=False):
        """按现在的层设置标题栏；animate=False 时直接变成最终的样子（打开弹窗时）"""
        inner = self.page != "home"
        if inner:
            # 回到第一层时不改文字，让收起的过程中还显示着原来的分类名
            title = next(c[2] for c in self.categories if c[0] == self.page)
            self.crumb.set_text(f" › {title}")
        for rev, ms in ((self.back_rev, SLIDE_MS), (self.crumb_rev, RESIZE_MS)):
            rev.set_transition_duration(ms if animate else 0)
            rev.set_reveal_child(inner)

    def build_home(self, box):
        for key, icon, title, _build, summary in self.categories:
            b = Gtk.Button()
            b.get_style_context().add_class("item")
            row = Gtk.Box(spacing=8)
            i = Gtk.Label(label=icon)
            i.get_style_context().add_class("item-icon")
            t = Gtk.Label(label=title, xalign=0)
            t.get_style_context().add_class("item-name")
            sub = Gtk.Label(label=summary(), xalign=1)
            sub.get_style_context().add_class("sub")
            sub.set_ellipsize(Pango.EllipsizeMode.END)  # 太长时省略
            arrow = Gtk.Label(label="›")
            arrow.get_style_context().add_class("arrow")
            row.pack_start(i, False, False, 0)
            row.pack_start(t, False, False, 0)
            row.pack_start(sub, True, True, 0)
            row.pack_start(arrow, False, False, 0)
            b.add(row)
            b.connect("clicked", lambda _b, k=key: self.go(k))
            box.pack_start(b, False, False, 0)

    def go(self, page):
        """切换到某一层：进入分类时向左滑，回到第一层时向右滑"""
        forward = page != "home"
        self.page = page
        self.build_head(animate=True)
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT if forward
                                       else Gtk.StackTransitionType.SLIDE_RIGHT)
        start = self.stack.get_allocated_height()
        self.stack.set_visible_child_name(page)
        target = self.pages[page].get_preferred_height()[1]
        self.clip.set_min_content_height(start)
        self.clip.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)
        self.resize_anim = (start, target, time.monotonic())
        self.stack.add_tick_callback(self.follow_size)

    def follow_size(self, _widget, _clock):
        """切换期间的每一帧：把高度从旧的一层推进到新的一层（开始快、结束慢），
        并按现在的高度重设窗口大小（layer-shell 的窗口不会自己变小）"""
        if not self.resize_anim:
            return False
        start, target, t0 = self.resize_anim
        p = min(1.0, (time.monotonic() - t0) * 1000 / RESIZE_MS)
        ease = 1 - (1 - p) ** 3
        self.clip.set_min_content_height(round(start + (target - start) * ease))
        if p >= 1.0:
            self.end_resize()
        self.win.resize(WIDTH, 1)
        return self.resize_anim is not None

    def end_resize(self):
        """高度的动画结束：改回跟着内容的高度（数值变了、行数变了时也能自动适应）"""
        self.resize_anim = None
        self.clip.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.clip.set_min_content_height(-1)

    def monitors_summary(self):
        if not self.monitors:
            return ""
        ordered = sorted(self.monitors, key=lambda m: (not is_internal(m["name"]), m["name"]))
        return " · ".join(f"{m['name']} {fmt_scale(m.get('scale', 1.0))}" for m in ordered)

    # ---------- 分类：显示器 ----------
    def build_monitors(self, box):
        if not self.monitors:
            msg = Gtk.Label(label="取不到屏幕的信息（mmsg 不能用）", xalign=0)
            msg.get_style_context().add_class("sub")
            box.pack_start(msg, False, False, 0)
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
                where, align = positions.get(n, ("right", "center"))
                label = f"在 {first} 的"
                card.pack_start(self.button_row(label, POSITIONS, where,
                                                lambda v, n=n: self.set_position(n, v)), False, False, 0)
                aligns = ALIGNS["side" if where in ("right", "left") else "stack"]
                card.pack_start(self.button_row("对齐", aligns, align,
                                                lambda v, n=n: self.set_align(n, v)), False, False, 0)
            box.pack_start(card, False, False, 0)

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

    # ---------- 分类：电源模式 ----------
    def connect_ppd(self):
        """连接 power-profiles-daemon；模式在别处被改了时（PropertiesChanged）重建画面"""
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE,
                                                   None, *PPD, None)
        except GLib.Error:
            return None
        proxy.connect("g-properties-changed", lambda *_: self.visible and self.build())
        return proxy

    def ppd_get(self, prop):
        """power-profiles-daemon 的属性；daemon 没在运行时返回 None"""
        v = self.ppd.get_cached_property(prop) if self.ppd else None
        return v.unpack() if v is not None else None

    def power_summary(self):
        active = self.ppd_get("ActiveProfile")
        return next((text for key, text, _ in PROFILES if key == active), active or "不能用")

    def build_power(self, box):
        active = self.ppd_get("ActiveProfile")
        if active is None:
            msg = Gtk.Label(label="取不到电源模式（power-profiles-daemon 没有运行）", xalign=0)
            msg.get_style_context().add_class("sub")
            box.pack_start(msg, False, False, 0)
            return
        available = {p.get("Profile") for p in self.ppd_get("Profiles") or []}
        items = [(key, text) for key, text, _ in PROFILES if key in available]
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("card")
        card.pack_start(self.button_row("模式", items, active, self.set_profile), False, False, 0)
        note = next((desc for key, _, desc in PROFILES if key == active), "")
        degraded = self.ppd_get("PerformanceDegraded")
        if degraded:
            note += f"\n性能模式暂时受限：{DEGRADED.get(degraded, degraded)}"
        info = Gtk.Label(label=note, xalign=0)
        info.set_line_wrap(True)
        info.get_style_context().add_class("sub")
        card.pack_start(info, False, False, 0)
        box.pack_start(card, False, False, 0)

    def set_profile(self, profile):
        """切换电源模式（DBus 的 Properties.Set）；切换后 daemon 发出 PropertiesChanged，画面随之更新"""
        if not self.ppd:
            return
        self.ppd.call("org.freedesktop.DBus.Properties.Set",
                      GLib.Variant("(ssv)", (PPD[2], "ActiveProfile", GLib.Variant("s", profile))),
                      Gio.DBusCallFlags.NONE, -1, None, self.on_profile_set)

    def on_profile_set(self, proxy, res):
        try:
            proxy.call_finish(res)
        except GLib.Error as e:
            print(f"settings-popup: 切换电源模式失败：{e.message}", file=sys.stderr)

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
        positions[name] = (value, positions.get(name, ("right", "center"))[1])
        self.apply(scales, positions, rest)

    def set_align(self, name, value):
        scales, positions, rest = read_local()
        for m in self.monitors:
            scales.setdefault(m["name"], m.get("scale", 1.0))
        positions[name] = (positions.get(name, ("right", "center"))[0], value)
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
        self.page = "home"     # 每次打开都从第一层开始
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.end_resize()
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
            if self.page != "home":
                self.go("home")
            else:
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
