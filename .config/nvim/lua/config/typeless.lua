-- Typeless（语音输入）用的设置（init.lua 里 require；不用 Typeless 的电脑把 init.lua 里那一行注释掉）
--
-- Typeless 输入文字时是“放进剪贴板 → 按 Ctrl+V”：
--   1. 插入模式和命令行（: 之后）的 Ctrl+V 改成粘贴剪贴板
--      （原来的“照原样输入下一个字”用 Ctrl+Q，功能一样）
--   2. 普通模式、可视模式下没办法输入文字，这时的语音输入基本都是误操作：
--      Typeless 刚放进剪贴板（1 秒以内）时收到的 Ctrl+V 丢掉，不切换成矩形选择；其他时候 Ctrl+V 照常是矩形选择
--   3. 在 kitty 里：告诉 kitty “在运行 Neovim”（kitty 的用户变量 in_editor），
--      kitty 就把 Ctrl+V 原样交给 Neovim，而不是自己粘贴（见 ~/.config/kitty/typeless.conf）

-- <C-r><C-o>+：把剪贴板的内容原样插入（不会被自动缩进打乱）
vim.keymap.set("i", "<C-v>", "<C-r><C-o>+", { desc = "粘贴剪贴板（Typeless）" })
vim.keymap.set("c", "<C-v>", "<C-r>+", { desc = "粘贴剪贴板（Typeless）" })

-- Typeless 放进剪贴板的时间：wl-copy 的替身（~/.config/mango/scripts/typeless/wl-copy）每次更新这个文件的时间
local CLIPBOARD_TIME = (vim.env.XDG_RUNTIME_DIR or "/tmp") .. "/typeless-clipboard-time"
local IGNORE_WITHIN = 1 -- 秒：放进剪贴板之后这么久之内收到的 Ctrl+V 算是 Typeless 发的

local function from_typeless()
    local stat = vim.uv.fs_stat(CLIPBOARD_TIME)
    if not stat then
        return false
    end
    local sec, usec = vim.uv.gettimeofday()
    local age = (sec + usec / 1e6) - (stat.mtime.sec + stat.mtime.nsec / 1e9)
    return age >= 0 and age < IGNORE_WITHIN
end

vim.keymap.set({ "n", "x" }, "<C-v>", function()
    return from_typeless() and "" or "<C-v>"
end, { expr = true, desc = "矩形选择（Typeless 发的 Ctrl+V 丢掉）" })

if vim.env.KITTY_WINDOW_ID == nil then
    return
end

-- kitty 的控制码：ESC ] 1337 ; SetUserVar=名字=值（base64） BEL。只写名字是删除这个变量
-- “MQ==” 是 “1” 的 base64
local function set_in_editor(on)
    vim.api.nvim_ui_send("\027]1337;SetUserVar=in_editor" .. (on and "=MQ==" or "") .. "\007")
end

local group = vim.api.nvim_create_augroup("typeless", { clear = true })
vim.api.nvim_create_autocmd({ "UIEnter", "VimResume" }, {
    group = group,
    callback = function() set_in_editor(true) end,
})
vim.api.nvim_create_autocmd({ "VimLeavePre", "VimSuspend" }, {
    group = group,
    callback = function() set_in_editor(false) end,
})
