# RuView Home Security — Project Status

## Current State
A working home alarm system running in Docker on a local Mac. The Rust sensing server (`wifi-densepose-sensing-server`) serves HTTP on port 3000 and WebSocket on 3001. A Python Telegram alerter (`scripts/telegram_alert.py`) runs as a sidecar process inside the same container, polls `/api/v1/sensing/latest` every 5 seconds, and sends Telegram messages on presence transitions. The bot supports **Arm / Disarm / Status inline keyboard buttons** — the system starts disarmed so normal household movement doesn't trigger alerts. Currently running in **simulation mode** (synthetic CSI data) — real detection requires an ESP32 with CSI firmware connected via UDP on port 5005. The Docker image (`ruview-telegram`) is built with `uv` for Python runtime (no apt-python) and `--restart unless-stopped` for persistence across reboots.

## Completed

### 2026-03-09 — Full local setup on `home-security-telegram` branch
- Verified environment: Docker v29.1.3, uv 0.8.17, Python 3.12, Git 2.52.0
- Detected CGNAT (public IP ≠ local IP — noted for future VPS/ESP32 setup)
- Created Telegram bot, retrieved chat ID (`6387049495`) via getUpdates API
- Created `scripts/telegram_alert.py` — polls REST API, tracks presence transitions, sends arm/disarm alerts with inline keyboard buttons
- Created `scripts/start.sh` (simulation mode) and `scripts/start_esp32.sh` (ESP32 mode)
- Created `Dockerfile` — multi-stage: Rust builder + uv Python runtime, no apt-python
- Fixed: `presence` field is nested under `classification` in the API response
- Fixed: server must bind to `0.0.0.0` (not `127.0.0.1`) to be reachable from host
- Fixed: scripts use `uv run` instead of `python3` (uv manages Python, no system python needed)
- Added arm/disarm state machine with threading — bot listens for Telegram commands in background
- Enhanced motion alert message with emoji and "INTRUSION ALERT" header
- Deployed locally with `--restart unless-stopped` (survives Mac reboots if Docker Desktop starts on login)
- Tested: startup Telegram message received, arm/disarm buttons work, motion alert fires when armed

## Next Steps
1. **Buy ESP32** and flash with CSI firmware from `firmware/esp32-csi-node/` — this enables real WiFi-based motion detection instead of simulation
2. **Provision ESP32** — run `provision.py` with target IP set to Mac's local IP (`192.168.1.23`), port 5005
3. **Switch to esp32 mode** — run container with `start_esp32.sh` or `-e CSI_SOURCE=esp32`
4. **Calibrate presence thresholds** — tune `CLEAR_DELAY` (currently 60s) and possibly add a confidence threshold filter on `classification.confidence`
5. **(Optional) VPS deployment** — if you want the alarm to work while Mac is off; requires WireGuard tunnel due to CGNAT. Hetzner CAX11 recommended.
6. **(Optional) Camera integration** — add a snapshot URL to the motion alert message

## Key Files & Commands
| What | Where / Command |
|------|----------------|
| Telegram alerter | `scripts/telegram_alert.py` |
| Docker entrypoint (sim) | `scripts/start.sh` |
| Docker entrypoint (esp32) | `scripts/start_esp32.sh` |
| Dockerfile | `Dockerfile` |
| Credentials | `.env` (gitignored) |
| Run container | `docker run -d --name ruview-alarm --restart unless-stopped --env-file .env -p 3000:3000 -p 3001:3001 -p 5005:5005/udp ruview-telegram` |
| Stop container | `docker stop ruview-alarm && docker rm ruview-alarm` |
| View logs | `docker logs ruview-alarm` |
| Rebuild image | `docker build -t ruview-telegram -f Dockerfile .` |
| Live UI | http://localhost:3000/ui/index.html |
| Sensing API | http://localhost:3000/api/v1/sensing/latest |

## Notes & Decisions
- **uv instead of pip/python3**: `uv run` is used in start scripts; uv manages its own Python 3.12 install. No system Python needed in the Docker image.
- **Polling vs WebSocket**: Using 5s REST polling (simple, reliable). WebSocket push is available on port 3001 for lower latency if ever needed.
- **Disarmed by default**: Bot starts disarmed — you must press "Arm" in Telegram before leaving home. Prevents false alerts during normal use.
- **CGNAT warning**: Your public IP and local IP differ. Direct port-forwarding to the internet won't work without a VPN/tunnel (e.g. WireGuard). For pure local use this doesn't matter.
- **Telegram bot token**: In `.env` — never commit this file. The `.env` is already in `.gitignore`.
- **Branch**: `home-security-telegram` (off `main`)
