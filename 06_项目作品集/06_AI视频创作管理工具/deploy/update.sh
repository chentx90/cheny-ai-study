#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[update] pull latest source (optional, skip if offline)"
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  git pull --ff-only || echo "[update] git pull skipped/failed, continuing with local tree"
fi

echo "[update] rebuild image"
docker compose build --pull

echo "[update] restart service"
docker compose up -d --remove-orphans

echo "[update] done — open http://<host>:${AVM_HOST_PORT:-8010}"
# IPv6 示例：http://[你的公网IPv6]:${AVM_HOST_PORT:-8010}
