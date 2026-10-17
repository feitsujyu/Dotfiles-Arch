; extends
; （上面一行表示“追加到 nvim-treesitter 的 Markdown 高亮规则后面”，不能删）

; 没有写语言的代码块（``` 后面直接换行），以及缩进 4 格的代码块：
; 里面的文字用 @markup.raw.plain（颜色在 lua/plugins/colorscheme.lua 里设置）
; 有语言的代码块不受影响（``` 后面紧接着的是语言名 info_string，不符合下面的写法）
(fenced_code_block
  .
  (fenced_code_block_delimiter)
  .
  (block_continuation)
  .
  (code_fence_content) @markup.raw.plain
  (#set! priority 95))

((indented_code_block) @markup.raw.plain
  (#set! priority 101))
