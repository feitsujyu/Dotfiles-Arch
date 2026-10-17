-- 配色：catppuccin（mocha）
--   catppuccin 决定“哪里用什么颜色”，颜色本身全部换成 Lilac（和 kitty / waybar 同一套）：
--     灰阶（底色、文字、边框）和彩色（Markdown 的标题、提示框、代码高亮等）都换掉
--   Markdown 的 1～6 级标题的颜色顺序可以在下面的 heading_style 切换

vim.pack.add({
    { src = "https://github.com/catppuccin/nvim", name = "catppuccin" },
})

-- Markdown 的 1～6 级标题的颜色顺序：
--   "rainbow"  红 → 橙 → 黄 → 绿 → 蓝 → 紫（catppuccin 原来的顺序）
--   "lilac"    粉 → 紫 → 淡紫 → 蓝紫 → 青 → 绿
local heading_style = "lilac"

-- Lilac 的颜色（kitty 的 current-theme.conf、waybar 的 style.css）
local lilac = {
    ink = "#1f1a3d",      -- 底色（kitty background）
    surface = "#3a3470",  -- 胶囊底色
    text = "#c9b9f2",     -- 文字（kitty foreground）
    muted = "#9a8cc8",    -- 次要文字
    accent = "#6c5cc4",   -- 强调色（mango 未聚焦边框）
    pink = "#f5a0c8",     -- 粉色（光标、当前工作区）
    lavender = "#a898e8",
    white = "#fbfaff",
}

require("catppuccin").setup({
    flavour = "mocha",
    transparent_background = true, -- 不画底色，用 kitty 的（半透明）底色
    term_colors = true,
    color_overrides = {
        mocha = {
            -- 彩色：kitty 的 16 色（current-theme.conf）；Lilac 里没有的橙色、淡粉是另外配的
            red = "#f07a9a",       -- color1
            maroon = "#ff9fb8",    -- color9
            peach = "#f5b08a",     -- 橙（偏粉）
            yellow = "#f2cf8a",    -- color3
            green = "#8fd4a8",     -- color2
            teal = "#b0e8c4",      -- color10
            sky = "#7cc4e0",       -- color6
            sapphire = "#a8dcf0",  -- color14
            blue = "#8878d8",      -- color4
            lavender = lilac.lavender, -- color12
            mauve = "#c88ce8",     -- color5
            pink = lilac.pink,     -- color13
            flamingo = "#f8c8dc",  -- 淡粉
            rosewater = "#fbe0ec", -- 更淡的粉
            -- 黑～白的灰阶：Lilac 的深紫～淡紫
            text = lilac.text,
            subtext1 = "#bcade8",
            subtext0 = "#ae9fdc",
            overlay2 = lilac.muted,
            overlay1 = "#867ab4",
            overlay0 = "#72679f",
            surface2 = "#4d4589",
            surface1 = lilac.surface,
            surface0 = "#2a2450",
            base = lilac.ink,
            mantle = "#1a1634",
            crust = "#15112b",
        },
    },
    integrations = {
        mini = { enabled = true },
        render_markdown = true,
        snacks = { enabled = true },
    },
    custom_highlights = function(c)
        local groups = {
            -- 界面
            CursorLine = { bg = "#2a2450" },
            CursorLineNr = { fg = lilac.pink, bold = true },
            LineNr = { fg = c.overlay0 },
            Visual = { bg = lilac.surface },
            WinSeparator = { fg = lilac.accent },
            FloatBorder = { fg = lilac.accent, bg = c.base },
            FloatTitle = { fg = lilac.pink, bg = c.base },
            NormalFloat = { bg = c.base },
            Pmenu = { bg = "#2a2450" },
            PmenuSel = { fg = lilac.white, bg = lilac.accent },
            Search = { fg = c.base, bg = lilac.lavender },
            IncSearch = { fg = c.base, bg = lilac.pink },
            CurSearch = { fg = c.base, bg = lilac.pink },
            Folded = { bg = "#2a2450" },
            Comment = { fg = c.overlay1, italic = true },

            -- 状态栏（lua/config/statusline.lua）
            StatusLine = { fg = c.text, bg = "#2a2450" },
            StatusLineNC = { fg = c.overlay1, bg = "#2a2450" },
            StatusModeNormal = { fg = lilac.ink, bg = lilac.lavender, bold = true },
            StatusModeInsert = { fg = lilac.ink, bg = lilac.pink, bold = true },
            StatusModeVisual = { fg = lilac.white, bg = lilac.accent, bold = true },
            StatusModeCommand = { fg = lilac.ink, bg = c.yellow, bold = true },
            StatusModeReplace = { fg = lilac.ink, bg = c.red, bold = true },
            StatusModified = { fg = lilac.pink, bg = "#2a2450" },
            StatusPosition = { fg = lilac.ink, bg = lilac.lavender },

            -- Markdown 渲染：代码块的底色（参考配置用 crust）
            RenderMarkdownCode = { bg = c.crust },
            -- ==高亮==：橙色的荧光笔（原来的底色和 Lilac 的底色太接近看不出来）
            -- 浅色底上的深色字会显得细，所以用粗体
            RenderMarkdownInlineHighlight = { fg = c.base, bg = c.peach, bold = true },
            -- 没有写语言的代码块的文字：和代码里的成员名（Lua 的 vim.keymap 的 keymap 等）同一个颜色
            -- （哪些文字算“没有写语言的代码块”见 after/queries/markdown/highlights.scm）
            ["@markup.raw.plain"] = { link = "@variable.member" },
        }

        -- Markdown 的 1～6 级标题的颜色（字的颜色，以及按 catppuccin 的算法调暗后的底色）
        if heading_style == "lilac" then
            local darken = require("catppuccin.utils.colors").darken
            local colors = { c.pink, c.mauve, c.lavender, c.blue, c.sky, c.green }
            for i, color in ipairs(colors) do
                groups["rainbow" .. i] = { fg = color }
                groups["RenderMarkdownH" .. i] = { fg = color }
                groups["RenderMarkdownH" .. i .. "Bg"] = { bg = darken(color, 0.28, c.base) }
            end
        end
        return groups
    end,
})

vim.cmd.colorscheme("catppuccin")
