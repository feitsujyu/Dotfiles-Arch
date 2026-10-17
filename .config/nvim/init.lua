-- Neovim 的设置（主要用来看 / 写 Markdown，也用来看代码）
--
-- 插件用 Neovim 0.12 自带的 vim.pack 管理：
--   第一次启动时自动从 GitHub 下载到 ~/.local/share/nvim/site/pack/core/opt/
--   版本记录在 nvim-pack-lock.json（放进 dotfiles 仓库，换电脑时装同一个版本）
--   更新插件：:lua vim.pack.update()
--
-- 需要的系统包：tree-sitter-cli marksman imagemagick wl-clipboard ripgrep fd

vim.loader.enable()

require("config.options")
require("config.keymaps")
require("config.statusline")

require("plugins.colorscheme") -- 配色（catppuccin，界面颜色换成 Lilac）
require("plugins.icons")       -- 文件 / 语言图标（mini.icons）
require("plugins.treesitter")  -- 语法高亮、按结构折叠（nvim-treesitter）
require("plugins.snacks")      -- 图片显示、文件查找 / 全文搜索（snacks.nvim）
require("plugins.markdown")    -- Markdown 渲染（render-markdown.nvim）
require("plugins.img-clip")    -- 从剪贴板粘贴图片（img-clip.nvim）
require("plugins.lsp")         -- Markdown 的语言服务器 marksman（nvim-lspconfig）

require("config.kitty-transparency") -- kitty 里让标题、代码块的底色半透明
