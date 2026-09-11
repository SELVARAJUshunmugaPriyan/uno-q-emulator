#!/bin/sh
set -eu

MODEL_PATH=${1:-}

if [ -z "$MODEL_PATH" ]; then
    echo "Usage: run-model.sh models/<exercise>/<model>.eim" >&2
    exit 2
fi

if [ ! -f "$MODEL_PATH" ]; then
    echo "Model not found: $MODEL_PATH" >&2
    exit 1
fi

case "$MODEL_PATH" in
    models/*)
        MODEL_RELATIVE=${MODEL_PATH#models/}
        ;;
    *)
        echo "Model path must be inside models/: $MODEL_PATH" >&2
        exit 1
        ;;
esac

MODEL_CONTAINER_ROOT=${MODEL_CONTAINER_ROOT:-/models/custom}
RUNNER_SERVICE=${RUNNER_SERVICE:-runner}
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-uno-q-emulator}

export EIM_MODEL="$MODEL_CONTAINER_ROOT/$MODEL_RELATIVE"
export COMPOSE_PROJECT_NAME

echo "Runner service: $RUNNER_SERVICE"
echo "Model host path: $MODEL_PATH"
echo "Model container path: $EIM_MODEL"

exec docker compose up -d "$RUNNER_SERVICE"