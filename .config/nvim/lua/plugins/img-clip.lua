-- 从剪贴板粘贴图片（img-clip.nvim）
--   截图 / 复制图片后，在 Markdown 里按 <leader>p：
--   图片保存到这个文件旁边的 attachments/ 文件夹（文件名是日期时间），并插入 ![](attachments/....png)
--   剪贴板里是图片的路径 / 网址时也可以（会复制一份到 attachments/）
--   读剪贴板用 wl-clipboard

vim.pack.add({ "https://github.com/HakonHarnes/img-clip.nvim" })

require("img-clip").setup({
    default = {
        dir_path = "attachments",
        relative_to_current_file = true, -- attachments/ 放在 Markdown 文件旁边（而不是 Neovim 的当前目录）
        use_absolute_path = false,
        copy_images = true,
        prompt_for_file_name = false,
        file_name = "%y%m%d-%H%M%S",
        extension = "png",
    },
    filetypes = {
        markdown = {
            template = "![$CURSOR]($FILE_PATH)", -- 光标停在 [] 里，可以接着输入图片说明
        },
    },
})

vim.keymap.set("n", "<leader>p", "<cmd>PasteImage<CR>", { desc = "从剪贴板粘贴图片" })
