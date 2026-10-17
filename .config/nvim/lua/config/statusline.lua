-- 状态栏：  模式  文件名 [+]  ……  文件类型  行:列  百分比
-- 颜色（StatusMode* 等）在 lua/plugins/colorscheme.lua 里定义

local modes = {
    n = { "普通", "StatusModeNormal" },
    i = { "插入", "StatusModeInsert" },
    v = { "选择", "StatusModeVisual" },
    V = { "选行", "StatusModeVisual" },
    ["\22"] = { "选块", "StatusModeVisual" },
    c = { "命令", "StatusModeCommand" },
    R = { "替换", "StatusModeReplace" },
    t = { "终端", "StatusModeInsert" },
}

function _G.statusline()
    local mode = modes[vim.fn.mode():sub(1, 1)] or modes.n
    local parts = {
        "%#" .. mode[2] .. "# " .. mode[1] .. " ",
        "%#StatusLine# %<%f",                      -- 文件名（太长时从这里截掉）
        vim.bo.modified and " %#StatusModified#●%#StatusLine#" or "",
        vim.bo.readonly and " 󰌾" or "",
        "%=",                                      -- 以下靠右
        vim.bo.filetype ~= "" and (vim.bo.filetype .. "  ") or "",
        "%#StatusPosition# %l:%c  %p%% ",
    }
    return table.concat(parts)
end

vim.o.statusline = "%!v:lua.statusline()"
