-- 通用的快捷键（<leader> 是空格键）
-- 各插件的快捷键写在各自的文件里；Markdown 专用的写在 after/ftplugin/markdown.lua

local map = vim.keymap.set

-- 自动换行时，j / k 按屏幕上看到的行移动（带数字时如 5j 还是按实际的行）
map({ "n", "x" }, "j", "v:count == 0 ? 'gj' : 'j'", { expr = true, desc = "下移一行" })
map({ "n", "x" }, "k", "v:count == 0 ? 'gk' : 'k'", { expr = true, desc = "上移一行" })

map("n", "<Esc>", "<cmd>nohlsearch<CR>", { desc = "取消搜索高亮" })
map("n", "<leader>w", "<cmd>write<CR>", { desc = "保存" })
map("n", "<leader>q", "<cmd>quit<CR>", { desc = "关闭窗口" })

-- 分屏和切换（Ctrl + h/j/k/l 移到左 / 下 / 上 / 右的窗口）
map("n", "|", "<cmd>vsplit<CR>", { desc = "左右分屏" })
map("n", "\\", "<cmd>split<CR>", { desc = "上下分屏" })
map("n", "<C-h>", "<C-w>h", { desc = "移到左边的窗口" })
map("n", "<C-j>", "<C-w>j", { desc = "移到下边的窗口" })
map("n", "<C-k>", "<C-w>k", { desc = "移到上边的窗口" })
map("n", "<C-l>", "<C-w>l", { desc = "移到右边的窗口" })

-- 打开的文件之间切换
map("n", "H", "<cmd>bprevious<CR>", { desc = "上一个文件" })
map("n", "L", "<cmd>bnext<CR>", { desc = "下一个文件" })
