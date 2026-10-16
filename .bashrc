#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
alias grep='grep --color=auto'
PS1='[\u@\h \W]\$ '
export PATH="$HOME/.local/bin:$PATH"

# dotfiles：bare 仓库 ~/.dotfiles，工作目录是家目录。用法和 git 一样：dotfiles status / add / commit / push
alias dotfiles='git --git-dir=$HOME/.dotfiles --work-tree=$HOME'
