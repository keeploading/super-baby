#!/usr/bin/env bash
# 把 product-manager + architect 协作能力安装到目标项目。
# 用法：
#   ./install.sh [目标项目目录]      # 缺省为当前目录
# 行为：
#   1. 复制两个 agent 到 <目标>/.claude/agents/
#   2. 把协作流程片段合并进 <目标>/CLAUDE.md（已存在则追加，重复则跳过）
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$(pwd)}"

if [ ! -d "$TARGET" ]; then
  echo "错误：目标目录不存在：$TARGET" >&2
  exit 1
fi

# 1) 安装 agents
mkdir -p "$TARGET/.claude/agents"
cp "$SRC_DIR/agents/product-manager.md" "$TARGET/.claude/agents/"
cp "$SRC_DIR/agents/architect.md"       "$TARGET/.claude/agents/"
echo "✓ 已安装 agents 到 $TARGET/.claude/agents/"

# 2) 合并 CLAUDE.md 片段
CLAUDE_FILE="$TARGET/CLAUDE.md"
MARKER="<!-- BEGIN pm-architect-workflow -->"
if [ -f "$CLAUDE_FILE" ] && grep -qF "$MARKER" "$CLAUDE_FILE"; then
  echo "• CLAUDE.md 已包含协作流程片段，跳过。"
else
  {
    [ -f "$CLAUDE_FILE" ] && printf '\n'
    cat "$SRC_DIR/CLAUDE.snippet.md"
  } >> "$CLAUDE_FILE"
  echo "✓ 已把协作流程片段写入 $CLAUDE_FILE"
fi

# 3) 建好默认文档目录
mkdir -p "$TARGET/docs/requirements" "$TARGET/docs/design"
echo "✓ 已创建 docs/requirements 与 docs/design"
echo "完成。在目标项目里直接对 Claude 说『帮我生成需求设计文档』即可触发。"
