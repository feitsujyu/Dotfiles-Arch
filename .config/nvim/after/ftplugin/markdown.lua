-- 打开 Markdown 文件时的设置

vim.wo[0][0].wrap = true        -- 自动换行（长段落不用左右滚动）
vim.wo[0][0].conceallevel = 2   -- 隐藏 ** ` 等标记（render-markdown 用）
vim.bo.shiftwidth = 2           -- 列表缩进 2 格
vim.bo.tabstop = 2

-- gx：打开光标处的链接（光标在 [文字] 或 (网址) 上都可以）
vim.keymap.set("n", "gx", function()
    local line = vim.api.nvim_get_current_line()
    local col = vim.fn.col(".")
    for s, url, e in line:gmatch("()%[[^%]]*%]%(([^)%s]+)[^)]*%)()") do
        if col >= s and col < e then
            vim.ui.open(url)
            return
        end
    end
    vim.cmd("normal! gx")
end, { buffer = true, desc = "打开光标处的链接" })

-- zM：只折叠 2 级以下的标题（# 1 级标题保持展开，一眼看到整篇的结构）
-- zR：全部展开；za：展开 / 折叠光标处
vim.keymap.set("n", "zM", function()
    local view = vim.fn.winsaveview()
    vim.cmd("normal! zR")
    -- 从深的标题开始折，外层的折叠才不会把里面的挡住
    for level = 6, 2, -1 do
        local pattern = "^" .. string.rep("#", level) .. "%s"
        for lnum = 1, vim.fn.line("$") do
            if vim.fn.getline(lnum):match(pattern) and vim.fn.foldlevel(lnum) > 0
                and vim.fn.foldclosed(lnum) == -1 then
                vim.cmd(lnum .. "foldclose")
            end
        end
    end
    vim.fn.winrestview(view)
end, { buffer = true, desc = "折叠 2 级以下的标题" })
