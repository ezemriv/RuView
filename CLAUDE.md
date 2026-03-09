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

# Run (ESP32 mode — once hardware is connected)
docker run -d --name ruview-alarm --restart unless-stopped \
  --env-file .env \
  -p 3000:3000 -p 3001:3001 -p 5005:5005/udp \
  -e CSI_SOURCE=esp32 \
  ruview-telegram

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

## Hardware (future)

ESP32 with CSI firmware from `firmware/esp32-csi-node/`. When connected:
- Set target IP to Mac's local IP (`192.168.1.23`) in `provision.py`
- ESP32 sends UDP frames to port 5005
- Switch container to `CSI_SOURCE=esp32`

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
