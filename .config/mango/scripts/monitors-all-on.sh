#!/bin/bash
# 打开所有屏幕（Super + Shift + P）
#   waybar 设置弹窗里关掉的屏幕全部重新打开：万一全部屏幕都关掉了（黑屏），用键盘恢复
#   不经过设置弹窗，弹窗出了问题时也能用
#
# 1. 去掉 local.conf 里的 disable:1（mango 发现文件变了会重新加载，按 monitor_rule 打开、排好位置）
# 2. 这样还是关着的屏幕（local.conf 读不了等情况），直接让 mango 打开
#    （已经开着的屏幕不要再 enable_monitor：mango 会把它重新自动排位置）
LOCAL=~/.config/mango/local.conf

if [ -f "$LOCAL" ] && grep -q ',disable:1' "$LOCAL"; then
    sed -i 's/,disable:1//' "$LOCAL"
    sleep 1
fi

# 关着的屏幕：mmsg 里还在，但宽高是 0
mmsg get all-monitors | python3 -c '
import json, sys
for m in json.load(sys.stdin)["monitors"]:
    if m["width"] == 0 or m["height"] == 0:
        print(m["name"])
' | while read -r name; do
    mmsg dispatch "enable_monitor,$name" >/dev/null
done
