-- 在 kitty 里，让 Markdown 的标题底色、代码块底色也半透明（和 kitty 的其他部分一样能透出壁纸）
--
-- 终端里“指定了颜色的底色”本来是不透明的，Neovim 自己没办法设透明度。
-- kitty 有一个功能：底色正好是某几种颜色（最多 7 种）时画成半透明，
-- 这里在 Neovim 启动 / 换配色时，把下面这些颜色组的底色告诉 kitty（只对这个 kitty 窗口有效），
-- 退出 Neovim（或 Ctrl+Z 暂停）时恢复成 kitty 原来的设置。
-- 不是 kitty 时什么也不做。

local OPACITY = 0.9 -- 不透明度：1 = 不透明，越小越透明（太小的话浅色的壁纸会透得发白，看不清字）

-- 要变成半透明的颜色组（最多 7 个，kitty 的上限）
local groups = {
    "RenderMarkdownH1Bg", "RenderMarkdownH2Bg", "RenderMarkdownH3Bg",
    "RenderMarkdownH4Bg", "RenderMarkdownH5Bg", "RenderMarkdownH6Bg",
    "RenderMarkdownCode",
}

if vim.env.KITTY_WINDOW_ID == nil then
    return
end

-- kitty 的控制码：ESC ] 21 ; transparent_background_color1=#rrggbb@不透明度 ; ... ESC \
-- 只写 transparent_background_colorN（没有 =）是恢复原来的设置
local function send(fields)
    vim.api.nvim_ui_send("\027]21;" .. table.concat(fields, ";") .. "\027\\")
end

local function apply()
    local fields = {}
    for i, name in ipairs(groups) do
        local bg = vim.api.nvim_get_hl(0, { name = name, link = false }).bg
        local key = "transparent_background_color" .. i
        fields[i] = bg and string.format("%s=#%06x@%s", key, bg, OPACITY) or key
    end
    send(fields)
end

local function reset()
    local fields = {}
    for i = 1, #groups do
        fields[i] = "transparent_background_color" .. i
    end
    send(fields)
end

local group = vim.api.nvim_create_augroup("kitty-transparency", { clear = true })
vim.api.nvim_create_autocmd({ "UIEnter", "ColorScheme", "VimResume" }, { group = group, callback = apply })
vim.api.nvim_create_autocmd({ "VimLeavePre", "VimSuspend" }, { group = group, callback = reset })
