#!/usr/bin/env python3
# Wi-Fi 弹窗（turn 30，turn 23 的方案 D）：点击 waybar 的 Wi-Fi 模块时，从模块上方淡入显示
#
# · 常驻后台（平时隐藏），收到 SIGUSR1 时 显示 ⇄ 隐藏（由 wifi-popup-toggle.sh 发送），所以点击后马上出现
# · 用 gtk-layer-shell 显示成图层，图层名 “wifi-menu”（mango 的 layerrule 可以单独设置它）
# · 淡入 / 淡出由程序自己做，时间 FADE_MS（0.2 秒）；mango 那边对这个图层设置 noanim:1（不再叠加动画）
#   （mango 的动画时间是所有窗口共用的设置，没法只给这个弹窗设成 0.2 秒，所以由程序自己做）
# · 点击弹窗外面自动关闭：显示时在弹窗后面铺一层完全透明的全屏图层（“wifi-menu-catcher”），点到它就关闭
# · 实际的扫描 / 连接 / 保存密码沿用 wifi-menu.py（rofi 版）里的 nmcli 处理；密码不会出现在命令行参数里
#
# 操作：直接打字 → 按名字过滤  ↑↓ → 选择  Enter / 点击 → 连接（加密的新网络会在那一行下面展开密码框）
#       点击已连接的网络 → 显示“断开连接”  Esc → 收起展开的部分 / 关闭  点击外面 → 关闭

import importlib.util
import os
import signal
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLibUnix", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, GLibUnix, Gtk, GtkLayerShell, Pango  # noqa: E402

# turn 46：弹窗位置的计算（和其他弹窗共用，popup_anchor.py）
sys.dont_write_bytecode = True  # 不在 scripts 目录里生成 __pycache__
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import popup_anchor  # noqa: E402

# ---------- 设置 ----------
MODE = "layer"          # "layer"：图层（现在用的）  "window"：普通窗口（turn 29；需要 mango 的 windowrule，见文件末尾）
FADE_MS = 200           # 淡入 / 淡出的时间（毫秒）
WIDTH = 420             # 弹窗宽度
MARGIN_RIGHT = 255      # 离屏幕右边的距离（对准 Wi-Fi 模块）
#   turn 46 起：每次打开时查模块的实际位置（place），这个值只在查不到时使用
MARGIN_BOTTOM = 8       # 离 waybar 的距离
LIST_MAX_HEIGHT = 330   # 列表最多显示的高度（超过时可以滚动）
REFRESH_SEC = 5         # 打开期间自动刷新列表的间隔
NAMESPACE = "wifi-menu"

HERE = os.path.dirname(os.path.realpath(__file__))
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
PIDFILE = os.path.join(RUNTIME, f"wifi-popup-{os.environ.get('WAYLAND_DISPLAY', 'wayland-0')}.pid")

# 沿用 rofi 版 wifi-menu.py 里的 nmcli 处理（scan / saved_profile / set_password / wifi_device / nmcli）
sys.dont_write_bytecode = True  # 不在 scripts 目录里生成 __pycache__
_spec = importlib.util.spec_from_file_location("wifi_menu", os.path.join(HERE, "wifi-menu.py"))
nm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nm)

