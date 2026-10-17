# dotfiles

Arch Linux + [mango](https://github.com/mangowm/mango)（Wayland 合成器）的桌面配置。配色统一为 Lilac（淡紫色）。

| 程序 | 文件 | 内容 |
|---|---|---|
| mango | `.config/mango/config.conf` | 快捷键、动画、窗口规则、开机启动 |
| | `.config/mango/local.conf.example` | 每台电脑自己的设置（`local.conf`，不放进仓库）的说明 |
| | `.config/mango/scripts/` | 壁纸切换、亮度调节、fcitx5 字体跟随 kitty |
| | `.config/mango/wallpaperd/` | 预先准备好壁纸、切换时不卡顿的壁纸程序（C，需要编译） |
| waybar | `.config/waybar/config.jsonc`, `style.css` | 底部状态栏 |
| | `.config/waybar/scripts/` | Wi-Fi / 蓝牙 / 音量 / 亮度 / 设置弹窗（Python + GTK3 layer shell） |
| | `.config/waybar/barprobe/` | 找出状态栏模块位置、让弹窗对齐的小程序（C，需要编译） |
| kitty | `.config/kitty/` | 终端 |
| rofi | `.config/rofi/` | 程序启动器（Lilac 主题） |
| fcitx5 | `.config/fcitx5/` | 输入法设置（经典界面使用 Lilac 主题） |
| | `.local/share/fcitx5/themes/lilac/` | 输入法候选框主题 |
| | `.local/share/fcitx5/inputmethod/tiger.conf` | 虎码输入法设置 |
| | `.local/share/fcitx5/addon/repeatlast.conf`, `lua/repeatlast/` | `;` + 空格 重复上一次输入（fcitx5-lua） |
| bash | `.bashrc` | 包括 `dotfiles` 命令 |

## 在新电脑上恢复

```bash
git clone --bare https://github.com/feitsujyu/Dotfiles-Arch.git "$HOME/.dotfiles"
alias dotfiles='git --git-dir=$HOME/.dotfiles --work-tree=$HOME'
dotfiles config status.showUntrackedFiles no
dotfiles checkout
# 让 dotfiles status 能显示和 GitHub 相比新 / 旧几个提交（bare 克隆默认不设置）
dotfiles config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
dotfiles fetch
dotfiles branch -u origin/main main
```

如果 `checkout` 因为已有同名文件（例如系统自带的 `~/.bashrc`）报错，先把它们移走再执行一次：

```bash
mkdir -p ~/.dotfiles-backup
dotfiles checkout 2>&1 | grep -E '^\s+' | awk '{print $1}' | while read -r f; do
    mkdir -p ~/.dotfiles-backup/"$(dirname "$f")"
    mv ~/"$f" ~/.dotfiles-backup/"$f"
done
dotfiles checkout
```

### 1. 安装程序

```bash
# 桌面（mangowm-git 在 AUR）
mangowm-git waybar kitty rofi
# 弹窗脚本
python-gobject gtk3 gtk-layer-shell
# 网络 / 蓝牙 / 声音 / 电源
networkmanager bluez bluez-utils pipewire pipewire-pulse wireplumber upower power-profiles-daemon
# 输入法
fcitx5 fcitx5-chinese-addons fcitx5-gtk fcitx5-qt fcitx5-configtool fcitx5-lua inotify-tools
# 字体
ttf-jetbrains-mono-nerd noto-fonts noto-fonts-cjk noto-fonts-emoji
# 编译 wallpaperd / barprobe
base-devel wayland wayland-protocols
# 可选（不是必需的）：只在 wallpaperd 还没编译或编译失败时，wallpaper.sh 才改用 swaybg 显示壁纸
swaybg
```

### 2. 编译两个小程序

```bash
~/.config/mango/wallpaperd/build.sh
~/.config/waybar/barprobe/build.sh
```

### 3. 屏幕的缩放和位置

不用手动设置。进入 mango 后点 waybar 最右边的齿轮图标 → “显示器”，选每块屏幕的缩放和外接屏的位置（内置屏的右边 / 左边 / 上边 / 下边）。

- 设置写在 `~/.config/mango/local.conf`（每台电脑各自的文件，不放进仓库），mango 会自动重新加载，马上生效
- 屏幕的位置按缩放后的大小自动算好，屏幕之间不会空出一段
- 插上 / 拔掉显示器时，按记住的设置自动重新排列
- 触屏和触控笔自动固定在笔记本内置的屏幕（`config.conf` 的 `device_rule=type:touch,...`），不用查设备名

没有 `local.conf` 时：所有屏幕都是 100%，自动从左往右排列。

### 4. 仓库里没有的东西

- **虎码码表**：从虎码官方获取 fcitx5 版码表，放到 `~/.local/share/fcitx5/table/tiger.main.dict`。
- **虎码图标**：32×32 的 png，放到 `~/.local/share/icons/hicolor/32x32/apps/fcitx-tiger.png`（`tiger.conf` 里只写图标名 `fcitx-tiger`）。
- **壁纸**：png / jpg 放到 `~/Pictures/background/`，按文件名顺序切换（`Super+W` / `Super+Shift+W`）。

### 5. 重新登录 mango

waybar、fcitx5、壁纸等都由 mango 的 `exec_once` 启动。

## 注意：mango 的版本

配置是按 mango 0.18 的写法（`monitor_rule`、`exec_once` 这类用下划线的名字）写的，0.17 及更早的版本读不了。
`mangowm-git` 每次安装都会编译最新的代码，更新 mango 之后建议先检查一下配置：

```bash
mango -c ~/.config/mango/config.conf -p   # 只检查，不启动；有错误时会列出行号
```

## 取得最新的配置（已经恢复过的电脑）

```bash
dotfiles pull
```

- 如果本地改过同一个文件，`pull` 会停下来，不会覆盖。先用 `dotfiles diff` 看改了什么：
  - 不要的改动：`dotfiles checkout -- <文件>` 还原，再 `pull`
  - 要保留的改动：先 `dotfiles commit`，再 `pull`（会合并两边的修改）
  - fcitx5 在设置界面里保存时会改写 `~/.config/fcitx5/config` 和 `profile`，这两个文件常常会出现这种情况
- `pull` 之后：
  - mango 的 `config.conf`、waybar 的 `style.css`：保存后会自动重新加载，不用做什么
  - waybar 的 `config.jsonc`、各个弹窗脚本、fcitx5 的主题：重新登录 mango 最简单
    （只想重启 fcitx5 时：`fcitx5 -r -d`）
  - `wallpaperd.c`、`barprobe.c` 改了的话：重新执行各自的 `build.sh`
- 只想先看看 GitHub 上有什么新的提交：`dotfiles fetch` 后 `dotfiles log --oneline main..origin/main`

## 日常使用

```bash
dotfiles status
dotfiles add ~/.config/waybar/style.css   # 新文件要登记一次
dotfiles commit -m "waybar: ..."
dotfiles push
```
