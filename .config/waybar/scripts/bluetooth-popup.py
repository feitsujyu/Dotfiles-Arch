#!/usr/bin/env python3
# 蓝牙弹窗（turn 41）：点击 waybar 的蓝牙模块时，从模块上方淡入显示
#
# 做法和 Wi-Fi 弹窗（wifi-popup.py，turn 30）、音量弹窗（volume-popup.py，turn 34）相同：
# · 常驻后台（平时隐藏），收到 SIGUSR1 时 显示 ⇄ 隐藏（由 bluetooth-popup-toggle.sh 发送）
# · gtk-layer-shell 的图层，图层名 “bluetooth-menu”；淡入淡出 FADE_MS（0.2 秒）由程序自己做，
#   mango 那边对这个图层设置 noanim:1
# · 点击外面自动关闭（后面铺一层完全透明的全屏图层 “bluetooth-menu-catcher”）
#
# 画面：
# · 标题行：蓝牙开关、重新搜索按钮
# · “我的设备”：已配对的设备。点击展开 → 连接 / 断开、取消配对
# · “附近的设备”：弹窗打开期间自动搜索到的设备（只显示有名字的）。点击 → 配对 → 信任 → 连接
# · 配对时需要确认数字 / 输入 PIN 码的话，弹窗上方会出现提示（手机等从对方发起配对时，弹窗也会自动打开）
#
# 和蓝牙服务（bluez）的通信直接用 DBus（PyGObject 的 Gio），不调用 bluetoothctl：
# 设备的变化（连接、断开、电量、搜索到新设备）会通过 DBus 的信号马上反映到画面上。
# 操作：Esc → 关闭；点外面 / 再点一次蓝牙模块 → 关闭

import os
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

# turn 46：弹窗位置的计算（和其他弹窗共用，popup_anchor.py）
sys.dont_write_bytecode = True  # 不在 scripts 目录里生成 __pycache__
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import popup_anchor  # noqa: E402

# ---------- 设置 ----------
FADE_MS = 200           # 淡入 / 淡出的时间（毫秒）
WIDTH = 400             # 弹窗宽度
MARGIN_RIGHT = 325      # 离屏幕右边的距离（弹窗右边对准 waybar 的蓝牙模块的右边；turn 41：454，turn 42：321，turn 44 换字体后改）
#   turn 46 起：每次打开时查模块的实际位置（place），这个值只在查不到时使用
MARGIN_BOTTOM = 8       # 离 waybar 的距离
MAX_LIST_HEIGHT = 420   # 设备列表最多显示多高（超过时出现滚动条）
MAX_NEARBY = 15         # “附近的设备”最多显示几个（按信号强弱）
NAMESPACE = "bluetooth-menu"

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
PIDFILE = os.path.join(RUNTIME, f"bluetooth-popup-{os.environ.get('WAYLAND_DISPLAY', 'wayland-0')}.pid")

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
AGENT_PATH = "/org/waybar/bluetooth_popup/agent"