SIGNAL_ICONS = nm.SIGNAL_ICONS  # 󰤟 󰤢 󰤥 󰤨
LOCK = "󰌾"

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
entry {
    background-color: #3a3470; background-image: none; color: #c9b9f2;
    border: none; border-radius: 8px; box-shadow: none; padding: 4px 10px;
    caret-color: #f5a0c8; min-height: 0;
}
entry selection { background-color: #c8b8f8; color: #1f1a3d; }
scrolledwindow, viewport, list { background-color: transparent; border: none; }
/* transition: none —— 系统 GTK 主题（Adwaita）给行的背景色加了 150ms 的过渡动画，
   列表重建时选中行会先变暗再变回粉色，看起来像闪了一下（turn 31），所以关掉 */
row { padding: 5px 10px; border-radius: 8px; background-color: transparent; outline: none; transition: none; }
row:hover { background-color: rgba(58, 52, 112, 0.85); }
row:selected, row:selected:hover { background-color: #f5a0c8; }
row:selected label { color: #1f1a3d; }
row:selected entry { background-color: #1f1a3d; color: #c9b9f2; }
.icons { color: #a898e8; }
row:selected .icons { color: #1f1a3d; }
.connected { color: #8fd4a8; font-size: 11pt; }
row:selected .connected { color: #1f1a3d; font-weight: bold; }
.status { color: #8e8c9e; font-size: 11pt; }
.error { color: #f07a9a; font-size: 11pt; }
row:selected .error { color: #8a1c3c; }
row:selected .status { color: #3a3470; }
button {
    background-color: #6c5cc4; background-image: none; color: #fbfaff;
    border: none; border-radius: 8px; box-shadow: none; text-shadow: none;
    padding: 4px 12px; min-height: 0;
}
button label { color: #fbfaff; }
button:hover { background-color: #7d6dd6; }
button.flat { background-color: transparent; }
button.flat label { color: #c9b9f2; }
button.flat:hover { background-color: rgba(58, 52, 112, 0.85); }
switch {
    background-color: #3a3470; background-image: none; border: none;
    border-radius: 12px; box-shadow: none; min-height: 0;
}
switch:checked { background-color: #6c5cc4; }
switch slider {
    background-color: #f5a0c8; background-image: none; border: none;
    border-radius: 10px; box-shadow: none; min-width: 20px; min-height: 20px;
}
switch image { color: transparent; }
separator { background-color: rgba(108, 92, 196, 0.5); min-height: 1px; margin: 6px 0; }
#empty { color: #8e8c9e; padding: 16px; }
"""


def run_bg(func, done=None, *args):
    """在后台线程里执行 nmcli（不让画面卡住），结束后回到主线程执行 done(结果)"""
    def work():
        try:
            res = func(*args)
        except Exception as e:  # noqa: BLE001
            res = e
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=work, daemon=True).start()


def connect_job(ssid, security, password):
    """返回 (结果, 信息)  结果：ok / need_password / error / unsupported"""
    dev = nm.wifi_device()
    profile = nm.saved_profile(ssid)
    if profile:  # 已保存过的网络
        if password:
            nm.set_password(profile, password)
        r = nm.nmcli("--wait", "30", "connection", "up", "id", profile)
        if r.returncode == 0:
            return "ok", None
        if security:
            return "need_password", "连接失败，请重新输入密码"
        return "error", r.stderr.strip()
    if "802.1X" in security:
        return "unsupported", "企业认证（802.1X）网络请用 nmtui（右键 Wi-Fi 模块）"
    if "WEP" in security:
        return "unsupported", "WEP 网络请用 nmtui（右键 Wi-Fi 模块）"
    if security and not password:
        return "need_password", None
    # 新网络：建立配置 → 设置密码（通过标准输入）→ 连接；失败时删掉配置
    args = ["connection", "add", "type", "wifi", "con-name", ssid, "ssid", ssid]
    if dev:
        args += ["ifname", dev]
    if security:
        key_mgmt = "sae" if ("WPA3" in security and "WPA2" not in security and "WPA1" not in security) else "wpa-psk"
        args += ["wifi-sec.key-mgmt", key_mgmt]
    r = nm.nmcli(*args)
    if r.returncode != 0:
        return "error", r.stderr.strip()
    if security:
        nm.set_password(ssid, password)
    r = nm.nmcli("--wait", "30", "connection", "up", "id", ssid)
    if r.returncode != 0:
        nm.nmcli("connection", "delete", "id", ssid)
        return "need_password" if security else "error", "连接失败（密码错误或信号太弱）"
    return "ok", None


class NetRow(Gtk.ListBoxRow):
    def __init__(self, popup, in_use, sig, sec, ssid):
        super().__init__()
        self.popup, self.in_use, self.sig, self.sec, self.ssid = popup, in_use, sig, sec, ssid
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        line = Gtk.Box(spacing=10)
        self.icons = Gtk.Label()
        self.icons.get_style_context().add_class("icons")
        self.set_signal(sig)
        icons = self.icons
        name = Gtk.Label(label=ssid, xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        line.pack_start(icons, False, False, 0)
        line.pack_start(name, True, True, 0)
        if in_use:
            mark = Gtk.Label(label="󰄬 已连接")
            mark.get_style_context().add_class("connected")
            line.pack_end(mark, False, False, 0)
        outer.pack_start(line, False, False, 0)

        # 展开部分：密码框 + 连接按钮 / 断开按钮 / 状态信息
        # 展开 / 收起是瞬间完成的（高度变化后要重新计算弹窗大小，见 WifiPopup.fit_size）
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.NONE)
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=4)
        self.pw_box = Gtk.Box(spacing=8)
        self.pw = Gtk.Entry(visibility=False, placeholder_text="密码",
                            input_purpose=Gtk.InputPurpose.PASSWORD)  # 告诉输入法这是密码，fcitx5 不会介入
        self.pw.connect("activate", lambda *_: self.do_connect())
        btn = Gtk.Button(label="连接")
        btn.connect("clicked", lambda *_: self.do_connect())
        self.pw_box.pack_start(self.pw, True, True, 0)
        self.pw_box.pack_start(btn, False, False, 0)
        self.disc_btn = Gtk.Button(label="󰖪 断开连接")
        self.disc_btn.connect("clicked", lambda *_: self.popup.disconnect_current())
        self.msg = Gtk.Label(xalign=0)
        self.msg.set_line_wrap(True)
        detail.pack_start(self.pw_box, False, False, 0)
        detail.pack_start(self.disc_btn, False, False, 0)
        detail.pack_start(self.msg, False, False, 0)
        self.revealer.add(detail)
        outer.pack_start(self.revealer, False, False, 0)
        self.add(outer)
        self.show_all()
        self.pw_box.hide()
        self.disc_btn.hide()
        self.msg.hide()

    def key(self):
        return (self.ssid, self.in_use, self.sec)

    def set_signal(self, sig):
        self.sig = sig
        self.icons.set_text(SIGNAL_ICONS[min(3, sig // 25)] + (f" {LOCK}" if self.sec else "  "))

    def expanded(self):
        return self.revealer.get_reveal_child()

    def collapse(self):
        self.revealer.set_reveal_child(False)
        self.pw.set_text("")  # 收起时清掉没连接的密码
        self.popup.fit_size()

    def show_message(self, text, error=False):
        ctx = self.msg.get_style_context()
        ctx.remove_class("error")
        ctx.remove_class("status")
        ctx.add_class("error" if error else "status")
        self.msg.set_text(text or "")
        self.msg.set_visible(bool(text))
        self.popup.fit_size()

    def ask_password(self, message=None):
        self.disc_btn.hide()
        self.pw_box.show()
        self.show_message(message, error=bool(message))
        self.revealer.set_reveal_child(True)
        self.popup.fit_size()
        self.pw.grab_focus()

    def activate_row(self):
        if self.popup.busy:
            return
        # turn 32：再点一次已经展开的网络 → 收起
        if self.expanded():
            self.collapse()
            return
        # turn 32：点了别的网络 → 之前展开的（没有连接的）都收起来
        self.popup.collapse_others(self)
        if self.in_use:  # 已连接：显示“断开连接”
            self.pw_box.hide()
            self.show_message(None)
            self.disc_btn.show()
            self.revealer.set_reveal_child(True)
            self.popup.fit_size()
            return
        if self.sec and not nm.saved_profile(self.ssid):
            self.ask_password()
            return
        self.do_connect()

    def do_connect(self):
        if self.popup.busy:
            return
        password = self.pw.get_text() if self.pw_box.get_visible() else None
        if self.pw_box.get_visible() and not password:
            self.show_message("请输入密码", error=True)
            return
        self.popup.busy = True
        self.disc_btn.hide()
        self.show_message(f"正在连接 {self.ssid} …")
        self.revealer.set_reveal_child(True)
        self.popup.fit_size()

        def done(res):
            self.popup.busy = False
            if isinstance(res, Exception):
                self.show_message(str(res), error=True)
                return
            result, info = res
            if result == "ok":
                self.pw.set_text("")
                self.popup.refresh(keep_selection=self.ssid)  # 列表里会显示“已连接”
            elif result == "need_password":
                self.pw.set_text("")
                self.ask_password(info)
            else:
                self.pw_box.hide()
                self.show_message(info, error=True)
        run_bg(connect_job, done, self.ssid, self.sec, password)


class WifiPopup:
    def __init__(self):
        self.busy = False
        self.visible = False
        self.fade_target = 0.0
        self.refresh_id = None

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = self.make_window(NAMESPACE, catcher=False)
        self.catcher = self.make_window(NAMESPACE + "-catcher", catcher=True) if MODE == "layer" else None

        # ---- 画面内容 ----
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, name="panel")
        self.panel.set_size_request(WIDTH, -1)
        head = Gtk.Box(spacing=8)
        head.pack_start(Gtk.Label(label="Wi-Fi", name="title"), False, False, 0)
        self.search = Gtk.Entry(placeholder_text="搜索…")
        self.search.connect("changed", self.on_search)
        self.search.connect("activate", lambda *_: self.activate_selected())
        head.pack_start(self.search, True, True, 0)
        self.panel.pack_start(head, False, False, 0)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.set_filter_func(self.filter_row)
        self.listbox.connect("row-activated", lambda lb, row: row.activate_row())
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_max_content_height(LIST_MAX_HEIGHT)
        self.scroll.add(self.listbox)
        self.empty = Gtk.Label(name="empty")
        self.panel.pack_start(self.scroll, True, True, 0)
        self.panel.pack_start(self.empty, False, False, 0)

        self.panel.pack_start(Gtk.Separator(), False, False, 0)
        foot = Gtk.Box(spacing=8)
        self.rescan_btn = Gtk.Button(label="󰑐 重新扫描")
        self.rescan_btn.get_style_context().add_class("flat")
        self.rescan_btn.connect("clicked", lambda *_: self.rescan())
        self.foot_msg = Gtk.Label(xalign=0)
        self.foot_msg.get_style_context().add_class("status")
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch_handler = self.switch.connect("notify::active", self.on_switch)
        foot.pack_start(self.rescan_btn, False, False, 0)
        foot.pack_start(self.foot_msg, True, True, 0)
        foot.pack_end(self.switch, False, False, 0)
        foot.pack_end(Gtk.Label(label="Wi-Fi"), False, False, 0)
        self.panel.pack_start(foot, False, False, 0)

        self.win.add(self.panel)
        self.win.connect("key-press-event", self.on_key)
        self.panel.show_all()      # 内容只在这里显示一次；之后显示 / 隐藏只针对窗口本身
        self.empty.hide()
        self.panel.set_opacity(0.0)

    # ---------- 窗口 ----------
    def make_window(self, namespace, catcher):
        win = Gtk.Window()
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)  # 透明背景（圆角外面、全屏透明层）
        win.set_app_paintable(True)
        if MODE == "layer":
            GtkLayerShell.init_for_window(win)
            GtkLayerShell.set_namespace(win, namespace)
            if catcher:
                # 全屏透明层：盖住整个屏幕（包括 waybar），点到它就关闭弹窗
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
        else:
            # 普通窗口（turn 29）：位置 / 浮动由 mango 的 windowrule 决定；失去焦点 = 点了外面 → 关闭
            win.set_title("Wi-Fi")
            win.set_decorated(False)
            win.connect("focus-out-event", lambda *_: self.hide())
        win.connect("delete-event", lambda *_: (self.hide(), True)[1])
        return win

    # ---------- 显示 / 隐藏（淡入淡出） ----------
    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()
        return True

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

    def show(self):
        if self.visible:
            return
        self.visible = True
        if MODE == "layer":
            self.place()
        self.search.set_text("")
        self.foot_msg.set_text("")
        self.refresh()
        # 后台重新扫描，2.5 秒后刷新一次列表
        run_bg(lambda: nm.nmcli("device", "wifi", "rescan"),
               lambda _: GLib.timeout_add(2500, lambda: (self.refresh_if_idle(), False)[1]))
        if self.catcher:
            self.catcher.show()
        self.win.show()
        self.search.grab_focus()
        self.fade_to(1.0)
        self.refresh_id = GLib.timeout_add_seconds(REFRESH_SEC, self.refresh_if_idle)

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        if self.refresh_id:
            GLib.source_remove(self.refresh_id)
            self.refresh_id = None
        self.fade_to(0.0)

    def fade_to(self, target):
        self.fade_target = target
        start = self.panel.get_opacity()
        t0 = time.monotonic()

        def tick(widget, clock):
            if self.fade_target != target:  # 中途又切换了方向
                return False
            p = min(1.0, (time.monotonic() - t0) * 1000 / FADE_MS) if FADE_MS > 0 else 1.0
            ease = 1 - (1 - p) ** 2  # 先快后慢
            self.panel.set_opacity(start + (target - start) * ease)
            if p >= 1.0:
                if target == 0.0:
                    self.win.hide()
                    if self.catcher:
                        self.catcher.hide()
                return False
            return True
        self.panel.add_tick_callback(tick)

    def collapse_others(self, keep):
        for r in self.listbox.get_children():
            if r is not keep and r.expanded():
                r.collapse()

    def fit_size(self):
        """按“现在显示着的行”的高度调整列表和弹窗的大小（GTK3 的窗口不会因为内容变多而自动变大）"""
        def do():
            rows = self.visible_rows()
            h = sum(r.get_preferred_height()[1] for r in rows)
            self.scroll.set_min_content_height(min(h, LIST_MAX_HEIGHT))
            self.scroll.set_max_content_height(LIST_MAX_HEIGHT)
            self.win.resize(WIDTH, 1)  # 请求最小的大小 → 正好包住内容（行变少时也会缩小）
            return False
        GLib.idle_add(do)

    # ---------- 列表 ----------
    def refresh_if_idle(self):
        if not self.visible:
            return False
        if not self.busy and not any(r.expanded() for r in self.listbox.get_children()) \
                and not self.search.get_text():
            self.refresh(keep_selection=self.selected_ssid())
        return True  # 继续定时刷新

    def selected_ssid(self):
        row = self.listbox.get_selected_row()
        return row.ssid if row else None

    def refresh(self, keep_selection=None):
        def load():
            on = nm.nmcli("radio", "wifi").stdout.strip() == "enabled"
            return on, (nm.scan() if on else [])
        run_bg(load, lambda res: self.fill(res, keep_selection))

    def fill(self, res, keep_selection):
        if isinstance(res, Exception):
            self.foot_msg.set_text(str(res))
            return
        on, nets = res
        self.switch.handler_block(self.switch_handler)
        self.switch.set_active(on)
        self.switch.handler_unblock(self.switch_handler)
        rows = self.listbox.get_children()
        if [r.key() for r in rows] == [(ssid, in_use, sec) for in_use, sig, sec, ssid in nets]:
            # 网络和顺序都没变：只更新信号强度的图标，不重建列表（turn 31：避免选中行闪烁）
            for r, (in_use, sig, sec, ssid) in zip(rows, nets):
                if r.sig != sig:
                    r.set_signal(sig)
            return
        for row in rows:
            self.listbox.remove(row)
        for net in nets:
            self.listbox.add(NetRow(self, *net))
        if not on:
            self.empty.set_text("Wi-Fi 已关闭")
        elif not nets:
            self.empty.set_text("没有找到网络")
        else:
            self.empty.set_text("")
        self.empty.set_visible(not on or not nets)
        self.scroll.set_visible(bool(nets))
        self.rescan_btn.set_sensitive(on)
        self.select_first(prefer=keep_selection)
        self.fit_size()

    def visible_rows(self):
        return [r for r in self.listbox.get_children() if r.get_child_visible() and self.filter_row(r)]

    def select_first(self, prefer=None):
        rows = self.visible_rows()
        target = next((r for r in rows if r.ssid == prefer), rows[0] if rows else None)
        if target:
            self.listbox.select_row(target)

    def filter_row(self, row):
        q = self.search.get_text().strip().lower()
        return not q or q in row.ssid.lower()

    def on_search(self, *_):
        self.listbox.invalidate_filter()
        self.select_first()
        self.fit_size()

    def activate_selected(self):
        row = self.listbox.get_selected_row()
        if row:
            row.activate_row()

    def move_selection(self, delta):
        rows = self.visible_rows()
        if not rows:
            return
        cur = self.listbox.get_selected_row()
        i = rows.index(cur) if cur in rows else -1
        row = rows[max(0, min(len(rows) - 1, i + delta))]
        self.listbox.select_row(row)
        # 让选中的行保持在可见范围内
        alloc = row.get_allocation()
        adj = self.scroll.get_vadjustment()
        if alloc.y < adj.get_value():
            adj.set_value(alloc.y)
        elif alloc.y + alloc.height > adj.get_value() + adj.get_page_size():
            adj.set_value(alloc.y + alloc.height - adj.get_page_size())

    def on_key(self, win, ev):
        key = ev.keyval
        if key == Gdk.KEY_Escape:
            expanded = [r for r in self.listbox.get_children() if r.expanded()]
            if expanded and not self.busy:
                for r in expanded:
                    r.collapse()
                self.search.grab_focus()
            else:
                self.hide()
            return True
        if key in (Gdk.KEY_Up, Gdk.KEY_Down):
            self.move_selection(-1 if key == Gdk.KEY_Up else 1)
            return True
        return False

    # ---------- 底部的操作 ----------
    def rescan(self):
        self.foot_msg.set_text("正在扫描 …")
        self.rescan_btn.set_sensitive(False)

        def done(_):
            GLib.timeout_add(2000, lambda: (self.refresh(keep_selection=self.selected_ssid()),
                                            self.foot_msg.set_text(""),
                                            self.rescan_btn.set_sensitive(True), False)[-1])
        run_bg(lambda: nm.nmcli("--wait", "15", "device", "wifi", "rescan"), done)

    def on_switch(self, sw, _):
        on = sw.get_active()
        self.foot_msg.set_text("正在开启 Wi-Fi …" if on else "正在关闭 Wi-Fi …")

        def done(_):
            self.foot_msg.set_text("")
            GLib.timeout_add(1500 if on else 300, lambda: (self.refresh(), False)[1])
        run_bg(lambda: nm.nmcli("radio", "wifi", "on" if on else "off"), done)

    def disconnect_current(self):
        self.busy = True
        self.foot_msg.set_text("正在断开 …")

        def done(_):
            self.busy = False
            self.foot_msg.set_text("")
            self.refresh()
        run_bg(lambda: nm.nmcli("device", "disconnect", nm.wifi_device()), done)


def main():
    show_now = "--show" in sys.argv
    # 已经有常驻的在运行：只让它切换显示
    try:
        pid = int(open(PIDFILE).read())
        if pid != os.getpid() and "wifi-popup.py" in open(f"/proc/{pid}/cmdline").read():
            os.kill(pid, signal.SIGUSR1)
            return
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    if MODE == "window":
        GLib.set_prgname(NAMESPACE)  # 普通窗口的 app_id（mango 的 windowrule 用它识别）；必须在建立窗口之前设置
    popup = WifiPopup()
    # 注意：不能在信号的回调里直接显示窗口（实测会卡在 gtk-layer-shell 显示图层的地方），
    #       所以收到信号后交给 idle（主循环空闲时）再执行
    GLibUnix.signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1,
                        lambda: (GLib.idle_add(lambda: (popup.toggle(), False)[1]), True)[1])
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

# ---------- MODE = "window"（普通窗口）时需要在 mango 的 config.conf 里加的规则（turn 29） ----------
# windowrule=appid:^wifi-menu$,isfloating:1,offsetx:100,offsety:100,width:428,height:460,isnoborder:1,animation_type_open:zoom,animation_type_close:zoom
# 注意：普通窗口的位置是 mango 按“刚出现时的大小”计算的，之后窗口变高会超出屏幕下边，
#       所以要用 height 把高度固定下来（列表行数少时，下面会留出空白）。图层模式没有这个问题。
