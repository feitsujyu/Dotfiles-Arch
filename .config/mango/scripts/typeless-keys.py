#!/usr/bin/env python3
# Typeless（语音输入）的三个功能用哪个键：弹出窗口，依次按想用的键，生成 ~/.config/mango/typeless-keys.conf
#
# typeless-keys.conf 是这台电脑自己的设置（键盘不一样），不放进仓库；typeless.conf 用 source_optional 读入。
# 生成的是 mango 的 bind（按下时），让 typeless-trigger.py 在虚拟键盘上“轻按”Typeless 的快捷键。
#
#   每一步按下要用的键（单个键或组合键，例如 Ctrl + Alt + Z），画面上显示按下的键，确认后点“下一步”
#   键用键码（code:数字）记录：和键盘布局无关，就是按下的那个实体键；组合键的修饰键记成 mango 的 CTRL / ALT 等
#   Ctrl / Shift / Alt / Super 这类修饰键也可以单独用（例如右边的 Ctrl），但这个键原来的作用就没有了
#   已经被 mango 的其他快捷键占用的键（组合键），按了窗口收不到（mango 先拿走了），要选别的键
#   选键的时候，现在的 Typeless 的键暂时不起作用（否则按了会直接启动 Typeless，窗口收不到）；取消时恢复原样

import os
import re
import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

KEYS_FILE = os.path.expanduser("~/.config/mango/typeless-keys.conf")
TRIGGER = "~/.config/mango/scripts/typeless-trigger.py"
RELOAD_WAIT = 0.6  # 秒：写了文件之后，等 mango 重新读入设置

# 功能：（typeless-trigger.py 的名字，显示的名字，Typeless 默认的键）
FEATURES = [
    ("dictation", "听写", "Right Alt"),
    ("ask", "Ask Anything", "Right Alt + Space"),
    ("translate", "翻译模式", "Right Alt + Right Shift"),
]

# 组合键里按着的修饰键（GTK 的状态）→ mango 的写法。按这个顺序显示
MOD_MASKS = [
    (Gdk.ModifierType.CONTROL_MASK, "CTRL"),
    (Gdk.ModifierType.SHIFT_MASK, "SHIFT"),
    (Gdk.ModifierType.MOD1_MASK, "ALT"),
    (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK, "SUPER"),
    (Gdk.ModifierType.HYPER_MASK | Gdk.ModifierType.MOD3_MASK, "HYPER"),
]
MOD_NAMES = {"CTRL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt", "SUPER": "Super", "HYPER": "Hyper"}
# 单独当作键用时可以选的修饰键（mango 的快捷键表示不了 AltGr 等，不能选）
MODIFIER_KEYS = {
    "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
    "Super_L", "Super_R", "Hyper_L", "Hyper_R",
}

# 显示用的键名（没有的显示 keysym 的名字）
DISPLAY_NAMES = {
    "Henkan_Mode": "変換", "Henkan": "変換", "Muhenkan": "無変換", "Hiragana_Katakana": "カタカナひらがな",
    "Control_L": "Left Ctrl", "Control_R": "Right Ctrl",
    "Shift_L": "Left Shift", "Shift_R": "Right Shift",
    "Alt_L": "Left Alt", "Alt_R": "Right Alt",
    "Super_L": "Left Super", "Super_R": "Right Super",
    "Menu": "Menu", "Print": "Print Screen", "Scroll_Lock": "Scroll Lock", "Pause": "Pause",
    "space": "Space", "Return": "Enter", "Escape": "Esc", "BackSpace": "Backspace",
}


def key_text(key):
    """(键码, keysym, 修饰键) → 显示用的文字，例如 Ctrl + Alt + Z"""
    _, keysym, mods = key
    name = DISPLAY_NAMES.get(keysym, keysym.upper() if len(keysym) == 1 else keysym)
    return " + ".join([MOD_NAMES[m] for m in mods] + [name])


