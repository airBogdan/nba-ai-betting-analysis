#!/bin/bash
FLAG="/tmp/claude-plan-reassessed"

if [ -f "$FLAG" ]; then
  rm "$FLAG"
  exit 0
fi

touch "$FLAG"
echo "Before finalizing this plan, reassess it critically. Identify potential issues, misconfigurations, errors, and rewrite it if needed." >&2
exit 2