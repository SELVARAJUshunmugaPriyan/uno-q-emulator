#!/bin/sh
set -eu

mkdir -p /home/arduino/.arduino-bricks/ei-models /home/arduino/ArduinoApps/hey_dragon/python
chown -R arduino:arduino /home/arduino
ssh-keygen -A
exec supervisord -n -c /etc/supervisor/supervisord.conf

