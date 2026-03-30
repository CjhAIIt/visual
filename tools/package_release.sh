#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASES_DIR="$ROOT_DIR/releases"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
PACKAGE_NAME="plant-release-${TIMESTAMP}"
STAGE_DIR="$RELEASES_DIR/$PACKAGE_NAME"

mkdir -p "$RELEASES_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required to package this project." >&2
  exit 1
fi

echo "[1/4] Building frontend"
(
  cd "$ROOT_DIR/frontend"
  if [ ! -d node_modules ]; then
    npm ci
  fi
  npm run build
)

echo "[2/4] Staging release files"
rsync -a \
  --exclude=".git/" \
  --exclude=".idea/" \
  --exclude=".vscode/" \
  --exclude=".codex-artifacts/" \
  --exclude=".playwright-cli/" \
  --exclude="__pycache__/" \
  --exclude="*.pyc" \
  --exclude="*.pyo" \
  --exclude=".venv/" \
  --exclude=".venv-linux/" \
  --exclude="venv/" \
  --exclude="env/" \
  --exclude="backups/" \
  --exclude="releases/" \
  --exclude="runtime/" \
  --exclude="video_frames/" \
  --exclude="deploy/backend.env" \
  --exclude="frontend/node_modules/" \
  --exclude="frontend/.vite/" \
  --exclude="frontend/playwright-report/" \
  --exclude="frontend/test-results/" \
  --exclude="frontend/index.shell-backup-*.html" \
  --exclude="test-results/" \
  --exclude="plantbackend/.venv/" \
  --exclude="plantbackend/.venv-linux/" \
  --exclude="plantbackend/.venv-train/" \
  --exclude="plantbackend/.venv_linux/" \
  --exclude="plantbackend/.vscode/" \
  --exclude="plantbackend/__pycache__/" \
  --exclude="plantbackend/auth.db" \
  --exclude="plantbackend/plant_auth.db" \
  --exclude="plantbackend/annotation_datasets/" \
  --exclude="plantbackend/annotation_dataset/" \
  --exclude="plantbackend/training_runs/" \
  "$ROOT_DIR/" "$STAGE_DIR/"

mkdir -p \
  "$STAGE_DIR/plantbackend/annotation_datasets" \
  "$STAGE_DIR/plantbackend/training_runs" \
  "$STAGE_DIR/runtime"

GIT_REF="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")"

cat > "$STAGE_DIR/PACKAGE_INFO.txt" <<EOF
Package: $PACKAGE_NAME
Built at: $(date -Iseconds)
Git ref: $GIT_REF

Included:
- Frontend source and built dist assets
- FastAPI backend source
- Docker deployment files
- Existing model assets and training base weights

Excluded local-only data:
- Virtual environments
- node_modules and test reports
- Local auth databases
- Local annotation datasets and training runs
- Local env files such as deploy/backend.env

Quick start:
1. cd deploy
2. cp backend.env.example backend.env
3. docker compose -f compose.prod.yml up --build
EOF

echo "[3/4] Creating archives"
(
  cd "$RELEASES_DIR"
  tar -czf "${PACKAGE_NAME}.tar.gz" "$PACKAGE_NAME"
)

python3 - "$RELEASES_DIR" "$PACKAGE_NAME" <<'PY'
import shutil
import sys
from pathlib import Path

releases_dir = Path(sys.argv[1])
package_name = sys.argv[2]
shutil.make_archive(str(releases_dir / package_name), "zip", root_dir=releases_dir, base_dir=package_name)
PY

(
  cd "$RELEASES_DIR"
  sha256sum "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}.zip" > "${PACKAGE_NAME}.sha256"
)

rm -rf "$STAGE_DIR"

echo "[4/4] Done"
echo "Created:"
echo "  $RELEASES_DIR/${PACKAGE_NAME}.tar.gz"
echo "  $RELEASES_DIR/${PACKAGE_NAME}.zip"
echo "  $RELEASES_DIR/${PACKAGE_NAME}.sha256"
