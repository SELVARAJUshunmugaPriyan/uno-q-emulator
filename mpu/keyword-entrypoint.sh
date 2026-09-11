#!/bin/sh
set -eu

mkdir -p /home/arduino/.arduino-bricks/ei-models /home/arduino/ArduinoApps/hey_dragon/python
if [ ! -f /home/arduino/ArduinoApps/hey_dragon/python/main.py ]; then
  cp /opt/uno-q/app/main.py /home/arduino/ArduinoApps/hey_dragon/python/main.py
fi
chown -R arduino:arduino /home/arduino
exec /usr/sbin/sshd -D -e

