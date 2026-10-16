-- 重复上一次输入
--
-- 虎码状态下按 `;` 进入快速输入（tiger.conf 的 QuickPhraseKey=semicolon），
-- 再按空格时，快速输入的输入框里是一个空格 “ ”。
-- 这时把“上一次上屏的内容”作为候选，并且自动上屏（AutoCommit），不用再按别的键。
--
-- fcitx.lastCommit()：fcitx5-lua 提供的“最后一次上屏的内容”（所有窗口共用，只在内存里，fcitx5 重启后清空）
-- 还没有上屏过任何内容时，什么都不做（和以前一样，空格留在输入框里）

local fcitx = require("fcitx")

function repeatLastCommit(input)
    if input ~= " " then
        return nil
    end
    local last = fcitx.lastCommit()
    if last == nil or last == "" then
        return nil
    end
    return {
        { last, last, fcitx.QuickPhraseAction.AutoCommit },
    }
end

fcitx.addQuickPhraseHandler("repeatLastCommit")
