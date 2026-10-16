#!/bin/bash
# 蓝牙的开 / 关：waybar 的蓝牙模块的 on-click-right 调用这个脚本
# bluetoothctl 来自 bluez-utils。被 rfkill 禁用（soft blocked）时 power on 会失败，先解除
if bluetoothctl show 2>/dev/null | grep -q 'Powered: yes'; then
    bluetoothctl power off
else
    rfkill list bluetooth 2>/dev/null | grep -q 'Soft blocked: yes' && rfkill unblock bluetooth && sleep 0.5
    bluetoothctl power on
fi >/dev/null 2>&1
