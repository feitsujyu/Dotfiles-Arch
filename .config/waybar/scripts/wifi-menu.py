#!/usr/bin/env python3
# Wi-Fi 选择菜单：点击 waybar 的 Wi-Fi 模块时弹出
#
# 用到的都是已经装好的程序：
#   nmcli（NetworkManager 自带）  扫描 / 连接 / 断开 / 开关 Wi-Fi
#   rofi 显示列表、输入密码、显示提示
#
# 操作：
#   选择网络       → 已保存过的直接连接；新的加密网络会弹出密码框（输入内容显示为 *）
#   选择当前网络   → 可以断开连接
#   列表最后的项目 → 重新扫描 / 关闭（开启）Wi-Fi
#   菜单打开时再点一次 Wi-Fi 模块 → 关闭菜单
#
# 密码不会出现在命令行参数里（其他程序看不到），而是通过标准输入交给 `nmcli connection edit` 保存。

import os
import signal
import subprocess
import sys
import time

# 弹出位置：屏幕右下角、waybar（高 40px）的上方，靠近 Wi-Fi 模块
ROFI_THEME = (
    "window { location: south east; anchor: south east; "
    "x-offset: -255px; y-offset: -48px; width: 420px; } "
    "listview { lines: 8; } "
    "element-icon { size: 0px; } "
)
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-wifi-menu.pid")

SIGNAL_ICONS = ["󰤟", "󰤢", "󰤥", "󰤨"]  # 弱 → 强
LOCK = "󰌾"
CHECK = "󰄬"
RESCAN = "󰑐  重新扫描"
WIFI_OFF = "󰤮  关闭 Wi-Fi"
WIFI_ON = "󰤨  开启 Wi-Fi"
DISCONNECT = "󰖪  断开连接"
BACK = "  返回"


