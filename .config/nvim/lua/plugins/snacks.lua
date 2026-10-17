-- snacks.nvim：图片显示、文件查找 / 全文搜索、通知
--   图片用 kitty 的图形协议显示（只在 kitty 里有效）；png 以外的格式用 imagemagick 转换

vim.pack.add({ "https://github.com/folke/snacks.nvim" })

require("snacks").setup({
    image = {
        enabled = true,
        doc = {
            enabled = true,
            inline = true,   -- 图片直接显示在 Markdown 正文里（那一行的下面）
            float = true,    -- inline 关掉时：光标移到图片链接上，在浮动窗口里显示
            max_width = 80,  -- 最大宽度 / 高度（字符格数）
            max_height = 30,
        },
        -- 数学公式（$...$）排版成图片显示：需要 LaTeX，现在没有装，先关掉
        -- 要用时：sudo pacman -S tectonic ghostscript，然后把下面改成 true
        math = { enabled = false },
        -- Mermaid 图：需要 mermaid-cli（很重，没有装）。没有装时只显示代码，不会报错
    },
    picker = {
        ui_select = true, -- Neovim 里“从列表里选一个”的地方都用 snacks 的列表
        matcher = { frecency = true }, -- 常用的文件排在前面
    },
    notifier = { enabled = true }, -- 通知显示在右上角
    input = { enabled = true },    -- 输入框（重命名等）
})

-- 查找（f = find）
local map = vim.keymap.set
map("n", "<leader>ff", function() Snacks.picker.smart() end, { desc = "找文件" })
map("n", "<leader>fo", function() Snacks.picker.recent() end, { desc = "最近打开的文件" })
map("n", "<leader>fw", function() Snacks.picker.grep() end, { desc = "全文搜索" })
map("n", "<leader>fb", function() Snacks.picker.lines() end, { desc = "在这个文件里搜索" })
map("n", "<leader>fs", function()
    -- 标题 / 符号列表：有语言服务器（Markdown 是 marksman）时用它，没有时用 treesitter
    if #vim.lsp.get_clients({ bufnr = 0, method = "textDocument/documentSymbol" }) > 0 then
        Snacks.picker.lsp_symbols({ tree = true })
    else
        Snacks.picker.treesitter()
    end
end, { desc = "标题 / 符号列表" })
map("n", "<leader><leader>", function() Snacks.picker.buffers({ sort_lastused = true }) end, { desc = "打开着的文件" })
map("n", "<leader>fk", function() Snacks.picker.keymaps() end, { desc = "快捷键一览" })
map("n", "<leader>fh", function() Snacks.picker.help() end, { desc = "搜索帮助" })
map("n", "<leader>fc", function() Snacks.picker.files({ cwd = vim.fn.stdpath("config") }) end, { desc = "Neovim 的设置文件" })
map("n", "<leader>fn", function() Snacks.picker.notifications() end, { desc = "通知的记录" })
map("n", "<leader>e", function() Snacks.explorer() end, { desc = "文件树" })
