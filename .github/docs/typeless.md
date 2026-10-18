# Typeless（语音输入）

[Typeless](https://www.typeless.com/)（AUR 的 `typeless-bin`）在这套桌面（mango + Wayland）上使用时的设置、原理，以及调查时遇到的问题。
安装步骤在 [README 的 “6. Typeless”](../README.md#6-typeless语音输入可选)，这里写“为什么这样做”。

调查时的版本：Typeless 2.2.0（Electron，在 XWayland 下运行）、mango 0.18、wl-clipboard 2.3.0、kitty 0.49.2、Neovim 0.12.6。
Typeless 更新后，可以按最后的 [更新后的检查](#更新后的检查) 看看哪些对策已经不需要了。

## 文件一览

| 文件 | 内容 |
|---|---|
| `.config/mango/typeless.conf` | mango 的设置：开机启动、窗口规则（`config.conf` 用 `source=` 读入） |
| `.config/mango/scripts/typeless-keys.py` | 选键：弹出窗口，依次按三个功能要用的键，生成 `typeless-keys.conf` |
| `~/.config/mango/typeless-keys.conf` | 用哪个键（mango 的 `bindc` / `bindrc`）。每台电脑各自的文件，不放进仓库（`typeless.conf` 用 `source_optional=` 读入） |
| `.config/mango/scripts/typeless-trigger.py` | 只给 Typeless 用的虚拟键盘（常驻），mango 的快捷键通过它“按” Typeless 的快捷键 |
| `.config/mango/udev/70-typeless-trigger.rules` | 只给当前登录的用户读这个虚拟键盘的权限，并让 mango 不使用它 |
| `.config/mango/scripts/typeless-launch.sh` | 启动 Typeless（PATH 的最前面加上 `scripts/typeless/`） |
| `.config/mango/scripts/typeless/wl-copy`, `wl-paste` | wl-clipboard 的替身（见 [问题 3](#3-识别结果粘贴不出来还会卡死)） |
| `.config/mango/scripts/xwayland-workarea.py` | 把 XWayland 的可用区域设置成屏幕去掉 waybar 的部分（常驻） |
| `.config/kitty/typeless.conf` | kitty 里 Ctrl+V 也能粘贴（`kitty.conf` 用 `include` 读入） |
| `.config/nvim/lua/config/typeless.lua` | Neovim 里 Ctrl+V 的处理（`init.lua` 里 `require`） |
| `~/.local/share/applications/typeless.desktop` | rofi 的入口（不在仓库里，`typeless-launch.sh` 自动生成，见 [问题 8](#8-开机启动rofi-的入口)） |

不用 Typeless 的电脑：把 `config.conf` 的 `source=~/.config/mango/typeless.conf`、`kitty.conf` 的 `include typeless.conf`、`init.lua` 的 `require("config.typeless")` 注释掉。

## 原理

### 快捷键

```
自己选的键（typeless-keys.conf）
  → mango 的 bindc / bindrc（按下 / 松开）→ typeless-trigger.py press|release <功能>
  → 常驻的 typeless-trigger.py serve 在虚拟键盘 “typeless-trigger” 上按下 / 松开 RightAlt 等
  → Typeless 读到虚拟键盘的按键（和直接按右 Alt 一样）
```

- Typeless 直接读 `/dev/input/event*` 来检测快捷键，通常要把用户加入 `input` 组。加入的话，用户运行的所有程序都能读到全部按键（包括密码），所以没有这样做。
- udev 规则只给名字是 `typeless-trigger` 的设备加 `uaccess`（当前登录的用户可以读），并设置 `LIBINPUT_IGNORE_DEVICE`（mango 不使用它，虚拟的按键只给 Typeless）。
- Typeless 的键盘程序会独占（EVIOCGRAB）它读的设备，再通过自己的虚拟键盘 “Typeless Keyboard Helper” 把按键送回系统。
- 建虚拟键盘要用 `/dev/uinput`：这个权限是 `typeless-bin` 包自带的 udev 规则（`/usr/lib/udev/rules.d/70-typeless-uinput.rules`，`TAG+="uaccess"`）给的，所以要先装 `typeless-bin`、重新登录后才能用。
- 用法：**轻按一次开始说话，说完再轻按一次结束**（结束时按三个键中的哪一个都可以，模式不会变）。

### 输入识别结果

```
Typeless：原来的剪贴板 wl-paste 读出来 → 识别结果 wl-copy 放进剪贴板 → 用虚拟键盘按 Ctrl+V
         → 大约 0.5 秒后恢复原来的剪贴板
```

`wl-copy` / `wl-paste` 是 PATH 里的替身（`typeless-launch.sh` 设置的 PATH），替身再交给 `/usr/bin/` 里真正的命令。

### 窗口

| 窗口 | app_id / 标题 | 说明 |
|---|---|---|
| 浮动条 | `Typeless-floating-bar` / `Status` | 一直存在的透明窗口，录音 / 处理时显示进度。不接受键盘焦点；空白的地方鼠标会“穿过去”（Typeless 自己每 0.1 秒检查鼠标的位置） |
| 回答卡片 | `Typeless` / `Status` → `AI result` | Ask Anything 的回答等。每次开始录音时 Typeless 会关掉它，下次的回答总是新的窗口 |
| 主窗口 | `Typeless` / `Typeless` | 设置画面。普通窗口 |

## 遇到的问题

### 1. 快捷键：日语键盘没有右 Alt，设置画面也改不了快捷键

- **现象**：Typeless 的默认快捷键是 RightAlt 系列，日语键盘没有右 Alt。设置画面里改快捷键的输入框按什么键都没有反应。
- **原因**：输入框也是靠 Typeless 读 `/dev/input` 来收按键的，用户不在 `input` 组时什么都收不到。
- **对策**：Typeless 的快捷键保持默认，用虚拟键盘（`typeless-trigger.py`）把自己选的键转成 RightAlt 系列。
- 键不写死：有的日语键盘也没有 変換 / 無変換，换成标准布局的键盘也一样，所以用 `typeless-keys.py` 选键，写到每台电脑各自的 `typeless-keys.conf`。
  - 键用键码（`code:数字`）记录：和键盘布局无关，就是按下的那个实体键。
  - 选键时先让 `typeless-keys.conf` 暂时变空：已经绑定的键会被 mango 先拿走，窗口收不到。取消时恢复原来的内容。
  - Right Ctrl 这类修饰键也可以用。实测（虚拟键盘按 Right Ctrl / Shift / Alt）：**按下**时 mango 看到的修饰键里没有它自己（匹配 `NONE`），
    **松开**时有（匹配 `CTRL` 等），所以修饰键的 `bindrc` 要写上对应的修饰键（`typeless-keys.py` 自动处理）。
    mango 的快捷键表示不了的修饰键（AltGr 等 `ISO_Level3_Shift`）不能选。
  - 已经被 mango 的其他快捷键占用的键选不了（按了窗口收不到）。
- mango 里同一个键同时绑定“按下”（`bind`）和“松开”（`bindr`）会被当作冲突，两个都要加 `c`（`bindc` / `bindrc`）。
- 实体键按住时 mango 会按键盘的重复速度一直发 press。晚到的 press 可能排在 release 后面，变成“松开后又按下”，所以松开后 0.2 秒内的 press 不理会（`IGNORE_PRESS_AFTER_RELEASE`）。

### 2. Ask Anything、翻译都变成了普通听写

- **现象**：三个键按哪个，结果都是普通的听写（Typeless 的历史记录里 `mode` 都是 `voice_transcript`）。偶尔会成功。
- **原因**：虚拟键盘把组合键的两个键（RightAlt + Space 等）在**同一瞬间**按下时，Typeless 有时只认出第一个键 RightAlt（= 听写）。真人按键时总有时间差，所以 Typeless 平时不会遇到。
- **对策**：组合键的各个键一个一个地按（松开也一样），中间隔 0.05 秒（`typeless-trigger.py` 的 `KEY_GAP`）。

### 3. 识别结果粘贴不出来，还会卡死

- **现象**：录音、处理都正常，但文字不出现。有时接着 Typeless 卡死：鼠标变成 I 形、画面点不了、关不掉（Alt+Q、托盘的退出都没用）。
- **原因**：Typeless 启动 `wl-copy` 时把标准输出 / 标准错误关掉了。wl-clipboard 2.3.0 起遇到这种情况会
  “launched with a closed standard file descriptor … Aborting.” 直接退出，识别结果放不进剪贴板。
  Typeless 接着改用 XWayland 的剪贴板，而读剪贴板的 `wl-paste` 向剪贴板的主人（Typeless 自己）要内容，Typeless 却在等 `wl-paste` 结束 → 互相等待，卡死。
- **对策**：`scripts/typeless/` 里的替身把关掉的 0 / 1 / 2 号接到 `/dev/null`，再交给真正的命令。
  `wl-paste` 的替身另外超过 2 秒就放弃（以防万一又互相等待）。
  替身只对通过 `typeless-launch.sh` 启动的 Typeless 有效，所以 mango 的开机启动和 rofi 的入口都通过它启动。
- 不推荐的做法：把 wl-clipboard 降级到没有这个检查的版本（整个系统都受影响，每次更新都要跳过它）。
- 卡死时的恢复：`wl-copy --clear` 后 `pkill -x wl-paste`，或者 `pkill -KILL -x typeless`。
- 调查时一度以为是透明的浮动条挡住了鼠标点击，**不是**（把浮动条移开也一样卡死）。

### 4. kitty 里粘贴不出来

- **原因**：Typeless 一律按 Ctrl+V（Linux 上没有按程序切换粘贴键的设置），kitty 的粘贴是 Ctrl+Shift+V。
- **对策**（`.config/kitty/typeless.conf`）：Ctrl+V 也粘贴；但窗口里在运行 Neovim 时（Neovim 用 kitty 的用户变量 `in_editor` 告诉 kitty），Ctrl+V 原样交给 Neovim。
- 副作用：shell 里 Ctrl+V（bash 的“照原样输入下一个字”）用不了；ssh 到别的电脑上运行的 Vim / Neovim 识别不到（Ctrl+V 会由 kitty 粘贴）。
- 不能在替身里改按别的键：替身知道当前窗口，但拦不住 Typeless 自己按的 Ctrl+V，另外再按一次会粘贴两次。
- Typeless 还带有“语音输入法”的方式（不经过剪贴板），但只附带了 IBus 版（fcitx5 版的 `.so` 没有附带），用不了。

### 5. Neovim 里的 Ctrl+V

`.config/nvim/lua/config/typeless.lua`：

- 插入模式、命令行：Ctrl+V 改成粘贴剪贴板（`<C-r><C-o>+`，原样插入）。原来的“照原样输入下一个字”用 Ctrl+Q。
- 普通 / 可视模式：Ctrl+V 照常是矩形选择，但 **Typeless 刚放进剪贴板（1 秒以内）时收到的 Ctrl+V 丢掉**（这时的语音输入基本是误操作，不切换成矩形选择）。
  “刚放进剪贴板”的判断：`wl-copy` 的替身每次更新 `$XDG_RUNTIME_DIR/typeless-clipboard-time` 的时间。
- 在 kitty 里：启动 / 恢复时设置 kitty 的用户变量 `in_editor`，退出 / Ctrl+Z 时取消。

### 6. 浮动条、回答卡片被 waybar 挡住

- **原因**：Typeless 按“可用区域”的最下面放浮动条和回答卡片（卡片在内容变化、改大小时每次都重新这样放）。
  X11 程序从 XWayland 的 `_NET_WORKAREA` 知道可用区域，但 mango 不设置它，所以 Typeless 以为整个屏幕都能用。
  mango 会照办 XWayland 浮动窗口自己请求的位置，所以只靠窗口规则（只在窗口出现时生效）挡不住。
- **对策**：`xwayland-workarea.py`（常驻）设置 `_NET_WORKAREA`。屏幕插拔、开关时重新设置（`mmsg watch all-monitors`）；XWayland 没有 X11 程序时会退出、值会消失，所以每 5 秒检查一次。XWayland 没在运行时不去连接它（连接会让 mango 启动 XWayland）。
- 限制：Chromium / Electron 只对 XWayland 的**主屏幕**使用这个值（其他屏幕当作整块都能用），所以设置成主屏幕的可用区域。接外接显示器、Typeless 显示在主屏幕以外时还是可能被挡住。
- 浮动条另外有 `offset_y:100` 的窗口规则，是刚登录时的保险（Typeless 可能在可用区域设置好之前就放好了浮动条）。

### 7. 工作区

- 浮动条：`is_unmanaged_global:1`，切换工作区时跟着移过去。
  不用 `is_global`：`is_global` 的窗口在切换工作区时会抢走焦点（mango 把焦点给“最近得到过焦点、在新工作区能看到”的窗口）。`is_unmanaged_global` 的窗口不参加这种选择，用鼠标点还是可以的。
- 回答卡片：不加规则。出现在当时所在的工作区，之后留在那里。
  （试过给它加 `is_global`：每次切换工作区焦点都跑到卡片上。）
- 浮动条去掉边框（`no_border:1`），否则透明的窗口会画出一个空的框。
- 窗口规则只在窗口出现时生效，改了浮动条的规则后要重新启动 Typeless。

### 8. 开机启动、rofi 的入口

- Typeless 自己的“开机启动”写在 `~/.config/autostart/`，mango 不读那里，所以在 `typeless.conf` 的 `exec_once` 启动（参数和 Typeless 自己写的一样）。
- rofi 里启动的 Typeless 也要经过 `typeless-launch.sh`（否则没有替身，又会粘贴不出来、卡死），
  所以用 `~/.local/share/applications/typeless.desktop`（`Exec=` 换成这个脚本的系统 `typeless.desktop`）盖过系统的入口。
- **Typeless 每次启动时都会删掉 `~/.local/share/applications/typeless.desktop`**（只要 `/usr/share/applications/typeless.desktop` 存在；这是它设置 deep link 时的做法），
  所以手动建的入口在 Typeless 下一次启动时就没了。`typeless-launch.sh` 在 Typeless 启动 10 秒后重新写一次。
  （Typeless 不是通过这个脚本启动的话，入口就会被删掉、不会恢复；重新登录 mango 后会恢复。）
- 退出 Typeless 后偶尔会留下一个进程，要用 `kill`（SIGTERM）结束。
- 用命令重新启动 Typeless 时，主窗口有时会自己打开（关掉就缩回托盘）。

## 调查的方法

- **Typeless 的历史记录**：`~/.config/Typeless/typeless.db`（SQLite）的 `history_v2` 表，`mode` 是 `voice_transcript`（听写）/ `voice_command`（Ask Anything）/ `voice_translation`（翻译）。
  只读地打开：`sqlite3 -readonly "file:$HOME/.config/Typeless/typeless.db?mode=ro" "select created_at, mode, status from history_v2 order by created_at desc limit 5;"`
- **不说话也能测的方法**：轻按一下开始、再轻按一下结束，看历史记录里的 `mode`（`typeless-trigger.py press ask` → `release ask` 这样从命令行发也可以）。
  按住不放的话 Typeless 会取消录音、显示快捷键一览（Typeless 的规定），测不了。
  注意：麦克风会录到房间里的声音，可能会生成真正的回答。
- **Typeless 的程序**：`/opt/Typeless/resources/app.asar`（asar 格式，Python 几行就能解开）。
  JavaScript 是混淆过的；字符串可以用 Typeless 自带的 Electron 还原（`ELECTRON_RUN_AS_NODE=1 /opt/Typeless/typeless 脚本.js`，不用另外装 node）。
  快捷键的处理、录音的状态机在 `dist/renderer/static/js/` 里，窗口的位置在 `dist/main/` 里。
- **Electron 看到的屏幕 / 可用区域**：把 Typeless 的文件夹复制到临时的地方，`resources/` 里放一个自己写的 `app.asar`（打印 `screen.getAllDisplays()`），用 `--ozone-platform=x11` 运行。
- 测试时强制关掉 Neovim 的话会留下交换文件，下次启动停在交换文件的提示上（这时 Neovim 还没告诉 kitty “在运行 Neovim”，kitty 会把文字直接粘贴进去，看起来像是 Ctrl+V 的设置有问题）。

## 更新后的检查

Typeless（或 wl-clipboard、mango）更新后，下面的对策可能就不需要了：

| 对策 | 检查方法 | 不需要时 |
|---|---|---|
| 虚拟键盘（问题 1） | Typeless 不用 `input` 组也能检测快捷键（例如支持 Wayland 的全局快捷键、XDG portal）；或者设置画面能收到按键 | 删掉 `typeless.conf` 的 `source_optional=…typeless-keys.conf` 和 `typeless-trigger.py serve`，`typeless-keys.py`，udev 规则 |
| 组合键的间隔（问题 2） | `KEY_GAP = 0` 时 Ask Anything 的历史记录是 `voice_command` | 留着也没有坏处 |
| wl-clipboard 的替身（问题 3） | `sh -c 'echo test \| /usr/bin/wl-copy >&- 2>&-'; /usr/bin/wl-paste` 能读出 test（wl-clipboard 2.3.0 时 wl-copy 会退出，退出码 134）；或者 Typeless 不再关掉输出 | 删掉 `typeless-launch.sh` 和 `scripts/typeless/`，开机启动和 `.desktop` 直接启动 `/opt/Typeless/typeless`。Neovim 的“丢掉 Ctrl+V”用到 `wl-copy` 替身记录的时间，要一起改 |
| kitty / Neovim 的 Ctrl+V（问题 4、5） | Typeless 支持终端的粘贴键（Ctrl+Shift+V），或者用输入法的方式输入（fcitx5 版） | 删掉 `kitty/typeless.conf`、`nvim/lua/config/typeless.lua` |
| 可用区域（问题 6） | mango 自己设置 `_NET_WORKAREA`（`DISPLAY=:0 xprop -root _NET_WORKAREA`，先停掉 `xwayland-workarea.py`）；或者 Typeless 改成 Wayland 程序 | 删掉 `xwayland-workarea.py` 和它的 `exec_once` |
| rofi 的入口（问题 8） | Typeless 启动后 `~/.local/share/applications/typeless.desktop` 还在（先停掉 `typeless-launch.sh` 里重新写的部分） | 删掉 `typeless-launch.sh` 里重新写入口的部分，改成手动建一次 |
| 窗口规则（问题 7） | 窗口的 app_id / 标题变了的话规则就不起作用：`mmsg get all-clients` 看 app_id 和标题 | 改 `typeless.conf` 的 `window_rule` |
