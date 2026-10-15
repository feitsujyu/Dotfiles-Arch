#!/usr/bin/env python3
# waybar custom 模块：只显示“这块屏幕上当前聚焦的窗口”的标题（mango 专用）
#
# 背景：waybar 的 wlr/taskbar 没有“只显示聚焦窗口”的选项（active-only 不存在，会被忽略），
# 所以改用 mango 自带的 IPC：`mmsg watch monitor <输出名>` 会在该屏幕状态变化时输出一行 JSON，
# 其中 active_client 就是该屏幕上聚焦的窗口。
# 屏幕名由 waybar 通过环境变量 WAYBAR_OUTPUT_NAME 传入（每块屏幕的栏各跑一个本脚本）。

import html
import json
import os
import subprocess
import time

OUTPUT = os.environ.get("WAYBAR_OUTPUT_NAME", "")


def emit(client):
    title = (client or {}).get("title") or ""
    appid = (client or {}).get("appid") or ""
    print(json.dumps({
        "text": html.escape(title),
        "tooltip": html.escape(f"{appid} - {title}" if appid else title),
        "class": "focused" if title else "empty",
    }), flush=True)


def main():
    last = object()
    while True:
        # 没拿到屏幕名时（理论上不会发生），退而显示全局聚焦窗口
        cmd = ["mmsg", "watch", "monitor", OUTPUT] if OUTPUT else ["mmsg", "watch", "focusing-client"]
        try:
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as p:
                for line in p.stdout:
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    client = data.get("active_client") if OUTPUT else data
                    key = json.dumps(client, sort_keys=True)
                    if key != last:  # 状态没变就不重复输出
                        last = key
                        emit(client)
        except FileNotFoundError:
            pass
        # mmsg 退出（例如 mango 重启）后稍等再重连
        time.sleep(1)


if __name__ == "__main__":
    main()
