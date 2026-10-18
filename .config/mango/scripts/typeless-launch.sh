#!/bin/bash
# 启动 Typeless（rofi 的 “Typeless” 和 mango 的 exec_once 都通过这个脚本启动）
#   PATH 的最前面加上 scripts/typeless/：Typeless 用的 wl-copy / wl-paste 换成替身
#   （Typeless 启动它们的方式会让 wl-clipboard 直接退出，见 typeless/wl-copy、typeless/wl-paste）
#   参数原样传给 Typeless
#
# rofi 的入口：~/.local/share/applications/typeless.desktop（系统的 typeless.desktop 的 Exec= 换成这个脚本）
#   Typeless 每次启动时都会删掉这个文件（它设置 deep link 时的做法），所以启动后过一会儿重新写一次
SYSTEM_DESKTOP=/usr/share/applications/typeless.desktop
USER_DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/typeless.desktop"
DESKTOP_DELAY=10  # 秒：Typeless 启动、删掉文件之后再写

write_desktop() {
    [ -f "$SYSTEM_DESKTOP" ] || return
    mkdir -p "$(dirname "$USER_DESKTOP")"
    sed "s|^Exec=.*|Exec=$HOME/.config/mango/scripts/typeless-launch.sh %U|" "$SYSTEM_DESKTOP" > "$USER_DESKTOP.tmp" &&
        mv "$USER_DESKTOP.tmp" "$USER_DESKTOP"
}
(sleep "$DESKTOP_DELAY"; write_desktop) </dev/null >/dev/null 2>&1 &

export PATH="$HOME/.config/mango/scripts/typeless:$PATH"
exec /opt/Typeless/typeless "$@"
