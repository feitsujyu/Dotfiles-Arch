#!/usr/bin/env python3
# waybar 的网络模块（custom/network）：图标 + 连接速率
#
#   有线：󰈀 2.5G   —— 网口和路由器 / 交换机协商出的速度（/sys/class/net/<网卡>/speed）
#   无线：󰤨 867M   —— 现在的连接速率（NetworkManager 提供，随信号变化），图标的格数表示信号强度
#   未连接：󰤮 Disconnected
#
# 鼠标悬停的提示里显示实时的下载 / 上传速度（每 SPEED_INTERVAL 秒计算一次，
# 用 /sys/class/net/<网卡>/statistics/ 里收发的字节数之差算出）
#
# 一直运行，每次内容变化时输出一行 JSON（waybar 的 return-type: json）：
#   - nmcli monitor 有输出（连上 / 断开 / 换网络）时立刻更新
#   - 另外每 5 秒更新一次（无线的连接速率和信号强度会变化）
#   - 网速每 2 秒更新一次（只读两个文件，几乎没有开销）
# 有线、无线都连着时，显示有线（NetworkManager 默认也优先用有线）。

import json
import select
import signal
import subprocess
import sys
import time

REFRESH = 5         # 秒：重新读取网络状态（nmcli）的间隔
SPEED_INTERVAL = 2  # 秒：计算网速的间隔
WIFI_ICONS = ["󰤯", "󰤟", "󰤢", "󰤥", "󰤨"]  # 信号强度 0～100% 分成 5 级


def nmcli(*args):
    try:
        r = subprocess.run(["nmcli", "-t", *args], capture_output=True, text=True, timeout=3)
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def split(line):
    """nmcli -t 的一行按 : 分开（值里的 : 会写成 \\:）"""
    return [f.replace("\0", ":") for f in line.replace("\\:", "\0").split(":")]


def rate_text(mbps):
    """Mb/s → 2.5G / 10G / 867M"""
    if mbps >= 1000:
        return f"{mbps / 1000:.1f}".rstrip("0").rstrip(".") + "G"
    return f"{mbps}M"


def device_info(dev):
    """IP 地址、网关、连接速率（nmcli 显示的 Mb/s）"""
    info = {}
    for line in nmcli("-f", "IP4.ADDRESS,IP4.GATEWAY,CAPABILITIES.SPEED", "dev", "show", dev).splitlines():
        key, _, value = line.partition(":")
        info.setdefault(key.split("[")[0], value)
    speed = info.get("CAPABILITIES.SPEED", "").split()
    info["mbps"] = int(speed[0]) if speed and speed[0].isdigit() else 0
    return info


def wired_mbps(dev):
    try:
        with open(f"/sys/class/net/{dev}/speed") as f:
            return max(0, int(f.read()))
    except (OSError, ValueError):
        return 0


def traffic(dev):
    """网卡到现在为止收到 / 发出的字节数"""
    try:
        with open(f"/sys/class/net/{dev}/statistics/rx_bytes") as f:
            rx = int(f.read())
        with open(f"/sys/class/net/{dev}/statistics/tx_bytes") as f:
            tx = int(f.read())
        return rx, tx
    except (OSError, ValueError):
        return None


def speed_text(bytes_per_sec):
    """字节/秒 → 0 B/s / 350 KB/s / 1.2 MB/s"""
    value = float(bytes_per_sec)
    for unit in ("B/s", "KB/s", "MB/s"):
        if value < 1024:
            break
        value /= 1024
    else:
        unit = "GB/s"
    return f"{value:.1f} {unit}" if value < 10 and unit != "B/s" else f"{value:.0f} {unit}"


def status():
    """网络的状态：{"text", "tooltip", "class"}，连着网时还有 "dev"（用来计算网速的网卡名）"""
    connected = {}
    for line in nmcli("-f", "DEVICE,TYPE,STATE", "dev").splitlines():
        dev, typ, state = (split(line) + ["", "", ""])[:3]
        if state == "connected":
            connected.setdefault(typ, dev)

    if "ethernet" in connected:
        dev = connected["ethernet"]
        info = device_info(dev)
        mbps = wired_mbps(dev) or info["mbps"]
        text = "󰈀 " + rate_text(mbps) if mbps else "󰈀"
        tooltip = (f"有线：{dev}\nIP：{info.get('IP4.ADDRESS', '')}\n"
                   f"网关：{info.get('IP4.GATEWAY', '')}")
        return {"text": text, "tooltip": tooltip, "class": "ethernet", "dev": dev}

    if "wifi" in connected:
        dev = connected["wifi"]
        info = device_info(dev)
        ssid, signal = "", 0
        for line in nmcli("-f", "IN-USE,SSID,SIGNAL", "dev", "wifi", "list", "ifname", dev,
                          "--rescan", "no").splitlines():
            fields = split(line)
            if fields[0] == "*" and len(fields) >= 3:
                ssid, signal = fields[1], int(fields[2] or 0)
                break
        icon = WIFI_ICONS[min(signal // 20, 4)]
        mbps = info["mbps"]
        text = f"{icon} {rate_text(mbps)}" if mbps else icon
        tooltip = f"{ssid}\n信号：{signal}%\nIP：{info.get('IP4.ADDRESS', '')}"
        return {"text": text, "tooltip": tooltip, "class": "wifi", "dev": dev}

    return {"text": "󰤮 Disconnected", "tooltip": "未连接", "class": "disconnected"}


def main():
    monitor = subprocess.Popen(["nmcli", "monitor"], stdout=subprocess.PIPE, text=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        last = None
        state = status()
        next_status = time.monotonic() + REFRESH
        prev = None  # 上一次的 (网卡名, 时间, 收到的字节数, 发出的字节数)
        while True:
            # 网速：和上一次的字节数相比（刚启动、换了网卡时，要等下一次才算得出来）
            out = {k: v for k, v in state.items() if k != "dev"}
            dev = state.get("dev")
            now = time.monotonic()
            counts = traffic(dev) if dev else None
            if counts:
                if prev and prev[0] == dev and now > prev[1]:
                    down = max(0, counts[0] - prev[2]) / (now - prev[1])
                    up = max(0, counts[1] - prev[3]) / (now - prev[1])
                    out["tooltip"] += f"\n下载：{speed_text(down)}\n上传：{speed_text(up)}"
                else:
                    out["tooltip"] += "\n下载：…\n上传：…"
                prev = (dev, now, *counts)
            else:
                prev = None
            line = json.dumps(out, ensure_ascii=False)
            if line != last:
                print(line, flush=True)
                last = line

            # 等到下一次计算网速的时间（期间网络有变化时提前醒来）
            watch = [monitor.stdout] if monitor.stdout else []
            ready, _, _ = select.select(watch, [], [], SPEED_INTERVAL)
            changed = False
            if ready:
                if monitor.stdout.readline():
                    changed = True
                    # 一次变化会连续输出好几行：等 0.3 秒内的都读完再更新
                    while select.select([monitor.stdout], [], [], 0.3)[0]:
                        if not monitor.stdout.readline():
                            break
                else:  # nmcli monitor 结束了：之后只按时间更新
                    monitor.stdout.close()
                    monitor.stdout = None
            if changed or time.monotonic() >= next_status:
                state = status()
                next_status = time.monotonic() + REFRESH
    finally:
        monitor.terminate()

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(0)
