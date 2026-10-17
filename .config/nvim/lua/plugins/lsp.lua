-- 语言服务器（LSP）
--   nvim-lspconfig 提供各语言服务器的启动设置，这里只打开 Markdown 的 marksman（pacman 安装）
--   marksman 的功能：
--     <leader>fs  标题列表（snacks.lua）
--     gd          跳到链接指向的文件 / 标题（[文字](其他文件.md#标题)）
--     K           光标处链接的内容预览
--     grr         哪些地方链接到了这个标题
--     grn         重命名标题（链接到它的地方一起改）
--   以后要用其他语言的服务器：装好后在下面的列表里加名字（名字见 :help lspconfig-all）

vim.pack.add({ "https://github.com/neovim/nvim-lspconfig" })

vim.lsp.enable({ "marksman" })

vim.keymap.set("n", "gd", vim.lsp.buf.definition, { desc = "跳到定义 / 链接的目标" })
