# CLAUDE.md — RuView Home Security Fork

**Owner:** Ezequiel Rivero ([@ezemriv](https://github.com/ezemriv))
**Fork of:** [ruvnet/RuView](https://github.com/ruvnet/RuView)
**Purpose:** WiFi-based home presence detection + Telegram alarm system

---

## What This Fork Does

This is a personal fork of RuView adapted as a home security alarm system. The core Rust sensing server is unchanged. The additions are:

- **Telegram alerter** (`scripts/telegram_alert.py`) — polls the sensing API and sends alerts
- **Arm/disarm via Telegram inline keyboard buttons** — system starts disarmed
- **Docker entrypoints** (`scripts/start.sh`, `scripts/start_esp32.sh`)
- **Custom Dockerfile** — multi-stage build, uv-managed Python (no apt-python)

**Always read `PROJECT_STATUS.md` first** when resuming work — it tracks current state, what's done, and next steps.

---

## Project Structure (what I care about)

```
scripts/
  telegram_alert.py   # Telegram bot + presence alerter
  start.sh            # Docker entrypoint — simulation mode
  start_esp32.sh      # Docker entrypoint — real ESP32 mode
Dockerfile            # Multi-stage: Rust builder + uv Python runtime
.env                  # Telegram credentials (gitignored, never commit)
PROJECT_STATUS.md     # Session journal — read this when resuming
```

The upstream Rust crates, firmware, and Python v1 code are preserved as-is.

---

## Running Locally

```bash
# Build
docker build -t ruview-telegram -f Dockerfile .

# Run (simulation mode, auto-restart)
docker run -d --name ruview-alarm --restart unless-stopped \
  --env-file .env \
  -p 3000:3000 -p 3001:3001 -p 5005:5005/udp \
  ruview-telegram

# Run (ESP32 mode — hardware connected, see Hardware section below)
docker run -d --name ruview-alarm --restart unless-stopped \
  --env-file .env \
  -p 3000:3000 -p 3001:3001 -p 5005:5005/udp \
  ruview-telegram /app/scripts/start_esp32.sh

# Logs / stop
docker logs ruview-alarm
docker stop ruview-alarm && docker rm ruview-alarm
```

---

## Telegram Bot

- **Arm / Disarm / Status** via inline keyboard buttons (or `/arm`, `/disarm`, `/status` commands)
- System starts **disarmed** — press Arm before leaving home
- Motion alert: fires on `presence` transition false → true (with 60s clear delay)
- Credentials stored in `.env` (gitignored)

---

## Development Rules

- **Never commit `.env`** — credentials stay local
- **Always use `uv run`** for Python — uv manages Python 3.12, no system python needed
- **Run `/update-status`** after any meaningful work session to keep `PROJECT_STATUS.md` current
- Keep changes on `home-security-telegram` branch; merge to `main` via PR
- Don't touch upstream Rust crates or firmware unless intentionally upgrading from upstream

---

## Key API Endpoints (sensing server)

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Server health |
| `GET /api/v1/sensing/latest` | Latest CSI frame — `classification.presence` is the alarm field |
| `GET /api/v1/info` | Server info |
| `ws://localhost:3001/ws/sensing` | WebSocket push (100ms tick) |
| `http://localhost:3000/ui/index.html` | Live UI |

---

## Hardware (working as of 2026-03-14)

**Freenove ESP32-S3-WROOM Board Lite** successfully connected to home network (MiFibra-DA52), sends real CSI data via UDP to port 5005.

### Hardware Setup

The board has TWO USB-C ports:
- **OTG port** (labeled "OTG"): works for flashing, NOT for serial monitor
- **UART port** (labeled "RX/TX"): for ESP_LOG serial output, requires CH343 driver

**To see serial monitor output:**
1. Install CH343 driver from [WCH](http://www.wch.cn/downloads/CH343SER_MAC_ZIP.html)
2. Restart Mac
3. Serial output appears on `/dev/cu.wchusbserial*` (not `/dev/cu.usbmodem*`)

### Firmware Build & Flash

**Build firmware in Docker** (run from repo root):
```bash
docker run --rm -v $(pwd)/firmware/esp32-csi-node:/project -w /project espressif/idf:v5.2 \
  bash -c "rm -f sdkconfig && idf.py set-target esp32s3 && idf.py build"
```

**Flash via UART port** (replace `/dev/cu.wchusbserial58FA0422681` with your actual device):
```bash
esptool.py --chip esp32s3 --port /dev/cu.wchusbserial58FA0422681 --baud 460800 write_flash \
  0x0 firmware/esp32-csi-node/build/bootloader/bootloader.bin \
  0x8000 firmware/esp32-csi-node/build/partition_table/partition-table.bin \
  0xf000 firmware/esp32-csi-node/build/ota_data_initial.bin \
  0x20000 firmware/esp32-csi-node/build/esp32-csi-node.bin
```

**Note:** `sdkconfig.defaults` contains `CONFIG_ESP_WIFI_CSI_ENABLED=y` and is tracked in git. Must delete the generated `sdkconfig` before building so the defaults take effect.

### Running with ESP32

**Docker run command** (NOT using `CSI_SOURCE` env var — that is ignored):
```bash
docker run -d --name ruview-alarm --restart unless-stopped \
  --env-file .env \
  -p 3000:3000 -p 3001:3001 -p 5005:5005/udp \
  ruview-telegram /app/scripts/start_esp32.sh
```

The `start_esp32.sh` script disables simulation mode and listens on UDP 5005 for real CSI frames.

### Known Issues

- **Task watchdog warnings** on CPU 1 from `edge_dsp` task — "Fall detected" spam indicates fall detection threshold (2.0) is too sensitive for normal CSI variance. Non-critical, but noisy.

**CGNAT note:** Public IP ≠ local IP on this network. Port-forwarding to internet requires WireGuard tunnel. Not needed for local-only use.

---

## Branch

- `main` — stable, merged changes
- `home-security-telegram` — active feature branch (first big addition)

---

## Syncing with Upstream

To pull in updates from the original `ruvnet/RuView` repo:

```bash
gh repo sync ezemriv/RuView --source ruvnet/RuView --branch main
git pull origin main
```

Run this occasionally to pick up upstream Rust/firmware improvements without losing local changes.

---

## Session Resume

**Always read `PROJECT_STATUS.md` before starting any work.** It contains:
- What was last completed and when
- Exact current state of the system
- Next steps ordered by priority
- Quick-reference commands

After finishing any meaningful work, run `/update-status` to keep it current.
