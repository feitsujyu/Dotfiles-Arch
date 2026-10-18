#!/usr/bin/env python3
# Typeless（语音输入）的三个功能用哪个键：弹出窗口，依次按想用的键，生成 ~/.config/mango/typeless-keys.conf
#
# typeless-keys.conf 是这台电脑自己的设置（键盘不一样），不放进仓库；typeless.conf 用 source_optional 读入。
# 生成的是 mango 的 bindc / bindrc（按下 / 松开），让 typeless-trigger.py 在虚拟键盘上“按”Typeless 的快捷键。
#
#   键用键码（code:数字）记录：和键盘布局无关，就是按下的那个实体键
#   只能用单个键（不能是组合键）。Ctrl / Shift / Alt / Super 这类修饰键也可以（例如右边的 Ctrl），
#   但这个键原来的作用就没有了
#   已经被 mango 的其他快捷键占用的键，按了窗口收不到（mango 先拿走了），要选别的键
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

# 修饰键：松开时 mango 看到的修饰键里还有它自己，所以“松开”的绑定要写上对应的修饰键
MODIFIERS = {
    "Control_L": "CTRL", "Control_R": "CTRL",
    "Shift_L": "SHIFT", "Shift_R": "SHIFT",
    "Alt_L": "ALT", "Alt_R": "ALT", "Meta_L": "ALT", "Meta_R": "ALT",
    "Super_L": "SUPER", "Super_R": "SUPER",
    "Hyper_L": "HYPER", "Hyper_R": "HYPER",
}

# 显示用的键名（没有的显示 keysym 的名字）
DISPLAY_NAMES = {
    "Henkan_Mode": "変換", "Henkan": "変換", "Muhenkan": "無変換", "Hiragana_Katakana": "カタカナひらがな",
    "Control_L": "Left Ctrl", "Control_R": "Right Ctrl",
    "Shift_L": "Left Shift", "Shift_R": "Right Shift",
    "Alt_L": "Left Alt", "Alt_R": "Right Alt",
    "Super_L": "Left Super", "Super_R": "Right Super",
    "Menu": "Menu", "Print": "Print Screen", "Scroll_Lock": "Scroll Lock", "Pause": "Pause",
}


def display_name(keysym):
    return DISPLAY_NAMES.get(keysym, keysym)


def read_current():
    """现在的设置：{功能: (键码, keysym)}，以及文件原来的内容（取消时恢复用）"""
    try:
        with open(KEYS_FILE) as f:
            text = f.read()
    except OSError:
        return {}, None
    current = {}
    for feature, code, keysym in re.findall(r"^# key (\w+) code=(\d+) keysym=(\S+)$", text, re.M):
        current[feature] = (int(code), keysym)
    return current, text


def write_file(text):
    tmp = KEYS_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, KEYS_FILE)


def render(keys):
    """keys：{功能: (键码, keysym)} → typeless-keys.conf 的内容"""
    lines = [
        "# Typeless（语音输入）的三个功能用哪个键：这台电脑自己的设置（不放进仓库）",
        "# 由 ~/.config/mango/scripts/typeless-keys.py 生成，改的时候重新运行它",
        "# 同一个键同时绑定“按下”和“松开”，所以加上 c（允许同一个键有多个绑定）",
    ]
    for feature, label, _ in FEATURES:
        if feature not in keys:
            lines += ["", f"# {label}：不使用"]
            continue
        code, keysym = keys[feature]
        release_mod = MODIFIERS.get(keysym, "NONE")
        lines += [
            "",
            f"# {label}：{display_name(keysym)}",
            f"# key {feature} code={code} keysym={keysym}",
            f"bindc=NONE,code:{code},spawn,{TRIGGER} press {feature}",
            f"bindrc={release_mod},code:{code},spawn,{TRIGGER} release {feature}",
        ]
    return "\n".join(lines) + "\n"


class Setup(Gtk.Window):
    def __init__(self, current, original):
        super().__init__(title="Typeless 的按键设置")
        self.current = current
        self.original = original
        self.keys = {}
        self.step = 0
        self.saved = False

        self.set_default_size(520, 260)
        self.set_border_width(20)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(box)

        self.title = Gtk.Label(xalign=0)
        self.body = Gtk.Label(xalign=0, wrap=True)
        self.message = Gtk.Label(xalign=0, wrap=True)
        for label in (self.title, self.body, self.message):
            box.pack_start(label, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        box.pack_end(buttons, False, False, 0)
        self.back_button = self.button(buttons, "上一步", self.on_back)
        self.skip_button = self.button(buttons, "不使用这个功能", self.on_skip)
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
        self.save_button.set_visible(done)
        if done:
            self.title.set_markup("<b>确认</b>")
            lines = []
            for feature, label, _ in FEATURES:
                key = self.keys.get(feature)
                lines.append(f"{label}：{display_name(key[1]) if key else '不使用'}")
            self.body.set_text("\n".join(lines) + "\n\n没问题的话按“保存”（mango 会马上读入）。")
        else:
            feature, label, default = FEATURES[self.step]
            now = self.current.get(feature)
            self.title.set_markup(f"<b>第 {self.step + 1} / {len(FEATURES)} 步：“{label}”用哪个键？</b>")
            self.body.set_text(
                f"请按一个键（单个键，不是组合键）。\n"
                f"Typeless 默认的键：{default}\n"
                f"现在的设置：{display_name(now[1]) if now else '没有'}\n\n"
                f"按了没有反应的话，这个键已经被 mango 的其他快捷键占用了，请选别的键。"
            )
        self.message.set_markup(f"<span foreground='#f07a9a'>{GLib.markup_escape_text(message)}</span>")

    def on_key(self, _widget, event):
        if self.step >= len(FEATURES):
            return True
        keysym = Gdk.keyval_name(event.keyval) or f"keycode{event.hardware_keycode}"
        code = event.hardware_keycode
        if event.is_modifier and keysym not in MODIFIERS:
            self.update(f"{keysym} 不能用（mango 的快捷键表示不了这个修饰键），请选别的键。")
            return True
        for feature, label, _ in FEATURES[: self.step]:
            if self.keys.get(feature, (None,))[0] == code:
                self.update(f"{display_name(keysym)} 已经用于“{label}”了，请选别的键。")
                return True
        self.keys[FEATURES[self.step][0]] = (code, keysym)
        self.step += 1
        self.update()
        return True

    def on_skip(self, *_):
        self.keys.pop(FEATURES[self.step][0], None)
        self.step += 1
        self.update()

    def on_back(self, *_):
        self.step -= 1
        self.keys.pop(FEATURES[self.step][0], None)
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
