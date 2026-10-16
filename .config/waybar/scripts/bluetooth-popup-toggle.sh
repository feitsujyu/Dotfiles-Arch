#!/bin/bash
# 蓝牙弹窗的开关：waybar 的蓝牙模块的 on-click 调用这个脚本
# 常驻的 bluetooth-popup.py 在运行 → 发信号让它显示 / 隐藏；没在运行 → 启动它并显示
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/bluetooth-popup-${WAYLAND_DISPLAY:-wayland-0}.pid"
pid=$(cat "$PIDFILE" 2>/dev/null)
if [ -n "$pid" ] && grep -q "bluetooth-popup.py" "/proc/$pid/cmdline" 2>/dev/null; then
    kill -USR1 "$pid"
else
    setsid "$HOME/.config/waybar/scripts/bluetooth-popup.py" --show >/dev/null 2>&1 < /dev/null &
fi
