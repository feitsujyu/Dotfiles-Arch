#!/bin/bash
# 编译 wallpaperd（只用系统里已经装好的 gcc / wayland-scanner / wayland-protocols，不需要额外安装）
# 用法：~/.config/mango/wallpaperd/build.sh
set -e
cd "$(dirname "$0")"
mkdir -p build
WP=/usr/share/wayland-protocols
for x in "$WP/staging/fractional-scale/fractional-scale-v1.xml" \
         "$WP/stable/viewporter/viewporter.xml" \
         "protocol/wlr-layer-shell-unstable-v1.xml"; do
    n=$(basename "$x" .xml)
    wayland-scanner client-header "$x" "build/$n-client-protocol.h"
    wayland-scanner private-code  "$x" "build/$n-protocol.c"
done
gcc -O2 -Wall -Wextra -Wno-unused-parameter -Ibuild -o wallpaperd \
    wallpaperd.c build/*-protocol.c $(pkg-config --cflags --libs wayland-client) -lm
echo "built: $(pwd)/wallpaperd"
