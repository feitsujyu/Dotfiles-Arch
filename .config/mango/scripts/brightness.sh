#!/bin/bash
# 屏幕亮度（turn 48）：mango 的亮度键（Fn + F11/F12）调用这个脚本
#
# 用法：brightness.sh up | down | set <百分比>
#   up / down：每次 ±STEP%，最低 MIN%（防止屏幕完全变黑看不见）
#
# /sys/class/backlight/*/brightness 只有 root 可以写，所以通过 systemd-logind 的 SetBrightness 修改
# （logind 允许当前登录的用户改自己屏幕的亮度，不需要 sudo，也不需要安装 brightnessctl 等）
STEP=5
MIN=5

dev=$(ls -d /sys/class/backlight/* 2>/dev/null | head -n 1)
[ -n "$dev" ] || exit 1
max=$(cat "$dev/max_brightness")
cur=$(cat "$dev/brightness")
pct=$(( (cur * 100 + max / 2) / max ))   # 现在的百分比（四舍五入）

case "$1" in
    up)   pct=$(( (pct / STEP + 1) * STEP )) ;;            # 对齐到 STEP 的倍数（例如 47% → 50%）
    down) pct=$(( (pct + STEP - 1) / STEP * STEP - STEP )) ;;  # 47% → 45%
    set)  pct=${2%\%} ;;
    *)    echo "usage: $0 up|down|set <percent>" >&2; exit 2 ;;
esac
[ "$pct" -gt 100 ] && pct=100
[ "$pct" -lt "$MIN" ] && pct=$MIN
value=$(( max * pct / 100 ))

# 登录会话（mango 所在的会话）的 DBus 路径；XDG_SESSION_ID 没有时用 “auto”（调用者所在的会话）
session=/org/freedesktop/login1/session/auto
if [ -n "$XDG_SESSION_ID" ]; then
    s=$(busctl --system call org.freedesktop.login1 /org/freedesktop/login1 \
        org.freedesktop.login1.Manager GetSession s "$XDG_SESSION_ID" 2>/dev/null | awk '{print $2}' | tr -d '"')
    [ -n "$s" ] && session=$s
fi
busctl --system call org.freedesktop.login1 "$session" org.freedesktop.login1.Session \
    SetBrightness ssu backlight "$(basename "$dev")" "$value"
