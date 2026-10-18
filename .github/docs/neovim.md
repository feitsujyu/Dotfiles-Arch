# Neovim

主要用来看 / 写 Markdown（在 kitty 里直接显示渲染后的样子、图片），也用来看代码。
安装步骤在 [README 的 “5. Neovim 的插件”](../README.md#5-neovim-的插件)，这里写设置的内容、为什么这样做，以及设置时遇到的问题。

调查时的版本：Neovim 0.12.6、kitty 0.49.2。外观参考了 [patricorgi/dotfiles](https://github.com/patricorgi/dotfiles) 的设置。

## 文件一览

| 文件 | 内容 |
|---|---|
| `init.lua` | 按顺序读入下面的文件 |
| `lua/config/options.lua` | 基本设置（`<leader>` 是空格键、行号、缩进、和系统共用剪贴板等） |
| `lua/config/keymaps.lua` | 通用的快捷键 |
| `lua/config/statusline.lua` | 状态栏（中文的模式名） |
| `lua/config/kitty-transparency.lua` | 在 kitty 里让标题、代码块的底色半透明 |
| `lua/config/typeless.lua` | Typeless（语音输入）用的 Ctrl+V，见 [typeless.md](typeless.md#5-neovim-里的-ctrlv) |
| `lua/plugins/colorscheme.lua` | 配色：catppuccin，颜色全部换成 Lilac |
| `lua/plugins/markdown.lua` | Markdown 渲染（render-markdown.nvim） |
| `lua/plugins/treesitter.lua` | 语法高亮、按结构折叠（nvim-treesitter） |
| `lua/plugins/snacks.lua` | 图片显示、文件查找 / 全文搜索、通知（snacks.nvim） |
| `lua/plugins/img-clip.lua` | 从剪贴板粘贴图片（img-clip.nvim） |
| `lua/plugins/lsp.lua` | Markdown 的语言服务器 marksman |
| `lua/plugins/icons.lua` | 文件 / 语言图标（mini.icons） |
| `after/ftplugin/markdown.lua` | 打开 Markdown 时：自动换行、`gx` 打开链接、`zM` 只折叠 2 级以下的标题 |
| `after/queries/markdown/highlights.scm` | 没有写语言的代码块的文字颜色 |
| `nvim-pack-lock.json` | 插件的版本（和设置一起 commit） |

插件用 Neovim 0.12 自带的 `vim.pack` 管理（不用 lazy.nvim 等），第一次启动时从 GitHub 下载。

## 主要的快捷键

| 键 | 功能 |
|---|---|
| `<leader>mr` | Markdown：切换渲染 / 原文 |
| `<leader>ff` / `fo` / `fw` / `fb` | 找文件 / 最近的文件 / 全文搜索 / 在这个文件里搜索 |
| `<leader>fs` | 标题 / 符号列表 |
| `<leader><leader>` | 打开着的文件 |
| `<leader>fk` | 快捷键一览 |
| `<leader>e` | 文件树 |
| `<leader>p` | 粘贴剪贴板里的图片（保存到 `attachments/`，插入链接） |
| `gd` / `K` | 跳到链接的目标 / 预览链接的内容（marksman） |
| `gx` | 打开光标处的链接 |
| `zM` / `zR` / `za` | 折叠 2 级以下的标题 / 全部展开 / 展开或折叠光标处 |

## 设计上的选择

### 在 kitty 里预览，不用浏览器

Markdown 的预览有“在浏览器里显示”（markdown-preview.nvim 等）和“在 Neovim 里直接显示渲染后的样子”两种，选了后者：

- render-markdown.nvim 把标题、代码块、表格、提示框等直接画在 Neovim 里，光标所在的行显示原文（方便修改）。
- 图片用 kitty 的图形协议显示（snacks.nvim）。别的终端里不显示图片，也不会出错。
- 不需要浏览器、node 等。

### 现在没有装的功能

| 功能 | 需要的包 | 打开方法 |
|---|---|---|
| 数学公式显示成排版后的图片 | `tectonic ghostscript`（不想联网下载 TeX 宏包时用 `texlive-basic texlive-latexextra ghostscript`） | `snacks.lua` 的 `math = { enabled = false }` 改成 `true` |
| Mermaid 图显示成图片 | `mermaid-cli`（在 extra 仓库，约 360 MB，还依赖 nodejs 和 chromium） | 装好后自动显示 |
| 公式 `$...$` 转成文字显示 | `utftex` 或 `latex2text` | `markdown.lua` 的 `latex = { enabled = false }` 改成 `true` |

### 配色

- catppuccin（mocha）决定“哪里用什么颜色”，颜色本身全部换成 Lilac（和 kitty / waybar 同一套）：14 种彩色 + 灰阶。
- 背景透明（`transparent_background = true`），用 kitty 的半透明底色。
- Markdown 的 1～6 级标题的颜色顺序可以切换（`colorscheme.lua` 的 `heading_style`）：
  - `"lilac"`（现在用的）：粉 → 紫 → 淡紫 → 蓝紫 → 青 → 绿
  - `"rainbow"`：红 → 橙 → 黄 → 绿 → 蓝 → 紫（catppuccin 原来的顺序）
- 标题的底色按 catppuccin 的算法调暗（`darken(颜色, 0.28, 底色)`）。

### 底色半透明（kitty）

终端里“指定了颜色的底色”本来是不透明的，Neovim 自己没办法设透明度，所以标题、代码块的底色挡住了 kitty 的半透明。
kitty 有一个功能：底色正好是某几种颜色（最多 7 种）时画成半透明（`transparent_background_color1`～`7`）。
`kitty-transparency.lua` 在启动 / 换配色时，把 6 级标题和代码块的底色用控制码（OSC 21）告诉 kitty（只对这个窗口有效，不透明度 0.9），退出（或 Ctrl+Z）时恢复。

## 遇到的问题

### nvim-treesitter 的写法变了

参考配置用的 `require("nvim-treesitter.configs").setup({...})` 在 nvim-treesitter 的 main 分支（新版）里已经没有了。
现在的写法：`require("nvim-treesitter").install({ 语言... })` 装解析器，在 `FileType` 时 `vim.treesitter.start()` 打开高亮。解析器的编译要用 `tree-sitter-cli`。

### diff 的代码块没有底色

render-markdown 默认不给 `diff` 的代码块画底色（`code.disable_background` 的默认值里有 diff），而 catppuccin 的 diff 只有文字颜色。改成 `disable_background = {}`。

### 半透明时，边线 / 语言名那一行不透明

- **原因**：kitty 的半透明只对“底色”有效。render-markdown 的标题上下边线、代码块的细边线、语言名那一行的空白，是用 `▄ ▀ █` 之类的**字符**（文字颜色）画的，不会跟着透明。
- **对策**：
  - 标题：不画上下边线（`heading.border = false`）。
  - 代码块：`border = "thick"`（上下的 ``` 那两行画成和代码同样的底色），`language_border = " "`（语言名那一行的空白用空格）。
  - 空格只有文字颜色、没有底色，会露出窗口的底色，所以给这个颜色组（`bg_as_fg("RenderMarkdownCodeBorder")`）加上和代码块相同的底色。
  - render-markdown 在启动后、换配色后会重新生成这个颜色组，把我们的设置盖掉，所以要 `vim.schedule` 等它做完再设置。

### ==高亮== 看不出来

render-markdown 默认的高亮底色和 Lilac 的底色太接近，看不出来。改成橙色（彩虹标题第 2 级的颜色）的底色；浅色底上的深色字会显得细，所以加粗。

### 没有写语言的代码块的文字颜色

没有写语言的代码块（``` 后面直接换行）和缩进 4 格的代码块，nvim-treesitter 没有给里面的文字颜色（和正文一样，分不出来）。
`after/queries/markdown/highlights.scm` 给它们加上 `@markup.raw.plain`（`; extends` 表示追加到原来的规则后面，不能删），颜色和代码里的成员名（Lua 的 `vim.keymap` 的 `keymap` 等，`@variable.member`）一样。
试过绿色（太像代码）、注释的颜色（太暗）、和正文一样的颜色（分不出来）。

### 测试时：强制关掉的 Neovim 留下交换文件

强制结束 Neovim（例如直接关掉 kitty 窗口）会留下交换文件，下次打开同一个文件时停在交换文件的提示（ATTENTION）上。
这时按的键会被当成提示的回答，看起来像是设置出了问题。删掉 `~/.local/state/nvim/swap/` 里对应的文件即可。

## 更新插件

在 nvim 里执行 `:lua vim.pack.update()`，看过更新内容后 `:write` 确认，再执行 `:TSUpdate`（更新语法高亮的解析器）。
`nvim-pack-lock.json` 会变，和设置一起 commit。
render-markdown 更新后，如果语言名那一行又出现不透明的块，检查 `markdown.lua` 里 `bg_as_fg` 的写法是否还有效。