def nmcli(*args, input_text=None, check=False):
    r = subprocess.run(["nmcli", *args], input=input_text, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r


def split_escaped(line):
    """nmcli -t -e yes 的输出：字段用 “:” 分隔，字段里的 “:” 和 “\\” 前面会加 “\\”"""
    fields, cur, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if c == ":":
            fields.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    fields.append(cur)
    return fields


def rofi(prompt, entries=None, password=False, message=None):
    cmd = ["rofi", "-dmenu", "-i", "-p", prompt, "-theme-str", ROFI_THEME,
           "-no-custom" if entries is not None else "-l", *([] if entries is not None else ["0"])]
    if password:
        # 输入内容显示为 *，输入框的提示文字改成“密码”（默认是主题里的“搜索…”）
        cmd += ["-password", "-theme-str", 'entry { placeholder: "密码"; }']
    if message:
        cmd += ["-mesg", message]
    r = subprocess.run(cmd, input="\n".join(entries or []), capture_output=True, text=True)
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def show_message(text):
    subprocess.run(["rofi", "-e", text, "-theme-str", ROFI_THEME])


def busy(text):
    """连接需要几秒钟，先显示一个提示，完成后关掉"""
    return subprocess.Popen(["rofi", "-e", text, "-theme-str", ROFI_THEME],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wifi_device():
    for line in nmcli("-t", "-f", "DEVICE,TYPE", "device").stdout.splitlines():
        dev, typ = split_escaped(line)[:2]
        if typ == "wifi":
            return dev
    return None


def scan():
    """返回 [(in_use, signal, security, ssid)]，同名网络只保留信号最强的一个"""
    out = nmcli("-t", "-e", "yes", "-f", "IN-USE,SIGNAL,SECURITY,SSID",
                "device", "wifi", "list", "--rescan", "no").stdout
    best = {}
    for line in out.splitlines():
        in_use, sig, sec, ssid = (split_escaped(line) + ["", "", "", ""])[:4]
        if not ssid:  # 隐藏网络
            continue
        sig = int(sig or 0)
        item = (in_use == "*", sig, sec if sec not in ("", "--") else "", ssid)
        old = best.get(ssid)
        if old is None or item[0] > old[0] or (item[0] == old[0] and sig > old[1]):
            best[ssid] = item
    return sorted(best.values(), key=lambda x: (not x[0], -x[1], x[3].lower()))


def saved_profile(ssid):
    """已保存的 Wi-Fi 配置里，SSID 相同的那一个的名字"""
    for line in nmcli("-t", "-f", "NAME,TYPE", "connection", "show").stdout.splitlines():
        f = split_escaped(line)
        if len(f) >= 2 and f[1] == "802-11-wireless":
            if nmcli("-g", "802-11-wireless.ssid", "connection", "show", "id", f[0]).stdout.strip() == ssid:
                return f[0]
    return None


def set_password(profile, password):
    # 通过标准输入传给 nmcli 的编辑模式，密码不会出现在命令行参数里
    nmcli("connection", "edit", "id", profile,
          input_text=f"set 802-11-wireless-security.psk {password}\nsave\nquit\n")


def activate(profile, ssid):
    p = busy(f"正在连接 {ssid} …")
    try:
        r = nmcli("--wait", "30", "connection", "up", "id", profile)
    finally:
        p.terminate()
    return r


def connect(ssid, security, dev):
    profile = saved_profile(ssid)
    if profile:  # 已保存过：直接连接
        r = activate(profile, ssid)
        if r.returncode == 0:
            return
        if not security:
            show_message(f"连接 {ssid} 失败：\n{r.stderr.strip()}")
            return
        # 可能是密码改了：让用户重新输入
        pw = rofi(f"{ssid} 的密码", password=True, message="连接失败，请重新输入密码（Esc 取消）")
        if not pw:
            return
        set_password(profile, pw)
        r = activate(profile, ssid)
        if r.returncode != 0:
            show_message(f"连接 {ssid} 失败：\n{r.stderr.strip()}")
        return

    if "802.1X" in security:
        show_message(f"{ssid} 是企业认证（802.1X）网络，\n请在终端里用 nmtui 连接（右键 Wi-Fi 模块可以打开）。")
        return

    # 新网络：先建立配置，再设置密码，最后连接；失败时删掉这个配置
    args = ["connection", "add", "type", "wifi", "con-name", ssid, "ssid", ssid]
    if dev:
        args += ["ifname", dev]
    if security:
        if "WEP" in security:
            show_message(f"{ssid} 使用的是不安全的 WEP 加密，\n请在终端里用 nmtui 连接。")
            return
        pw = rofi(f"{ssid} 的密码", password=True, message="输入密码后按 Enter（Esc 取消）")
        if not pw:
            return
        key_mgmt = "sae" if ("WPA3" in security and "WPA2" not in security and "WPA1" not in security) else "wpa-psk"
        args += ["wifi-sec.key-mgmt", key_mgmt]
    r = nmcli(*args)
    if r.returncode != 0:
        show_message(f"无法建立 {ssid} 的连接配置：\n{r.stderr.strip()}")
        return
    if security:
        set_password(ssid, pw)
    r = activate(ssid, ssid)
    if r.returncode != 0:
        nmcli("connection", "delete", "id", ssid)
        show_message(f"连接 {ssid} 失败（密码错误或信号太弱）：\n{r.stderr.strip()}")


def main_menu():
    dev = wifi_device()
    if dev is None:
        show_message("没有找到 Wi-Fi 网卡")
        return
    if nmcli("radio", "wifi").stdout.strip() != "enabled":
        if rofi("Wi-Fi", [WIFI_ON]) == WIFI_ON:
            nmcli("radio", "wifi", "on")
        return

    # 后台刷新扫描结果，下次打开菜单时就是最新的列表
    subprocess.Popen(["nmcli", "device", "wifi", "rescan"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    nets = scan()
    entries, index = [], {}
    for in_use, sig, sec, ssid in nets:
        icon = SIGNAL_ICONS[min(3, sig // 25)]
        mark = f"  {CHECK} 已连接" if in_use else ""
        lock = f" {LOCK}" if sec else ""
        label = f"{icon}{lock}  {ssid}{mark}"
        entries.append(label)
        index[label] = (in_use, sec, ssid)
    entries += [RESCAN, WIFI_OFF]  # 操作项放在列表最后，默认选中的是网络（已连接的在最上面）

    choice = rofi("Wi-Fi", entries)
    if choice is None:
        return
    if choice == RESCAN:
        p = busy("正在扫描 …")
        nmcli("--wait", "15", "device", "wifi", "rescan")
        time.sleep(2)
        p.terminate()
        return main_menu()
    if choice == WIFI_OFF:
        nmcli("radio", "wifi", "off")
        return
    if choice in index:
        in_use, sec, ssid = index[choice]
        if in_use:
            if rofi(ssid, [DISCONNECT, BACK]) == DISCONNECT:
                nmcli("device", "disconnect", dev)
            return
        connect(ssid, sec, dev)


def main():
    # 被下一次点击关掉（SIGTERM）时，也要正常结束，删掉 PID 文件
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    # 菜单已经打开时再点一次：关闭菜单（和 Windows 一样）
    try:
        old = int(open(PIDFILE).read())
        cmdline = open(f"/proc/{old}/cmdline").read()  # 确认真的是这个脚本（防止 PID 被别的程序重复使用）
        if old != os.getpid() and "wifi-menu.py" in cmdline:
            subprocess.run(["pkill", "-x", "-P", str(old), "rofi"])
            os.kill(old, signal.SIGTERM)
            return
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    try:
        main_menu()
    finally:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
