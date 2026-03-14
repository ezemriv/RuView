# RuView Home Security — Project Status

## Current State
A fully operational home alarm system running in Docker on a local Mac. The Rust sensing server (`wifi-densepose-sensing-server`) serves HTTP on port 3000 and WebSocket on 3001. A Python Telegram alerter (`scripts/telegram_alert.py`) runs as a sidecar process inside the same container, polls `/api/v1/sensing/latest` every 5 seconds, and sends Telegram messages on presence transitions. The bot supports **Arm / Disarm / Status inline keyboard buttons** — the system starts disarmed so normal household movement doesn't trigger alerts. As of 2026-03-14, the system is **running in ESP32 mode with real CSI data** — a Freenove ESP32-S3-WROOM Board Lite is connected to WiFi (MiFibra-DA52, IP 192.168.1.36), sends CSI data via UDP to port 5005. The Docker image (`ruview-telegram`) is built with `uv` for Python runtime (no apt-python) and `--restart unless-stopped` for persistence across reboots.

## Completed

### 2026-03-14 — ESP32 hardware fully operational
- **Acquired & flashed Freenove ESP32-S3-WROOM Board Lite** with CSI firmware
- **Fixed firmware boot crash** by adding `CONFIG_ESP_WIFI_CSI_ENABLED=y` to `sdkconfig.defaults` (was missing, caused "CSI not enabled in menuconfig!" at `csi_collector.c:219`)
- **Discovered dual USB-C ports**: OTG (flashing only) vs UART (serial output); installed CH343 driver from WCH for UART port (`/dev/cu.wchusbserial*`)
- **Built firmware in Docker** with proper build flow: `rm -f sdkconfig && idf.py set-target esp32s3 && idf.py build` (cleaned generated config so defaults take effect)
- **Flashed firmware via UART** using esptool.py with correct partition offsets
- **ESP32 successfully connects** to home WiFi (MiFibra-DA52), obtains DHCP IP (192.168.1.36), sends UDP CSI frames to port 5005
- **Verified sensing server receives real CSI data** — presence classification working without simulation mode
- **Fixed Docker entrypoint**: CSI_SOURCE env var is ignored; must explicitly pass `/app/scripts/start_esp32.sh` as container command
- **Identified non-critical watchdog issue**: `edge_dsp` task triggers task_wdt warnings due to oversensitive fall detection threshold (2.0); logged for future calibration
- **Tracked sdkconfig.defaults in git** (removed from .gitignore) — this file is load-bearing for the build

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
1. **Calibrate presence thresholds** — tune `CLEAR_DELAY` (currently 60s) and possibly add a confidence threshold filter on `classification.confidence`; also tune fall detection threshold to reduce watchdog spam
2. **VPS deployment** — if you want the alarm to work while Mac is off; requires WireGuard tunnel due to CGNAT. Hetzner CAX11 recommended. Will need to run sensing server + Telegram bot on VPS, receive CSI from ESP32 via tunnel.
3. **(Optional) Provision ESP32 with fixed IP** — run `provision.py` with target IP set to a static local IP (currently DHCP 192.168.1.36)
4. **(Optional) Camera integration** — add a snapshot URL to the motion alert message
5. **(Optional) Multi-room setup** — add a second ESP32 in another room, run separate or mesh together

## Key Files & Commands
| What | Where / Command |
|------|----------------|
| Telegram alerter | `scripts/telegram_alert.py` |
| Docker entrypoint (sim) | `scripts/start.sh` |
| Docker entrypoint (esp32) | `scripts/start_esp32.sh` |
| Dockerfile | `Dockerfile` |
| Credentials | `.env` (gitignored) |
| Firmware config | `firmware/esp32-csi-node/sdkconfig.defaults` (tracked in git) |
| Run container (sim) | `docker run -d --name ruview-alarm --restart unless-stopped --env-file .env -p 3000:3000 -p 3001:3001 -p 5005:5005/udp ruview-telegram` |
| Run container (esp32) | `docker run -d --name ruview-alarm --restart unless-stopped --env-file .env -p 3000:3000 -p 3001:3001 -p 5005:5005/udp ruview-telegram /app/scripts/start_esp32.sh` |
| Stop container | `docker stop ruview-alarm && docker rm ruview-alarm` |
| View logs | `docker logs ruview-alarm` |
| Rebuild image | `docker build -t ruview-telegram -f Dockerfile .` |
| Build firmware | `docker run --rm -v $(pwd)/firmware/esp32-csi-node:/project -w /project espressif/idf:v5.2 bash -c "rm -f sdkconfig && idf.py set-target esp32s3 && idf.py build"` |
| Flash firmware | `esptool.py --chip esp32s3 --port /dev/cu.wchusbserial58FA0422681 --baud 460800 write_flash 0x0 firmware/esp32-csi-node/build/bootloader/bootloader.bin 0x8000 firmware/esp32-csi-node/build/partition_table/partition-table.bin 0xf000 firmware/esp32-csi-node/build/ota_data_initial.bin 0x20000 firmware/esp32-csi-node/build/esp32-csi-node.bin` |
| Live UI | http://localhost:3000/ui/index.html |
| Sensing API | http://localhost:3000/api/v1/sensing/latest |
| Serial monitor | `screen /dev/cu.wchusbserial58FA0422681 115200` (requires CH343 driver) |

## Notes & Decisions
- **uv instead of pip/python3**: `uv run` is used in start scripts; uv manages its own Python 3.12 install. No system Python needed in the Docker image.
- **Polling vs WebSocket**: Using 5s REST polling (simple, reliable). WebSocket push is available on port 3001 for lower latency if ever needed.
- **Disarmed by default**: Bot starts disarmed — you must press "Arm" in Telegram before leaving home. Prevents false alerts during normal use.
- **ESP32 board**: Freenove ESP32-S3-WROOM Board Lite has two USB-C ports. OTG (flashing) and UART (serial output). Serial output requires CH343 driver from WCH — without it, `screen /dev/cu.usbmodem*` will not show logs. Install driver, restart Mac, use `/dev/cu.wchusbserial*`.
- **Firmware config in git**: `sdkconfig.defaults` is tracked; the generated `sdkconfig` is ignored. Must delete `sdkconfig` before building so defaults take effect.
- **Docker entrypoint**: CSI_SOURCE env var does NOT work. Must explicitly pass `/app/scripts/start_esp32.sh` as the command to run ESP32 mode.
- **CGNAT warning**: Your public IP and local IP differ. Direct port-forwarding to the internet won't work without a VPN/tunnel (e.g. WireGuard). For pure local use this doesn't matter.
- **Telegram bot token**: In `.env` — never commit this file. The `.env` is already in `.gitignore`.
- **Watchdog warnings**: `edge_dsp` task triggers task_wdt spam due to fall detection threshold (2.0) being too sensitive. Non-critical but noisy; tune threshold in future.
- **Branch**: `main` (ESP32 work merged from `home-security-telegram`)
