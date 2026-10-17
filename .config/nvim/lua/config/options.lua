-- 基本设置

vim.g.mapleader = " "
vim.g.maplocalleader = " "

-- 显示
vim.o.number = true          -- 行号
vim.o.relativenumber = true  -- 其他行显示和光标所在行的距离（方便 5j、3k 这样移动）
vim.o.cursorline = true      -- 光标所在行加底色
vim.o.signcolumn = "no"      -- 行号左边不留标记栏
vim.o.scrolloff = 5          -- 光标上下至少留 5 行
vim.o.wrap = false           -- 默认不自动换行（Markdown 在 after/ftplugin/markdown.lua 里打开）
vim.o.linebreak = true       -- 自动换行时在单词之间换
vim.o.breakindent = true     -- 换行后的部分和上一行对齐
vim.o.showmode = false       -- 模式显示在状态栏里
vim.o.laststatus = 3         -- 分屏时只有一条状态栏
vim.o.winborder = "rounded"  -- 浮动窗口用圆角边框
vim.o.list = true            -- 显示 Tab 和行尾空格
vim.opt.listchars = { tab = "» ", trail = "·", nbsp = "␣" }
vim.opt.fillchars = { eob = " ", fold = " " }

-- 编辑
vim.o.expandtab = true       -- Tab 键输入空格
vim.o.tabstop = 4
vim.o.shiftwidth = 4
vim.o.undofile = true        -- 关掉文件后也能撤销
vim.o.mouse = "a"
vim.o.splitright = true      -- 新的分屏开在右边 / 下边
vim.o.splitbelow = true

-- 搜索：全是小写时不区分大小写，含大写字母时区分
vim.o.ignorecase = true
vim.o.smartcase = true
vim.o.inccommand = "split"   -- :s 替换时实时预览

vim.o.updatetime = 250
vim.o.timeoutlen = 400

-- 折叠：默认全部展开（按结构折叠的规则在 lua/plugins/treesitter.lua 里设置）
vim.o.foldlevelstart = 99
vim.o.foldtext = ""          -- 折叠后的那一行保持原来的颜色

-- 和系统共用剪贴板（用 wl-clipboard）：y 复制的内容可以粘贴到别的程序
-- 放到启动后再设置，启动更快
vim.schedule(function()
    vim.o.clipboard = "unnamedplus"
end)