ICON_ON = "󰂯"
ICON_OFF = "󰂲"
ICON_CONNECTED = "󰂱"
ICON_BATTERY = "󰥉"
RESCAN = "󰑐"
# bluez 的 Icon 属性 → Nerd Font 图标
DEVICE_ICONS = {
    "audio-headset": "󰋎", "audio-headphones": "󰋋", "audio-card": "󰓃",
    "input-mouse": "󰍽", "input-keyboard": "󰌌", "input-gaming": "󰊴", "input-tablet": "󰓶",
    "phone": "󰏲", "computer": "󰟀", "video-display": "󰍹", "printer": "󰐪", "camera-photo": "󰄀",
}

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
.sub, .status { color: #8e8c9e; font-size: 11pt; }
.connected { color: #8fd4a8; font-size: 11pt; }
.error { color: #f07a9a; font-size: 11pt; }
.icons { color: #a898e8; min-width: 24px; }
entry {
    background-color: #3a3470; background-image: none; color: #c9b9f2;
    border: none; border-radius: 8px; box-shadow: none; padding: 4px 10px;
    caret-color: #f5a0c8; min-height: 0;
}
scrolledwindow, viewport, list { background-color: transparent; border: none; }
/* transition: none —— 关掉系统主题（Adwaita）给按钮、行加的过渡动画（和 Wi-Fi 弹窗的 turn 31 一样） */
row { padding: 5px 10px; border-radius: 8px; background-color: transparent; outline: none; transition: none; }
row:hover { background-color: rgba(58, 52, 112, 0.85); }
row:selected, row:selected:hover { background-color: transparent; }
row.open { background-color: rgba(108, 92, 196, 0.35); }
button {
    background-color: #6c5cc4; background-image: none; color: #fbfaff;
    border: none; border-radius: 8px; box-shadow: none; text-shadow: none;
    padding: 4px 12px; min-height: 0; transition: none;
}
button label { color: #fbfaff; }
button:hover { background-color: #7d6dd6; }
button.flat { background-color: transparent; }
button.flat label { color: #c9b9f2; }
button.flat:hover { background-color: rgba(58, 52, 112, 0.85); }
button.danger { background-color: #3a3470; }
button.danger label { color: #f07a9a; }
button.danger:hover { background-color: #4a4290; }
switch {
    background-color: #3a3470; background-image: none; border: none;
    border-radius: 12px; box-shadow: none; min-height: 0; transition: none;
}
switch:checked { background-color: #6c5cc4; }
switch slider {
    background-color: #f5a0c8; background-image: none; border: none;
    border-radius: 10px; box-shadow: none; min-width: 20px; min-height: 20px;
}
switch image { color: transparent; }
#prompt {
    background-color: rgba(108, 92, 196, 0.35);
    border: 1px solid #f5a0c8; border-radius: 8px; padding: 8px;
}
#passkey { font-size: 20pt; font-weight: bold; color: #f5a0c8; letter-spacing: 4px; }
separator { background-color: rgba(108, 92, 196, 0.5); min-height: 1px; margin: 4px 0; }
.empty { color: #8e8c9e; padding: 12px; }
"""

AGENT_XML = """
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
    <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
    <method name="DisplayPasskey">
      <arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
    <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
    <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="Cancel"/>
  </interface>
</node>
"""

# bluez 的错误 → 中文说明
ERRORS = {
    "AuthenticationFailed": "配对失败（PIN 码 / 数字不一致，或者在设备上被拒绝了）",
    "AuthenticationCanceled": "配对已取消",
    "AuthenticationRejected": "配对被拒绝",
    "AuthenticationTimeout": "配对超时（设备没有响应）",
    "ConnectionAttemptFailed": "连接失败（设备不在附近，或者没有处于可连接状态）",
    "AlreadyConnected": "已经连接",
    "InProgress": "正在处理中，请稍候",
    "NotReady": "蓝牙还没有准备好",
    "Blocked": "蓝牙被 rfkill 禁用了",
    "DoesNotExist": "设备已经不在了（请重新搜索）",
}


def error_text(err):
    msg = err.message if isinstance(err, GLib.Error) else str(err)
    for key, text in ERRORS.items():
        if key in msg:
            return text
    if "Timeout" in msg or "timed out" in msg:
        return "超时（设备没有响应）"
    # “GDBus.Error:org.bluez.Error.Failed: br-connection-profile-unavailable” → 冒号后面的部分
    return msg.split(": ", 1)[-1] if msg.startswith("GDBus.Error") else msg


class Bluez:
    """bluez 的 DBus 调用（全部是异步的，不会让画面卡住）"""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def call(self, path, iface, method, args=None, reply_type=None, done=None, timeout_ms=25000):
        def finish(bus, res):
            try:
                out = bus.call_finish(res)
                err = None
            except GLib.Error as e:
                out, err = None, e
            if done:
                done(out.unpack() if out is not None else None, err)
        self.bus.call(BLUEZ, path, iface, method, args,
                      GLib.VariantType(reply_type) if reply_type else None,
                      Gio.DBusCallFlags.NONE, timeout_ms, None, finish)

    def objects(self, done):
        self.call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                  reply_type="(a{oa{sa{sv}}})", done=lambda out, err: done(out[0] if out else {}, err))

    def set_prop(self, path, iface, name, value, done=None):
        self.call(path, "org.freedesktop.DBus.Properties", "Set",
                  GLib.Variant("(ssv)", (iface, name, value)), done=done)


class DeviceRow(Gtk.ListBoxRow):
    def __init__(self, popup, path):
        super().__init__()
        self.popup, self.path = popup, path
        self.dev = {}
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        line = Gtk.Box(spacing=10)
        self.icon = Gtk.Label()
        self.icon.get_style_context().add_class("icons")
        self.name = Gtk.Label(xalign=0)
        self.name.set_ellipsize(Pango.EllipsizeMode.END)
        self.state = Gtk.Label()
        line.pack_start(self.icon, False, False, 0)
        line.pack_start(self.name, True, True, 0)
        line.pack_end(self.state, False, False, 0)
        outer.pack_start(line, False, False, 0)

        # 展开部分（已配对的设备）：连接 / 断开、取消配对；配对 / 连接中的状态信息
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.NONE)
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=4)
        self.buttons = Gtk.Box(spacing=8)
        self.conn_btn = Gtk.Button()
        self.conn_btn.connect("clicked", lambda *_: self.toggle_connection())
        self.remove_btn = Gtk.Button(label="取消配对")
        self.remove_btn.get_style_context().add_class("danger")
        self.remove_btn.connect("clicked", lambda *_: self.popup.remove_device(self.path))
        self.buttons.pack_start(self.conn_btn, True, True, 0)
        self.buttons.pack_start(self.remove_btn, False, False, 0)
        self.msg = Gtk.Label(xalign=0)
        self.msg.set_line_wrap(True)
        detail.pack_start(self.buttons, False, False, 0)
        detail.pack_start(self.msg, False, False, 0)
        self.revealer.add(detail)
        outer.pack_start(self.revealer, False, False, 0)
        self.add(outer)
        self.show_all()
        self.msg.hide()

    def update(self, dev, battery):
        self.dev = dev
        self.icon.set_text(DEVICE_ICONS.get(dev.get("Icon", ""), ICON_ON))
        self.name.set_text(dev.get("Alias") or dev.get("Name") or dev.get("Address", "?"))
        ctx = self.state.get_style_context()
        for c in ("connected", "status"):
            ctx.remove_class(c)
        busy = self.popup.busy.get(self.path)
        if busy:
            text, cls = busy, "status"
        elif dev.get("Connected"):
            text = "󰄬 已连接" + (f"  {ICON_BATTERY} {battery}%" if battery is not None else "")
            cls = "connected"
        elif dev.get("Paired"):
            text, cls = "未连接", "status"
        else:
            text, cls = "", "status"
        self.state.set_text(text)
        ctx.add_class(cls)
        self.conn_btn.set_label("󰂲 断开连接" if dev.get("Connected") else f"{ICON_CONNECTED} 连接")
        self.conn_btn.set_sensitive(not busy)
        self.remove_btn.set_sensitive(not busy)
        self.buttons.set_visible(bool(dev.get("Paired")))

    def expanded(self):
        return self.revealer.get_reveal_child()

    def set_expanded(self, on):
        self.revealer.set_reveal_child(on)
        ctx = self.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("open")
        if not on:
            self.show_message(None)
        self.popup.fit_size()

    def show_message(self, text, error=False):
        ctx = self.msg.get_style_context()
        ctx.remove_class("error")
        ctx.remove_class("status")
        ctx.add_class("error" if error else "status")
        self.msg.set_text(text or "")
        self.msg.set_visible(bool(text))
        self.popup.fit_size()

    def activate_row(self):
        if self.path in self.popup.busy:
            return
        if not self.dev.get("Paired"):  # 附近的设备：直接开始配对
            self.popup.collapse_others(self)
            self.set_expanded(True)
            self.popup.pair(self.path)
            return
        # 已配对的设备：展开 / 收起（和 Wi-Fi 弹窗的 turn 32 一样，展开别的行时之前的收起来）
        if self.expanded():
            self.set_expanded(False)
            return
        self.popup.collapse_others(self)
        self.set_expanded(True)

    def toggle_connection(self):
        if self.dev.get("Connected"):
            self.popup.device_action(self.path, "Disconnect", "正在断开 …")
        else:
            self.popup.device_action(self.path, "Connect", "正在连接 …")


class BluetoothPopup:
    def __init__(self):
        self.visible = False
        self.fade_target = 0.0
        self.refresh_pending = False
        self.adapter = None          # 适配器的路径（/org/bluez/hci0）
        self.powered = False
        self.discovering_by_us = False
        self.busy = {}               # 设备路径 → 正在进行的操作（“正在连接 …” 等）
        self.rows = {}               # 设备路径 → DeviceRow
        self.agent_inv = None        # 等待用户回答的配对请求
        self.bz = Bluez()

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = self.make_window(NAMESPACE, catcher=False)
        self.catcher = self.make_window(NAMESPACE + "-catcher", catcher=True)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, name="panel")
        self.panel.set_size_request(WIDTH, -1)
        self.build()
        self.win.add(self.panel)
        self.win.connect("key-press-event", self.on_key)
        self.panel.show_all()
        self.prompt_rev.set_reveal_child(False)
        self.panel.set_opacity(0.0)

        # bluez 的任何变化（属性改变、设备增加 / 消失）→ 刷新
        self.bz.bus.signal_subscribe(BLUEZ, None, None, None, None, Gio.DBusSignalFlags.NONE,
                                     lambda *a: self.schedule_refresh())
        # bluez 重启时重新注册配对代理
        Gio.bus_watch_name_on_connection(self.bz.bus, BLUEZ, Gio.BusNameWatcherFlags.NONE,
                                         lambda *a: self.register_agent(), None)

    # ---------- 画面 ----------
    def build(self):
        head = Gtk.Box(spacing=8)
        head.pack_start(Gtk.Label(label="蓝牙", name="title"), False, False, 0)
        self.sub = Gtk.Label(xalign=0)
        self.sub.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub.get_style_context().add_class("sub")
        head.pack_start(self.sub, True, True, 0)
        self.rescan_btn = Gtk.Button(label=RESCAN, tooltip_text="重新搜索")
        self.rescan_btn.get_style_context().add_class("flat")
        self.rescan_btn.connect("clicked", lambda *_: self.restart_discovery())
        head.pack_start(self.rescan_btn, False, False, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch_handler = self.switch.connect("notify::active", self.on_switch)
        head.pack_start(self.switch, False, False, 0)
        self.panel.pack_start(head, False, False, 0)

        # 配对时的确认 / PIN 码输入
        self.prompt_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.NONE)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, name="prompt")
        self.prompt_text = Gtk.Label(xalign=0)
        self.prompt_text.set_line_wrap(True)
        self.prompt_code = Gtk.Label(name="passkey")
        self.prompt_entry = Gtk.Entry(input_purpose=Gtk.InputPurpose.DIGITS)
        self.prompt_entry.connect("activate", lambda *_: self.agent_answer(True))
        btns = Gtk.Box(spacing=8)
        self.prompt_ok = Gtk.Button(label="确认")
        self.prompt_ok.connect("clicked", lambda *_: self.agent_answer(True))
        self.prompt_cancel = Gtk.Button(label="取消")
        self.prompt_cancel.get_style_context().add_class("danger")
        self.prompt_cancel.connect("clicked", lambda *_: self.agent_answer(False))
        btns.pack_start(self.prompt_ok, True, True, 0)
        btns.pack_start(self.prompt_cancel, True, True, 0)
        for w in (self.prompt_text, self.prompt_code, self.prompt_entry, btns):
            box.pack_start(w, False, False, 0)
        self.prompt_rev.add(box)
        self.panel.pack_start(self.prompt_rev, False, False, 0)

        self.off_label = Gtk.Label(label="蓝牙已关闭", xalign=0.5)
        self.off_label.get_style_context().add_class("empty")
        self.panel.pack_start(self.off_label, False, False, 0)

        self.lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.paired_label = self.section("我的设备")
        self.paired = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.paired.connect("row-activated", lambda lb, row: row.activate_row())
        self.nearby_label = self.section("附近的设备")
        self.nearby = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.nearby.connect("row-activated", lambda lb, row: row.activate_row())
        self.nearby_empty = Gtk.Label(label="正在搜索 …", xalign=0)
        self.nearby_empty.get_style_context().add_class("status")
        self.nearby_empty.set_margin_start(10)
        for w in (self.paired_label, self.paired, self.nearby_label, self.nearby, self.nearby_empty):
            self.lists.pack_start(w, False, False, 0)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_max_content_height(MAX_LIST_HEIGHT)
        self.scroll.add(self.lists)
        self.panel.pack_start(self.scroll, True, True, 0)

    @staticmethod
    def section(text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.get_style_context().add_class("section")
        return lbl

    def fit_size(self):
        def do():
            h = self.lists.get_preferred_height()[1]
            self.scroll.set_min_content_height(min(h, MAX_LIST_HEIGHT))
            self.win.resize(WIDTH, 1)  # 按内容重新计算大小（GTK3 的窗口不会自动跟着内容变大 / 变小）
            return False
        GLib.idle_add(do)

    def collapse_others(self, keep):
        for r in self.rows.values():
            if r is not keep and r.expanded() and r.path not in self.busy:
                r.set_expanded(False)

    # ---------- 数据 ----------
    def schedule_refresh(self):
        # 短时间内的多次变化合并成一次刷新；隐藏中不刷新（显示时会刷新）
        if self.visible and not self.refresh_pending:
            self.refresh_pending = True
            GLib.timeout_add(80, self.refresh)
        return False

    def refresh(self):
        self.refresh_pending = False
        self.bz.objects(self.fill)
        return False

    def fill(self, objs, err):
        adapters = sorted(p for p, ifs in objs.items() if ADAPTER in ifs)
        if not adapters:
            self.adapter = None
            self.sub.set_text("没有找到蓝牙适配器" if not err else error_text(err))
            self.set_powered_ui(False, no_adapter=True)
            return
        self.adapter = adapters[0]
        ad = objs[self.adapter][ADAPTER]
        self.set_powered_ui(bool(ad.get("Powered")))
        if self.powered and self.visible and not ad.get("Discovering") and not self.discovering_by_us:
            self.start_discovery()

        devs = {p: ifs for p, ifs in objs.items()
                if DEVICE in ifs and ifs[DEVICE].get("Adapter") == self.adapter}
        paired = [p for p, ifs in devs.items() if ifs[DEVICE].get("Paired") or ifs[DEVICE].get("Bonded")]
        # 正在配对的设备一直放在“附近的设备”里，直到配对完成
        nearby = [p for p, ifs in devs.items()
                  if p not in paired and (ifs[DEVICE].get("Name") or p in self.busy)]

        def name(p):
            d = devs[p][DEVICE]
            return (d.get("Alias") or d.get("Name") or "").lower()
        paired.sort(key=lambda p: (not devs[p][DEVICE].get("Connected"), name(p)))
        nearby.sort(key=lambda p: (p not in self.busy, -devs[p][DEVICE].get("RSSI", -999), name(p)))
        nearby = nearby[:MAX_NEARBY]
        n_conn = sum(1 for p in paired if devs[p][DEVICE].get("Connected"))
        self.sub.set_text(f"{n_conn} 个设备已连接" if n_conn else
                          ("正在搜索附近的设备 …" if ad.get("Discovering") else ""))

        changed = self.sync_list(self.paired, paired, devs)
        changed |= self.sync_list(self.nearby, nearby, devs)
        self.paired_label.set_visible(bool(paired))
        self.paired.set_visible(bool(paired))
        self.nearby_empty.set_text("正在搜索 …" if ad.get("Discovering") else "没有找到设备（点 󰑐 重新搜索）")
        self.nearby_empty.set_visible(not nearby)
        if changed:
            self.fit_size()

    def sync_list(self, listbox, paths, devs):
        """列表里的设备（和顺序）没变时只更新文字，不重建（不会闪，展开的行也保持展开）"""
        if [r.path for r in listbox.get_children()] != paths:
            for r in listbox.get_children():
                listbox.remove(r)
            for p in paths:
                row = self.rows.get(p) or DeviceRow(self, p)
                self.rows[p] = row
                parent = row.get_parent()
                if parent is not None:
                    parent.remove(row)
                listbox.add(row)
            # 不在任何列表里的设备的行丢掉
            keep = set(r.path for lb in (self.paired, self.nearby) for r in lb.get_children())
            for p in list(self.rows):
                if p not in keep:
                    del self.rows[p]
            changed = True
        else:
            changed = False
        for p in paths:
            bat = devs[p].get(BATTERY, {}).get("Percentage")
            self.rows[p].update(devs[p][DEVICE], bat)
        return changed

    def set_powered_ui(self, on, no_adapter=False):
        self.powered = on
        self.switch.handler_block(self.switch_handler)
        self.switch.set_active(on)
        self.switch.handler_unblock(self.switch_handler)
        self.switch.set_sensitive(not no_adapter)
        self.rescan_btn.set_visible(on)
        self.scroll.set_visible(on)
        self.off_label.set_visible(not on)
        if not on:
            self.discovering_by_us = False  # 关闭蓝牙时搜索也会停止；再打开时重新开始
            if not no_adapter:
                self.sub.set_text("")
        self.fit_size()

    # ---------- 操作 ----------
    def on_switch(self, sw, _):
        if self.adapter:
            set_power(self.bz, self.adapter, sw.get_active(), lambda: self.refresh())

    def start_discovery(self):
        if not self.adapter:
            return
        self.discovering_by_us = True
        self.bz.call(self.adapter, ADAPTER, "StartDiscovery",
                     done=lambda out, err: self.schedule_refresh())

    def stop_discovery(self):
        if self.adapter and self.discovering_by_us:
            self.bz.call(self.adapter, ADAPTER, "StopDiscovery")
        self.discovering_by_us = False

    def restart_discovery(self):
        if not self.adapter:
            return
        # bluez 的搜索不会“重新开始”，先停再开
        self.bz.call(self.adapter, ADAPTER, "StopDiscovery",
                     done=lambda out, err: self.start_discovery())

    def set_busy(self, path, text):
        if text:
            self.busy[path] = text
        else:
            self.busy.pop(path, None)
        self.schedule_refresh()

    def report(self, path, err, ok_text=None):
        row = self.rows.get(path)
        if row:
            if err:
                row.show_message(error_text(err), error=True)
            else:
                row.show_message(ok_text)

    def device_action(self, path, method, busy_text, then=None):
        self.set_busy(path, busy_text)
        row = self.rows.get(path)
        if row:
            row.show_message(None)

        def done(out, err):
            self.set_busy(path, None)
            if err or not then:
                self.report(path, err)
            if not err and then:
                then()
        self.bz.call(path, DEVICE, method, done=done, timeout_ms=60000)

    def pair(self, path):
        """配对 → 信任（以后设备可以自己连过来）→ 连接"""
        # 配对时停止搜索（搜索中配对容易失败）
        self.stop_discovery()

        def paired():
            self.bz.set_prop(path, DEVICE, "Trusted", GLib.Variant("b", True))
            self.device_action(path, "Connect", "正在连接 …")
        self.device_action(path, "Pair", "正在配对 …", then=paired)

    def remove_device(self, path):
        if self.adapter:
            self.bz.call(self.adapter, ADAPTER, "RemoveDevice", GLib.Variant("(o)", (path,)),
                         done=lambda out, err: self.report(path, err) if err else self.refresh())

    # ---------- 配对代理（PIN 码 / 数字确认） ----------
    def register_agent(self):
        if not hasattr(self, "agent_id"):
            info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0]
            reg = getattr(self.bz.bus, "register_object_with_closures2", None) or self.bz.bus.register_object
            self.agent_id = reg(AGENT_PATH, info, self.agent_call, None, None)

        def registered(out, err):
            if not err:
                self.bz.call("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
                             GLib.Variant("(o)", (AGENT_PATH,)))
        # KeyboardDisplay：能显示数字，也能输入 PIN 码
        self.bz.call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                     GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")), done=registered)

    def device_name(self, path):
        row = self.rows.get(path)
        if row and row.dev:
            return row.dev.get("Alias") or row.dev.get("Name") or path
        return path.rsplit("/", 1)[-1].replace("dev_", "").replace("_", ":")

    def agent_call(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        name = self.device_name(args[0]) if args and isinstance(args[0], str) and args[0].startswith("/") else ""
        if method == "RequestConfirmation":
            self.show_prompt(inv, method, f"请确认 {name} 上显示的数字和下面一样：", f"{args[1]:06d}")
        elif method == "RequestAuthorization":
            self.show_prompt(inv, method, f"允许 {name} 配对吗？")
        elif method in ("RequestPinCode", "RequestPasskey"):
            self.show_prompt(inv, method, f"请输入 {name} 的 PIN 码：", entry=True)
        elif method == "DisplayPinCode":
            self.show_prompt(None, method, f"请在 {name} 上输入下面的 PIN 码，然后按 Enter：", args[1])
            inv.return_value(None)
        elif method == "DisplayPasskey":
            self.show_prompt(None, method, f"请在 {name} 上输入下面的数字，然后按 Enter：", f"{args[1]:06d}")
            inv.return_value(None)
        elif method == "AuthorizeService":
            # 已配对的设备连接过来时会问这个：已配对 → 允许，否则拒绝
            dev = self.rows.get(args[0])
            if dev and dev.dev.get("Paired"):
                inv.return_value(None)
            else:
                inv.return_dbus_error("org.bluez.Error.Rejected", "not paired")
        elif method in ("Cancel", "Release"):
            self.hide_prompt()
            inv.return_value(None)
        else:
            inv.return_dbus_error("org.bluez.Error.Rejected", "unknown")

    def show_prompt(self, inv, method, text, code=None, entry=False):
        if self.agent_inv is not None:  # 前一个还没回答的请求：拒绝
            self.agent_inv[0].return_dbus_error("org.bluez.Error.Canceled", "replaced")
        self.agent_inv = (inv, method) if inv else None
        self.prompt_text.set_text(text)
        self.prompt_code.set_text(code or "")
        self.prompt_code.set_visible(bool(code))
        self.prompt_entry.set_text("")
        self.prompt_entry.set_visible(entry)
        self.prompt_ok.set_visible(inv is not None)
        self.prompt_cancel.set_label("取消" if inv is not None else "关闭")
        self.prompt_rev.set_reveal_child(True)
        if not self.visible:  # 手机等从对方发起配对时，弹窗还没打开 → 打开
            self.show(place=False)
        (self.prompt_entry if entry else self.prompt_ok if inv else self.prompt_cancel).grab_focus()
        self.fit_size()

    def hide_prompt(self):
        if self.agent_inv is not None:
            self.agent_inv[0].return_dbus_error("org.bluez.Error.Canceled", "canceled")
            self.agent_inv = None
        self.prompt_rev.set_reveal_child(False)
        self.fit_size()

    def agent_answer(self, ok):
        if self.agent_inv is None:
            self.hide_prompt()
            return
        inv, method = self.agent_inv
        self.agent_inv = None
        if not ok:
            inv.return_dbus_error("org.bluez.Error.Rejected", "rejected by user")
        elif method == "RequestPinCode":
            inv.return_value(GLib.Variant("(s)", (self.prompt_entry.get_text().strip(),)))
        elif method == "RequestPasskey":
            try:
                inv.return_value(GLib.Variant("(u)", (int(self.prompt_entry.get_text().strip()),)))
            except ValueError:
                inv.return_dbus_error("org.bluez.Error.Rejected", "invalid passkey")
        else:
            inv.return_value(None)
        self.hide_prompt()

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
        """turn 46：查一下“现在”模块在哪里，弹窗的右边对准模块的右边，显示在点击的那块屏幕上
        （约 20～25ms；查不到时保持上一次的位置，第一次是 MARGIN_RIGHT）"""
        pos = popup_anchor.locate()
        if pos is None:
            return
        monitor, margin = pos
        if monitor is not None:
            for w in (self.win, self.catcher):
                GtkLayerShell.set_monitor(w, monitor)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.RIGHT, margin)

    def show(self, place=True):
        if self.visible:
            return
        self.visible = True
        if place:  # 配对请求自动打开时（place=False）鼠标不一定在栏上，不查
            self.place()
        self.refresh()  # 蓝牙开着的话，refresh 里会开始搜索附近的设备
        self.catcher.show()
        self.win.show()
        self.switch.grab_focus()
        self.fit_size()
        self.fade_to(1.0)

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        if self.agent_inv is not None:  # 配对确认没回答就关掉了 → 拒绝
            self.hide_prompt()
        self.stop_discovery()  # 一直搜索会耗电，关掉弹窗时停止
        for r in self.rows.values():
            if r.expanded() and r.path not in self.busy:
                r.set_expanded(False)
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
            if self.prompt_rev.get_reveal_child():
                self.agent_answer(False)
            else:
                self.hide()
            return True
        return False


def set_power(bz, adapter, on, done=None):
    """蓝牙的开 / 关。被 rfkill 禁用时（Blocked）先解除再开"""
    def finish(out, err):
        if err and on and "Blocked" in err.message:
            subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True)
            GLib.timeout_add(500, lambda: (bz.set_prop(adapter, ADAPTER, "Powered", GLib.Variant("b", True),
                                                       lambda *a: done and done()), False)[1])
            return
        if done:
            done()
    bz.set_prop(adapter, ADAPTER, "Powered", GLib.Variant("b", on), finish)


def main():
    show_now = "--show" in sys.argv
    try:
        pid = int(open(PIDFILE).read())
        if pid != os.getpid() and "bluetooth-popup.py" in open(f"/proc/{pid}/cmdline").read():
            os.kill(pid, signal.SIGUSR1)
            return
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    popup = BluetoothPopup()
    # 不能在信号的回调里直接显示窗口（会卡在 gtk-layer-shell 显示图层的地方，turn 30），所以交给 idle
    GLibUnix.signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1,
                        lambda: (GLib.idle_add(popup.toggle), True)[1])
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (Gtk.main_quit(), False)[1])
    if show_now:
        GLib.idle_add(lambda: (popup.show(), False)[1])
    try:
        Gtk.main()
    finally:
        popup.stop_discovery()
        try:
            if open(PIDFILE).read().strip() == str(os.getpid()):
                os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
