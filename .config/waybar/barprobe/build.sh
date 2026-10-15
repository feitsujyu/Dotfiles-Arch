#!/bin/bash
# barprobe 的编译（turn 46）：只用系统里已有的 gcc / wayland-scanner / wayland-client
set -e
cd "$(dirname "$0")"
mkdir -p build
wayland-scanner client-header protocol/wlr-screencopy-unstable-v1.xml build/screencopy.h
wayland-scanner private-code  protocol/wlr-screencopy-unstable-v1.xml build/screencopy.c
gcc -O2 -Wall -o barprobe barprobe.c build/screencopy.c $(pkg-config --cflags --libs wayland-client)
echo "built: $(pwd)/barprobe"
