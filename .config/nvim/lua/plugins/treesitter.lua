-- 语法高亮、按结构折叠（nvim-treesitter，新版 main 分支的写法）
--   各语言的“解析器”第一次启动时自动下载并编译（要用 tree-sitter-cli 和 gcc），
--   放在 ~/.local/share/nvim/site/parser/
--   以后要加语言：在 languages 里加上名字（可用的名字：:lua print(vim.inspect(require("nvim-treesitter").get_available()))）
--   更新插件后要更新解析器：:TSUpdate

vim.pack.add({ "https://github.com/nvim-treesitter/nvim-treesitter" })

local languages = {
    -- Markdown 本身，以及里面嵌入的 HTML、LaTeX 公式、YAML（文件开头的 --- 属性）
    "markdown", "markdown_inline", "html", "latex", "yaml",
    -- 代码块里常见的语言 / 看代码时用
    "bash", "c", "cpp", "css", "diff", "javascript", "json", "lua", "python",
    "query", "regex", "rust", "toml", "vim", "vimdoc",
}

-- 还没有装的才会下载（在后台进行，装好之后重新打开文件就会有高亮）
require("nvim-treesitter").install(languages)

-- 打开文件时，有解析器的语言就用 treesitter 高亮和折叠
vim.api.nvim_create_autocmd("FileType", {
    group = vim.api.nvim_create_augroup("treesitter-start", { clear = true }),
    callback = function(args)
        if not pcall(vim.treesitter.start, args.buf) then
            return
        end
        vim.wo[0][0].foldmethod = "expr"
        vim.wo[0][0].foldexpr = "v:lua.vim.treesitter.foldexpr()"
    end,
})
