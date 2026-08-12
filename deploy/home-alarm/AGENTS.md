# Home alarm contributor notes

## Package map

- `src/ruview_alarm/`: Telegram alarm service, authenticated sensing client, durable state,
  and the fail-closed alarm healthcheck.
- `tests/`: unit/integration tests; `test_container_smoke.py` is the optional container gate.
- `scripts/provision_esp32.py`: interactive ESP32-S3 NVS-only Wi-Fi/VPS configuration wrapper.
- `compose.yaml`: pinned sensing image and alarm deployment contract.

## Commands

```bash
uv run pytest -v -m 'not container'
uv run ruff check src tests scripts
uv run --extra provision python scripts/provision_esp32.py --help
docker compose config
```

Run the provisioning helper only while physically present at the confirmed board. It accepts
the serial port, SSID, literal VPS IPv4, and node ID; it prompts for the Wi-Fi password and
rewrites only the ESP32 NVS partition through the upstream provisioner.

## Safety boundaries

- Keep `.env` and `.env.*` untracked; only `.env.example` and test fixtures may be committed.
- Keep the sensing image digest pinned. Build the firmware with the documented display-less
  `espressif/idf:v5.4` command and record artifact hashes before flashing.
- Software tests and Docker health are not hardware acceptance. Require serial boot output and
  authenticated end-to-end ESP32 sensing evidence before claiming a device is operational.
- The sensing container healthcheck, `kill -0 1`, establishes only process liveness; it does
  not establish API readiness. Check `/health` and authenticated latest sensing separately.
