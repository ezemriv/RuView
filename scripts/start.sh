#!/bin/sh
# Start Telegram alerter in background, then run sensing server in simulation mode
uv run /app/scripts/telegram_alert.py &
exec /app/sensing-server --source simulate --http-port 3000 --ws-port 3001 --bind-addr 0.0.0.0 --ui-path /app/ui
