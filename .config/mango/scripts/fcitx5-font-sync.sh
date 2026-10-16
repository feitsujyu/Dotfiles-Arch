#!/bin/bash
# fcitx5 输入框的字体大小 ← kitty 的字体大小
#
# 用法：fcitx5-font-sync.sh          同步一次
#       fcitx5-font-sync.sh --watch  同步一次，然后监视 kitty.conf，改了之后自动再同步（mango 的 exec_once 用）
#
# 做法：读 ~/.config/kitty/kitty.conf 的 font_size，改写 ~/.config/fcitx5/conf/classicui.conf 的
#       Font= / MenuFont=，然后通过 DBus 让 fcitx5 重新加载经典界面（不用重启 fcitx5）
# 监视用的 inotifywait 来自 inotify-tools（已经安装）
FAMILY="Noto Sans CJK SC"
KITTY_CONF="$HOME/.config/kitty/kitty.conf"
CLASSICUI="$HOME/.config/fcitx5/conf/classicui.conf"

sync_once() {
    # 最后一个有效的 font_size（注释掉的行不算）；小数 13.0 → 13
    local size
    size=$(awk '$1 == "font_size" { s = $2 } END { print s }' "$KITTY_CONF" 2>/dev/null)
    [ -n "$size" ] || return
    size=$(printf '%g' "$size")
    local font="\"$FAMILY $size\""
    [ -f "$CLASSICUI" ] || return
    if grep -qx "Font=$font" "$CLASSICUI" && grep -qx "MenuFont=$font" "$CLASSICUI"; then
        return  # 已经一样
    fi
    sed -i -e "s|^Font=.*|Font=$font|" -e "s|^MenuFont=.*|MenuFont=$font|" "$CLASSICUI"
    grep -q '^Font=' "$CLASSICUI" || echo "Font=$font" >> "$CLASSICUI"
    grep -q '^MenuFont=' "$CLASSICUI" || echo "MenuFont=$font" >> "$CLASSICUI"
    dbus-send --session --type=method_call --dest=org.fcitx.Fcitx5 /controller \
        org.fcitx.Fcitx.Controller1.ReloadAddonConfig string:classicui 2>/dev/null
}

sync_once
if [ "$1" = "--watch" ]; then
    # 已经有一个在监视时不再启动（重复执行 exec_once 等）
    exec 9> "${XDG_RUNTIME_DIR:-/tmp}/fcitx5-font-sync.lock"
    flock -n 9 || exit 0
    # 编辑器保存时常常是“写到新文件再改名”，所以监视目录，而不是 kitty.conf 本身
    inotifywait -m -q -e close_write,moved_to,create --format '%f' "$(dirname "$KITTY_CONF")" 2>/dev/null |
    while read -r name; do
        [ "$name" = "$(basename "$KITTY_CONF")" ] && sync_once
    done
fi
