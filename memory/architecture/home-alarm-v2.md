# Home Alarm v2

## Status Routing

This file stores durable architecture, not progress. The only living status and
next-step checklist is `docs/status/home-alarm-v2.md`; execute and mark its
steps one at a time.

## Purpose

`deploy/home-alarm/` is a restart-safe Python sidecar and pinned Docker Compose deployment around upstream RuView. It polls authenticated sensing, accepts Telegram control from one configured chat, persists alarm state atomically, and supervises sensing, Telegram polling, notification delivery, and watchdog heartbeat loops.

## Durable Boundaries

- Upstream Rust sensing and firmware algorithms remain unchanged.
- Production RuView uses the immutable digest recorded in the approved design and Compose file; never substitute `latest`.
- Persistent state is strict and unambiguous: missing state defaults disarmed, but corrupt, incomplete, coercive, duplicate-key, extra-key, or unsupported state terminates startup.
- Telegram callback acknowledgement is bounded and best-effort after durable state save; it must not wedge polling or falsely refresh Telegram liveness.
- Production Compose validation uses `docker compose config --quiet` so resolved tokens are not rendered.
- ESP32 provisioning is interactive TTY-only, prompts for the Wi-Fi password, confirms the exact port, writes NVS only, and isolates upstream temporary artifacts.

## Evidence Model

- Levels 1–2 cover locked dependencies, unit/service integration, lint, and Compose contracts.
- Level 3 deliberately separates two paths:
  - `MEASURED`: immutable RuView image pin, bearer boundary, honest non-ESP32 simulation source, port restrictions, container configuration, and cleanup.
  - `SYNTHETIC`: alarm-originated bearer polling of a clearly named fake ESP32-shaped service, intrusion/all-clear lifecycle, and restart-safe armed restoration.
- Level 4 is not software-complete evidence. It requires operator-controlled physical ESP32, redacted serial/runtime logs, VPS/firewall deployment, live sensing and Telegram checks, restart restoration, and rollback proof.

## Where to Start

- Current state and next steps: `docs/status/home-alarm-v2.md`
- Scoped rules: `deploy/home-alarm/AGENTS.md`
- Operator runbook: `deploy/home-alarm/README.md`
- Approved design: `docs/superpowers/specs/2026-08-12-home-alarm-v2-design.md`
- Executable plan: `docs/superpowers/plans/2026-08-12-home-alarm-v2.md`
- Current software evidence: `deploy/home-alarm/verification/software-verification.md`
- Level 4 evidence record: `deploy/home-alarm/verification/level4-acceptance.md`

## Validation

Run from `deploy/home-alarm/`:

```bash
uv sync --frozen --all-extras --dev
uv run pytest -v -m 'not container'
uv run ruff check src tests scripts
docker compose --env-file tests/fixtures/compose.env config --quiet
uv run pytest tests/test_container_smoke.py -v -m container
```

The container gate requires Docker and must not be treated as passing when skipped. Never stop or reuse unrelated operator containers during smoke verification.
