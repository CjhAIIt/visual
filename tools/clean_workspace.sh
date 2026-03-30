#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

rm -rf \
  .codex-artifacts \
  .playwright-cli \
  .venv \
  .venv-linux \
  frontend/dist \
  frontend/test-results \
  plantbackend/.venv \
  plantbackend/.venv-linux \
  plantbackend/.venv_linux \
  plantbackend/__pycache__ \
  plantbackend/.vscode \
  video_frames

rm -f \
  plantbackend/auth.db \
  yolo_split_augmented.zip \
  yolo_split_augmented_with_classes.zip

find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
