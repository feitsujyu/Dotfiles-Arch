-- Markdown 渲染（render-markdown.nvim）
--   在 Neovim 里把 Markdown 显示成渲染后的样子：标题、代码块、表格、复选框、提示框等
--   光标所在的行显示原文（方便修改）
--   切换渲染 / 原文：<leader>mr
--   外观设置照参考配置（patricorgi/dotfiles）

vim.pack.add({ "https://github.com/MeanderingProgrammer/render-markdown.nvim" })

-- 各级标题前的图标（1～6 级）
local heading_icons = { " 󰼏 ", " 󰎨 ", " 󰼑 ", " 󰎲 ", " 󰼓 ", " 󰎴 " }

require("render-markdown").setup({
    -- 提示框：> [!NOTE] 这类写法（GitHub 的 5 种是内置的，这里加上 Obsidian 风格的）
    callout = {
        abstract = {
            raw = "[!ABSTRACT]",
            rendered = "󰯂 Abstract",
            highlight = "RenderMarkdownInfo",
            category = "obsidian",
        },
        summary = {
            raw = "[!SUMMARY]",
            rendered = "󰯂 Summary",
            highlight = "RenderMarkdownInfo",
            category = "obsidian",
        },
        tldr = { raw = "[!TLDR]", rendered = "󰦩 Tldr", highlight = "RenderMarkdownInfo", category = "obsidian" },
        failure = {
            raw = "[!FAILURE]",
            rendered = " Failure",
            highlight = "RenderMarkdownError",
            category = "obsidian",
        },
        fail = { raw = "[!FAIL]", rendered = " Fail", highlight = "RenderMarkdownError", category = "obsidian" },
        missing = {
            raw = "[!MISSING]",
            rendered = " Missing",
            highlight = "RenderMarkdownError",
            category = "obsidian",
        },
        attention = {
            raw = "[!ATTENTION]",
            rendered = " Attention",
            highlight = "RenderMarkdownWarn",
            category = "obsidian",
        },
        warning = {
            raw = "[!WARNING]",
            rendered = " Warning",
            highlight = "RenderMarkdownWarn",
            category = "github",
        },
        danger = {
            raw = "[!DANGER]",
            rendered = " Danger",
            highlight = "RenderMarkdownError",
            category = "obsidian",
        },
        error = { raw = "[!ERROR]", rendered = " Error", highlight = "RenderMarkdownError", category = "obsidian" },
        bug = { raw = "[!BUG]", rendered = " Bug", highlight = "RenderMarkdownError", category = "obsidian" },
        quote = { raw = "[!QUOTE]", rendered = " Quote", highlight = "RenderMarkdownQuote", category = "obsidian" },
        cite = { raw = "[!CITE]", rendered = " Cite", highlight = "RenderMarkdownQuote", category = "obsidian" },
        todo = { raw = "[!TODO]", rendered = " Todo", highlight = "RenderMarkdownInfo", category = "obsidian" },
        wip = { raw = "[!WIP]", rendered = "󰦖 WIP", highlight = "RenderMarkdownHint", category = "obsidian" },
        done = { raw = "[!DONE]", rendered = " Done", highlight = "RenderMarkdownSuccess", category = "obsidian" },
    },
    sign = { enabled = false }, -- 行号左边不显示标记
    -- 公式 $...$ 转成文字显示：需要 utftex 或 latex2text（没有装），先关掉
    latex = { enabled = false },
    code = {
        -- 代码块：宽度只到最长的那一行（至少 80）
        width = "block",
        min_width = 80,
        -- 上下的 ``` 那两行也画成和代码同样的底色（"thin" 用字符画细边线，kitty 里底色半透明时不会跟着透明）
        border = "thick",
        -- 语言名那一行的空白处：默认用“█”字符画（字符不会透明），改成空格（底色在文件最后设置）
        language_border = " ",
        left_pad = 1,
        right_pad = 1,
        -- 所有语言都画深色底（默认 diff 不画，但 catppuccin 的 diff 只有文字颜色，没有自己的底色）
        disable_background = {},
        -- 右上角显示语言的图标和名字
        position = "right",
        language_icon = true,
        language_name = true,
        -- 行内代码 `...` 的颜色（不让标题里的行内代码太显眼）
        highlight_inline = "RenderMarkdownCodeInfo",
    },
    -- 标题：前面换成图标，加底色
    -- （上下的边线不加：边线是用字符画的，kitty 里让底色半透明时边线不会跟着透明）
    heading = {
        icons = heading_icons,
        border = false,
        render_modes = true, -- 插入模式下也保持渲染
    },
    -- 复选框：- [ ] 未完成  - [x] 完成，以及 [?] [>] [-] [!] [~] 几种自定义的
    checkbox = {
        unchecked = {
            icon = "󰄱",
            highlight = "RenderMarkdownCodeFallback",
            scope_highlight = "RenderMarkdownCodeFallback",
        },
        checked = {
            icon = "󰄵",
            highlight = "RenderMarkdownUnchecked",
            scope_highlight = "RenderMarkdownUnchecked",
        },
        custom = {
            question = {
                raw = "[?]",
                rendered = "",
                highlight = "RenderMarkdownError",
                scope_highlight = "RenderMarkdownError",
            },
            todo = {
                raw = "[>]",
                rendered = "󰦖",
                highlight = "RenderMarkdownInfo",
                scope_highlight = "RenderMarkdownInfo",
            },
            canceled = {
                raw = "[-]",
                rendered = "",
                highlight = "RenderMarkdownCodeFallback",
                scope_highlight = "@text.strike",
            },
            important = {
                raw = "[!]",
                rendered = "",
                highlight = "RenderMarkdownWarn",
                scope_highlight = "RenderMarkdownWarn",
            },
            favorite = {
                raw = "[~]",
                rendered = "",
                highlight = "RenderMarkdownMath",
                scope_highlight = "RenderMarkdownMath",
            },
        },
    },
    -- 表格：圆角边框
    pipe_table = {
        alignment_indicator = "─",
        border = { "╭", "┬", "╮", "├", "┼", "┤", "╰", "┴", "╯", "│", "─" },
    },
    -- 链接：前面加图标（GitHub、YouTube 等有专门的图标）
    link = {
        wiki = { icon = " ", highlight = "RenderMarkdownWikiLink", scope_highlight = "RenderMarkdownWikiLink" },
        image = " ",
        custom = {
            github = { pattern = "github", icon = " " },
            gitlab = { pattern = "gitlab", icon = "󰮠 " },
            youtube = { pattern = "youtube", icon = " " },
        },
        hyperlink = " ",
    },
    -- 光标所在行显示原文，但标题的底色保持显示
    anti_conceal = {
        ignore = {
            head_background = true,
        },
    },
    -- 光标所在行：普通模式也显示原文（可视 / 命令模式时保持渲染）
    win_options = { concealcursor = { rendered = "vc" } },
})

-- 语言名那一行的空白（上面的 language_border）：
-- render-markdown 只给它“文字颜色”（原本是用来画 █ 的），没有底色，所以空格会露出窗口的底色。
-- 这里给它加上和代码块相同的底色。
-- render-markdown 在启动后、换配色后会重新生成这个颜色组，所以等它做完（vim.schedule）再设置
local function language_row_background()
    local name = require("render-markdown.core.colors").bg_as_fg("RenderMarkdownCodeBorder")
    if name then
        local bg = vim.api.nvim_get_hl(0, { name = "RenderMarkdownCode", link = false }).bg
        vim.api.nvim_set_hl(0, name, { fg = bg, bg = bg })
    end
end
vim.api.nvim_create_autocmd({ "VimEnter", "ColorScheme" }, {
    group = vim.api.nvim_create_augroup("markdown-language-row", { clear = true }),
    callback = function()
        vim.schedule(language_row_background)
    end,
})

vim.keymap.set("n", "<leader>mr", "<cmd>RenderMarkdown toggle<CR>", { desc = "Markdown：切换渲染 / 原文" })
