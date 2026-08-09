#!/bin/bash
# Checks free memory; if low, restarts Ollama (VS Code and other processes are
# left untouched per explicit user scope). Used before each schema_ab retry
# this session because llama-server crashes correlated with near-zero free RAM.
set -e

MIN_FREE_MB=4000

free_mb() {
  vm_stat | awk '/Pages free/ {free=$3} END {print int(free*16384/1048576)}'
}

FREE=$(free_mb)
echo "Free memory: ${FREE}MB"

if [ "$FREE" -lt "$MIN_FREE_MB" ]; then
  echo "Below ${MIN_FREE_MB}MB threshold -- restarting Ollama..."
  osascript -e 'quit app "Ollama"' 2>/dev/null || true
  sleep 2
  PIDS=$(ps aux | grep -E "llama-server|ollama serve|Ollama\.app" | grep -v grep | awk '{print $2}')
  if [ -n "$PIDS" ]; then
    kill -9 $PIDS 2>/dev/null || true
  fi
  sleep 2
  open -a Ollama
  echo "Waiting for Ollama to come back up..."
  for i in $(seq 1 30); do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:11434/api/tags | grep -q 200; then
      echo "Ollama is up."
      break
    fi
    sleep 2
  done
  FREE=$(free_mb)
  echo "Free memory after restart: ${FREE}MB"
else
  echo "Memory OK, no restart needed."
fi