def read_current():
    """现在的设置：{功能: (键码, keysym, 修饰键)}，以及文件原来的内容（取消时恢复用）"""
    try:
        with open(KEYS_FILE) as f:
            text = f.read()
    except OSError:
        return {}, None
    current = {}
    for feature, code, keysym, mods in re.findall(
        r"^# key (\w+) code=(\d+) keysym=(\S+)(?: mods=(\S*))?$", text, re.M
    ):
        current[feature] = (int(code), keysym, tuple(m for m in mods.split("+") if m))
    return current, text


def write_file(text):
    tmp = KEYS_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, KEYS_FILE)


def render(keys):
    """keys：{功能: (键码, keysym, 修饰键)} → typeless-keys.conf 的内容"""
    lines = [
        "# Typeless（语音输入）的三个功能用哪个键：这台电脑自己的设置（不放进仓库）",
        "# 由 ~/.config/mango/scripts/typeless-keys.py 生成，改的时候重新运行它",
    ]
    for feature, label, _ in FEATURES:
        if feature not in keys:
            lines += ["", f"# {label}：不使用"]
            continue
        code, keysym, mods = keys[feature]
        lines += [
            "",
            f"# {label}：{key_text(keys[feature])}",
            f"# key {feature} code={code} keysym={keysym} mods={'+'.join(mods)}",
            f"bind={'+'.join(mods) or 'NONE'},code:{code},spawn,{TRIGGER} tap {feature}",
        ]
    return "\n".join(lines) + "\n"


