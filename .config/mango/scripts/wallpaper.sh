#!/bin/bash
# 切换壁纸
# 用法：wallpaper.sh next     切到下一张
#       wallpaper.sh prev     切到上一张
#       wallpaper.sh restore  启动壁纸程序，显示上次用的那张（mango 启动时用）
#
# 壁纸目录 ~/Pictures/background 里的 png / jpg 按文件名顺序循环切换；
# 当前用的是哪张记在 ~/.cache/mango-wallpaper 里，重启 mango 后也会保持。
#
# 平时用 wallpaperd（~/.config/mango/wallpaperd/）显示壁纸：它启动时就把所有壁纸准备好，
# next / prev 只是给它发一个信号，几乎没有延迟。
# wallpaperd 没有编译好时，退回到备用的做法（每次重新启动 swaybg，有 0.3 秒左右的延迟）。

WPD="$HOME/.config/mango/wallpaperd/wallpaperd"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/mango-wallpaperd-${WAYLAND_DISPLAY:-wayland-0}.pid"

# 列出“当前这个 mango 会话”（同一个 WAYLAND_DISPLAY）里某个程序的进程
session_pids() {
    for p in $(pgrep -u "$USER" -x "$1"); do
        tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null | grep -qx "WAYLAND_DISPLAY=$WAYLAND_DISPLAY" && echo "$p"
    done
}

daemon_pid() {
    local pid
    pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
    [ -n "$pid" ] && [ "$(cat "/proc/$pid/comm" 2>/dev/null)" = "wallpaperd" ] && echo "$pid"
}

if [ -x "$WPD" ]; then
    case "$1" in
        next | prev)
            pid=$(daemon_pid)
            if [ -z "$pid" ]; then           # 没在运行（比如被关掉了）：先启动
                "$0" restore
                exit 0
            fi
            if [ "$1" = next ]; then kill -USR1 "$pid"; else kill -USR2 "$pid"; fi
            ;;
        *)  # restore
            daemon_pid >/dev/null && exit 0
            old=$(session_pids swaybg)       # 之前用 swaybg 显示时，关掉它
            setsid "$WPD" >/dev/null 2>&1 < /dev/null &
            if [ -n "$old" ]; then
                sleep 1
                kill $old 2>/dev/null
            fi
            ;;
    esac
    exit 0
fi

# ---------- 以下是 wallpaperd 不可用时的备用做法（swaybg） ----------

DIR="$HOME/Pictures/background"
STATE="${WALLPAPER_STATE:-$HOME/.cache/mango-wallpaper}"
mkdir -p "$(dirname "$STATE")"
exec 9>"$STATE.lock"
flock -n 9 || exit 0

mapfile -t LIST < <(find "$DIR" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) | sort)
n=${#LIST[@]}
[ "$n" -eq 0 ] && exit 1
cur=$(cat "$STATE" 2>/dev/null)
idx=-1
for i in "${!LIST[@]}"; do
    [ "${LIST[$i]}" = "$cur" ] && idx=$i
done
case "$1" in
    next) idx=$(( (idx + 1) % n )) ;;
    prev) [ "$idx" -lt 0 ] && idx=0; idx=$(( (idx - 1 + n) % n )) ;;
    *)    [ "$idx" -lt 0 ] && idx=0 ;;
esac
new="${LIST[$idx]}"
old=$(session_pids swaybg)
# 9>&- ：不把锁文件交给 swaybg，否则 swaybg 运行期间锁一直不会释放
swaybg -i "$new" -m fill >/dev/null 2>&1 9>&- &
disown
sleep 0.5
[ -n "$old" ] && kill $old 2>/dev/null
echo "$new" > "$STATE"
