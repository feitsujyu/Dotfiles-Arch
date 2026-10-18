#!/usr/bin/env python3
# Typeless（语音输入）的快捷键：用自己选的键（可以是组合键）代替右 Alt 的组合键，并且不需要把用户加入 input 组
#
# Typeless 是直接读取键盘设备（/dev/input/event*）来检测快捷键的，通常要把用户加入 input 组
# （这样你运行的所有程序都能读到全部按键）。这里改成：
#   1. 这个程序建一个只给 Typeless 用的虚拟键盘“typeless-trigger”（/dev/uinput）
#   2. mango 的快捷键（typeless-keys.conf，用 typeless-keys.py 生成）按下时，让这个程序在虚拟键盘上“轻按”一下对应的键
#      （Typeless 是轻按一次开始、再轻按一次结束，按住不放反而会取消录音，所以不传实体键的“松开”：
#       组合键先松开哪个键都没关系，也不会出现“松开没传到、一直按着”）
#   3. udev 规则（.config/mango/udev/70-typeless-trigger.rules，要用 sudo 复制到 /etc/udev/rules.d/）
#      只给当前登录的用户读这个虚拟键盘的权限，并且让 mango 不使用它（虚拟的按键只给 Typeless）
# Typeless 那边的快捷键保持默认（RightAlt 等），看到的和直接按右 Alt 完全一样
#
# 用法：
#   typeless-trigger.py serve            常驻（mango 的 exec_once 启动）
#   typeless-trigger.py tap <功能>       实体键按下时（mango 的 bind）
# 功能和对应的键见 ACTIONS

import fcntl
import os
import signal
import socket
import struct
import sys
import time

# linux/input-event-codes.h
KEY_SPACE = 57
KEY_RIGHTSHIFT = 54
KEY_RIGHTALT = 100

# 功能：虚拟键盘上按下的键（按这个顺序按下，反过来的顺序松开）。和 Typeless 的默认快捷键一致
ACTIONS = {
    "dictation": (KEY_RIGHTALT,),                    # 听写（Dictate）：RightAlt
    "ask": (KEY_RIGHTALT, KEY_SPACE),                # Ask Anything：RightAlt + Space
    "translate": (KEY_RIGHTALT, KEY_RIGHTSHIFT),     # 翻译模式：RightAlt + RightShift
}

NAME = b"typeless-trigger"  # 虚拟键盘的名字（udev 规则按这个名字给权限）
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/typeless-trigger-{os.getuid()}"
SOCKET = os.path.join(RUNTIME, "typeless-trigger.sock")
LOCK = os.path.join(RUNTIME, "typeless-trigger.lock")

# linux/uinput.h
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503   # _IOW('U', 3, struct uinput_setup)，结构体 92 字节
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY, SYN_REPORT = 0, 1, 0
BUS_USB = 0x03
# 实体键按住时，mango 会按键盘的重复速度一直发 tap（config.conf 的 repeat_delay = 600 毫秒后，每秒 25 次）。
# 同一个功能的 tap 和上一个 tap 的间隔不到这么久就不理会（比 repeat_delay 长，按住不放也只轻按一次；
# 所以开始和结束之间至少要隔这么久）
IGNORE_REPEAT = 1.0  # 秒
TAP_HOLD = 0.1  # 秒：轻按时按下多久再松开
KEY_GAP = 0.05  # 秒：组合键的各个键之间的间隔（见 emit）


def send(command):
    """tap：把指令发给常驻的程序（没有在运行时什么也不做）"""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(command.encode(), SOCKET)
    except OSError:
        pass


def create_keyboard():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    # 像普通键盘一样登记一整套按键（Typeless 只把“像键盘的设备”当作键盘）
    for code in range(1, 249):
        fcntl.ioctl(fd, UI_SET_KEYBIT, code)
    fcntl.ioctl(fd, UI_DEV_SETUP, struct.pack("HHHH80sI", BUS_USB, 0x1209, 0x7470, 1, NAME, 0))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


def emit(fd, keys, value):
    # 组合键一个一个地按（松开也一样），中间隔 KEY_GAP 秒：同时按下的话 Typeless 只认出第一个键（RightAlt = 听写）
    # struct input_event：timeval（16 字节）+ type, code（各 2 字节）+ value（4 字节）
    for i, key in enumerate(keys):
        if i:
            time.sleep(KEY_GAP)
        os.write(fd, struct.pack("llHHi", 0, 0, EV_KEY, key, value))
        os.write(fd, struct.pack("llHHi", 0, 0, EV_SYN, SYN_REPORT, 0))


def should_tap(last_tap, action, now):
    """按住不放时的重复不理会：和上一个 tap（包括不理会的）的间隔不到 IGNORE_REPEAT 秒时 False"""
    previous = last_tap.get(action)
    last_tap[action] = now
    return previous is None or now - previous >= IGNORE_REPEAT


def serve():
    os.makedirs(RUNTIME, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)  # 已经在运行

    fd = create_keyboard()
    last_tap = {}  # 功能 → 上一次收到 tap 的时间（包括不理会的）

    def quit_(*_):
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        sys.exit(0)

    signal.signal(signal.SIGTERM, quit_)
    signal.signal(signal.SIGINT, quit_)

    try:
        os.unlink(SOCKET)
    except FileNotFoundError:
        pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(SOCKET)
    os.chmod(SOCKET, 0o600)

    while True:
        try:
            verb, _, action = sock.recv(64).decode(errors="replace").partition(" ")
        except InterruptedError:
            continue
        if action not in ACTIONS:
            continue
        if verb == "tap" and should_tap(last_tap, action, time.monotonic()):
            emit(fd, ACTIONS[action], 1)
            time.sleep(TAP_HOLD)
            emit(fd, reversed(ACTIONS[action]), 0)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "serve":
        serve()
    elif len(sys.argv) == 3 and sys.argv[1] == "tap":
        send(f"tap {sys.argv[2]}")
    else:
        print(f"usage: {sys.argv[0]} serve | tap <action>", file=sys.stderr)
        print(f"  actions: {', '.join(ACTIONS)}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
