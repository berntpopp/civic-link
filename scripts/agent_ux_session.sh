#!/usr/bin/env bash
# One agent UX session: run one task prompt in one agent CLI with only this MCP server mounted.
# The wall clock starts here (after the fleet session slot is acquired), so queueing is not timed.
#
#   scripts/agent_ux_session.sh <claude|codex|agy> <task-file> <out-dir> <mcp-url>
set -uo pipefail
agent=$1 task=$2 OUT=$3 URL=$4
NAME=eval-civic-link
TIMEOUT=${TIMEOUT:-1200}
id=$(basename "$task" .md)-$agent; dir=$OUT/$id; mkdir -p "$dir/cwd"
prompt=$(sed "s/{SERVER}/$NAME/g" "$task"); printf '%s\n' "$prompt" > "$dir/prompt.txt"
t0=$(date +%s.%N)
cd "$dir/cwd" || exit 1
case $agent in
  claude) timeout "$TIMEOUT" claude -p "$prompt" --model opus \
      --mcp-config "{\"mcpServers\":{\"$NAME\":{\"type\":\"http\",\"url\":\"$URL\"}}}" \
      --strict-mcp-config --tools "" --allowedTools "mcp__${NAME}__*" --setting-sources project \
      --no-session-persistence --output-format stream-json --verbose \
      < /dev/null > "$dir/trace.jsonl" 2> "$dir/stderr.log" ;;
  codex) timeout "$TIMEOUT" codex exec --json --skip-git-repo-check -s read-only \
      -o "$dir/final.txt" -c "mcp_servers.eval_civic.url=\"$URL\"" \
      -c 'mcp_servers.eval_civic.default_tools_approval_mode="approve"' "$prompt" \
      < /dev/null > "$dir/trace.jsonl" 2> "$dir/stderr.log" ;;
  agy) timeout "$TIMEOUT" agy -p "$prompt" --dangerously-skip-permissions \
      --print-timeout "$((TIMEOUT - 60))s" < /dev/null > "$dir/final.txt" 2> "$dir/stderr.log" ;;
esac
echo "rc=$? wall_s=$(echo "$(date +%s.%N) - $t0" | bc)" > "$dir/run.txt"
