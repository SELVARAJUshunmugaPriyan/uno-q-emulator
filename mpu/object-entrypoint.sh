#!/bin/sh
set -eu

APP_DIR=/opt/uno-q/app/object-detection
APP_FILE="$APP_DIR/python/main.py"

if [ ! -f "$APP_FILE" ]; then
    echo "Object-detection app not found: $APP_FILE" >&2
    exit 1
fi

mkdir -p \
    /home/arduino/.arduino-bricks \
    /home/arduino/ArduinoApps/object-detection

chown -R arduino:arduino /home/arduino

cd "$APP_DIR"

exec su -s /bin/sh arduino -c \
    "cd '$APP_DIR' && exec python3 '$APP_FILE'"