class Setup(Gtk.Window):
    def __init__(self, current, original):
        super().__init__(title="Typeless 的按键设置")
        self.current = current
        self.original = original
        self.keys = {}
        self.step = 0
        self.candidate = None  # 这一步按下的键（还没有点“下一步”）
        self.saved = False

        self.set_default_size(600, 360)
        self.set_border_width(20)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(box)

        self.title = Gtk.Label(xalign=0)
        self.body = Gtk.Label(xalign=0, wrap=True)
        self.pressed = Gtk.Label(xalign=0)
        self.message = Gtk.Label(xalign=0, wrap=True)
        for label in (self.title, self.body, self.pressed, self.message):
            box.pack_start(label, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        box.pack_end(buttons, False, False, 0)
        self.back_button = self.button(buttons, "上一步", self.on_back)
        self.skip_button = self.button(buttons, "不使用这个功能", self.on_skip)
        self.next_button = self.button(buttons, "下一步", self.on_next)
        self.save_button = self.button(buttons, "保存", self.on_save)
        self.button(buttons, "取消", lambda *_: self.close(), pack_end=True)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", self.on_destroy)
        self.show_all()
        self.update()

    def button(self, box, label, callback, pack_end=False):
        button = Gtk.Button(label=label)
        button.set_can_focus(False)  # 按键全部交给窗口（不让空格、回车去按按钮）
        button.connect("clicked", callback)
        (box.pack_end if pack_end else box.pack_start)(button, False, False, 0)
        return button

    def update(self, message=""):
        done = self.step >= len(FEATURES)
        self.back_button.set_sensitive(self.step > 0)
        self.skip_button.set_visible(not done)
        self.next_button.set_visible(not done)
        self.next_button.set_sensitive(self.candidate is not None)
        self.save_button.set_visible(done)
        if done:
            self.title.set_markup("<b>确认</b>")
            lines = []
            for feature, label, _ in FEATURES:
                key = self.keys.get(feature)
                lines.append(f"{label}：{key_text(key) if key else '不使用'}")
            self.body.set_text("\n".join(lines) + "\n\n没问题的话按“保存”（mango 会马上读入）。")
            self.pressed.set_text("")
        else:
            feature, label, default = FEATURES[self.step]
            now = self.current.get(feature)
            self.title.set_markup(f"<b>第 {self.step + 1} / {len(FEATURES)} 步：“{label}”用哪个键？</b>")
            self.body.set_text(
                "请按下要用的键：单个键，或者“修饰键 + 一个键”的组合键（例如 Ctrl + Alt + Z）。"
                "按错了就再按一次，确认后点“下一步”。\n"
                f"Typeless 默认的键：{default}\n"
                f"现在的设置：{key_text(now) if now else '没有'}\n\n"
                "注意：\n"
                "・组合键只能是 Ctrl / Shift / Alt / Super 加上一个键，不能自定义两个普通键的组合（例如 変換 + 空格）。\n"
                "・组合键里的修饰键不分左右（Ctrl + Z 用左右哪个 Ctrl 都算）；单独用修饰键时分左右（例如只用右 Ctrl）。\n"
                "・单独用作一个功能的修饰键，不要再用在别的功能的组合键里（按那个组合键时两个功能都会启动）。\n"
                "・按了没有反应的话，这个键已经被 mango 的其他快捷键占用了，请选别的键。"
            )
            text = key_text(self.candidate) if self.candidate else "（还没有按）"
            self.pressed.set_markup(f"按下的键：<b>{GLib.markup_escape_text(text)}</b>")
        self.message.set_markup(f"<span foreground='#f07a9a'>{GLib.markup_escape_text(message)}</span>")

    def on_key(self, _widget, event):
        if self.step >= len(FEATURES):
            return True
        keysym = Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)) or f"keycode{event.hardware_keycode}"
        if event.is_modifier and keysym not in MODIFIER_KEYS:
            self.update(f"{keysym} 不能用（mango 的快捷键表示不了这个修饰键），请选别的键。")
            return True
        state = event.state
        if state & Gdk.ModifierType.MOD5_MASK:
            self.update("AltGr 等修饰键不能用在组合键里（mango 的快捷键表示不了），请选别的键。")
            return True
        # 按着的修饰键（按下修饰键本身时，GTK 的状态里还没有它自己）
        mods = tuple(name for mask, name in MOD_MASKS if state & mask)
        self.candidate = (event.hardware_keycode, keysym, mods)
        self.update()
        return True

    def on_next(self, *_):
        for feature, label, _ in FEATURES[: self.step]:
            key = self.keys.get(feature)
            if key and (key[0], key[2]) == (self.candidate[0], self.candidate[2]):
                self.update(f"{key_text(self.candidate)} 已经用于“{label}”了，请选别的键。")
                return
        self.keys[FEATURES[self.step][0]] = self.candidate
        self.go(self.step + 1)

    def on_skip(self, *_):
        self.keys.pop(FEATURES[self.step][0], None)
        self.go(self.step + 1)

    def on_back(self, *_):
        self.go(self.step - 1)

    def go(self, step):
        """到第 step 步。回到已经设过的步骤时，显示之前选的键"""
        self.step = step
        self.candidate = self.keys.get(FEATURES[step][0]) if step < len(FEATURES) else None
        self.update()

    def on_save(self, *_):
        write_file(render(self.keys))
        self.saved = True
        self.close()

    def on_destroy(self, *_):
        if not self.saved:
            restore(self.original)
        Gtk.main_quit()


def restore(original):
    if original is None:
        try:
            os.remove(KEYS_FILE)
        except FileNotFoundError:
            pass
    else:
        write_file(original)


def main():
    current, original = read_current()
    # 选键时让现在的键暂时不起作用（mango 会先拿走绑定了的键，窗口收不到）
    write_file("# typeless-keys.py 正在选键（这时 Typeless 的键暂时不起作用）\n")
    time.sleep(RELOAD_WAIT)

    GLib.set_prgname("typeless-keys")  # Wayland 的 app_id（typeless.conf 的窗口规则用）
    window = Setup(current, original)
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ValueError, ImportError):
        signal_add = GLib.unix_signal_add
    # Ctrl+C 等结束时也恢复原来的设置
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_: window.close() or False)
    Gtk.main()
    if window.saved:
        print(f"已保存：{KEYS_FILE}")
    else:
        print("已取消，没有修改", file=sys.stderr)


if __name__ == "__main__":
    main()
