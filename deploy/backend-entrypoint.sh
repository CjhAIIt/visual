#!/bin/sh
set -eu

mkdir -p \
  /app/plantbackend/models \
  /app/plantbackend/annotation_datasets \
  /app/plantbackend/training_runs \
  /app/plantbackend/runtime

if [ -d /opt/plantbackend-seed/models ] && [ -z "$(ls -A /app/plantbackend/models 2>/dev/null)" ]; then
  cp -a /opt/plantbackend-seed/models/. /app/plantbackend/models/
fi

exec uvicorn plantbackend.asgi:app --host 0.0.0.0 --port 7800
