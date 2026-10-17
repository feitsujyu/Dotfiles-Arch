-- 文件 / 语言的图标（Markdown 代码块右上角的语言图标、文件查找的列表等用）

vim.pack.add({ "https://github.com/nvim-mini/mini.icons" })

require("mini.icons").setup({
    file = {
        ["README.md"] = { glyph = "󰆈", hl = "MiniIconsYellow" },
    },
})
