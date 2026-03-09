#!/bin/sh
# Use this script on the VPS once your ESP32 is configured
# Start Telegram alerter in background, then run sensing server with ESP32 source
uv run /app/scripts/telegram_alert.py &
exec /app/sensing-server --source esp32 --http-port 3000 --ws-port 3001 --bind-addr 0.0.0.0 --ui-path /app/ui
