# Home Alarm Level 4 Acceptance Record

**Sequencing authority:** [`docs/status/home-alarm-v2.md`](../../../docs/status/home-alarm-v2.md)
**Operator runbook:** [`deploy/home-alarm/README.md`](../README.md)

This tracked file is the canonical redacted evidence record for physical
ESP32/VPS acceptance. It is not the task tracker: execute and mark only the
first unchecked step in the sequencing authority above.

## Evidence rules

- Record hashes, non-sensitive target identifiers, timestamps, command
  outcomes, and redacted excerpts only.
- Never record tokens, passwords, chat IDs, private CSI, full environment
  dumps, or raw firewall/configuration output containing sensitive values.
- Use documentation-range addresses in examples. For a real address, record
  only that the application and firewall `/32` matched; keep the value in the
  operator-controlled system.
- Append evidence to a section only when its corresponding canonical checklist
  step is active. Update this record and that checkbox together.
- A build, simulator, skipped gate, or software smoke test cannot satisfy a
  hardware acceptance item.

## Step 2 evidence — operator inputs and authority

Record, when authorized:

- date/time plus a non-personal operator-role label or redacted approval
  reference;
- board model and non-sensitive confirmed UART identifier;
- explicit read-only probe and flash authorization outcomes.

### Discovery — 2026-08-12T17:11:57Z

- Operator role: repository owner (identity not recorded).
- `serial.tools.list_ports` found only Bluetooth and macOS debug devices; no
  ESP32 USB/UART identifier was available.
- Board model and flash capacity: unconfirmed.
- Full-flash authorization: not yet granted.
- VPS SSH/firewall authority: not yet confirmed.
- Production mode-`0600` environment file: not yet created or inspected.
- No hardware, credential, firewall, VPS, or deployment mutation occurred.

### UART connection — 2026-08-12T17:19:24Z

- The board was connected through its port labeled `USB UART` using a
  data-capable cable.
- Confirmed macOS UART identifier: `/dev/cu.wchusbserial58FA0422681`.
- USB bridge identity: `USB Single Serial`, WCH VID:PID `1A86:55D3`.
- Board model and flash capacity remain unconfirmed because the bridge
  identity is not sufficient to establish them.
- No serial query, reset, erase, flash, provisioning, or credential action was
  performed.

### Packaging and read-only probe — 2026-08-12T17:23:20Z

- Packaging identification: Freenove ESP32-S3-WROOM Board Lite, product code
  `FNK0099`, revision marking `A` (`A1B0` packaging mark).
- The source packaging photo was inspected locally but not retained. Its box
  serial number and barcode were omitted.
- Authorized `esptool` probe: ESP32-S3 QFN56 revision 0.2, 40 MHz crystal,
  8 MB embedded PSRAM, 8 MB quad flash at 3.3 V.
- Confirmed UART: `/dev/cu.wchusbserial58FA0422681`.
- The probe-reported unique chip address was not recorded.
- Read-only probes completed and hard-reset the board; no erase, write,
  provisioning, or credential action occurred.
- The operator authorized replacing the firmware after final board/UART/flash
  command confirmation.
- The operator controls the VPS but explicitly deferred VPS work to Step 4.

## Step 3 evidence — firmware and ESP32-S3

Record, when authorized:

- pinned RuView commit and ESP-IDF image/version;
- SHA-256 for bootloader, partition table, OTA data, and application binary;
- exact flash offsets/command derived from the pinned build output;
- re-confirmed board/UART target and flash outcome;
- redacted serial boot evidence.

### Pinned build — 2026-08-12T17:28:00Z

- Firmware source commit: `54384cba` (no firmware source change afterward).
- Build image: `espressif/idf:v5.4`, resolved image digest
  `sha256:f1e9f69dc052b9afc7801ca884e0ef40c17e014bb05ce73d9c09d29290bd17fb`.
- Target/defaults: `esp32s3` with
  `sdkconfig.defaults;sdkconfig.defaults.devkitc`; display support disabled.
- Build result: PASS; application size `0xde590`, with 57% of the smallest
  application partition free.
- Optional WASM3 source was absent, so Tier 3 WASM support was omitted. The
  Home Alarm CSI path does not require it.
- Existing compiler warning: unused local `data_type` in `mmwave_sensor.c`.
- Generated `build/`, `sdkconfig`, managed components, and dependency lock are
  ignored artifacts; no tracked firmware file changed.

SHA-256:

```text
d0776468f70e9a44cb3bb746fc130d780e4f110396f4fde08c33ff29f30b9cec  bootloader.bin
67222c257c0477501fd4002275638dc4262b34eb68235b8289fb1337054d322b  partition-table.bin
7d2c7ac4888bfd75cd5f56e8d61f69595121183afc81556c876732fd3782c62f  ota_data_initial.bin
cac28dab4f207818721ba82f63816ca51ab637c1afbc5209c1397c278f8a0514  esp32-csi-node.bin
```

Build-derived flash settings and offsets: DIO, 8 MB, 80 MHz;
bootloader `0x0`, partition table `0x8000`, OTA data `0xf000`, application
`0x20000`.

Exact build-derived command executed from `deploy/home-alarm` after final
target confirmation:

```bash
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv run python -m esptool \
  --chip esp32s3 --port /dev/cu.wchusbserial58FA0422681 --baud 460800 \
  --before default_reset --after hard_reset write_flash \
  --flash_mode dio --flash_size 8MB --flash_freq 80m \
  0x0 ../../firmware/esp32-csi-node/build/bootloader/bootloader.bin \
  0x8000 ../../firmware/esp32-csi-node/build/partition_table/partition-table.bin \
  0xf000 ../../firmware/esp32-csi-node/build/ota_data_initial.bin \
  0x20000 ../../firmware/esp32-csi-node/build/esp32-csi-node.bin
```

### Clean flash and boot — 2026-08-12T17:31:47Z

- Final target confirmation: granted for Freenove `FNK0099`, ESP32-S3
  revision 0.2, 8 MB flash, and UART `/dev/cu.wchusbserial58FA0422681`.
- Immediately before mutation, the read-only probe reconfirmed the target and
  all four binary hashes matched the values above.
- The operator explicitly requested the cleanest installation and authorized
  complete reset of the purpose-bought board.
- `esptool erase-flash`: PASS; the entire flash was erased successfully in
  3.9 seconds.
- The recorded four-offset command: PASS; bootloader, partition table, OTA
  data, and application were written, read-back hashes verified, and the board
  hard-reset.
- The command used accepted esptool compatibility spellings that emitted only
  deprecation warnings; no write or verification failure occurred.
- Redacted bounded serial outcome: display-less firmware initialized the
  MGMT+DATA CSI collector, edge tier 2, OTA service, adaptive controller, and
  CSI streaming path; live CSI callbacks were observed.
- Wi-Fi association and UDP sends failed as expected after the clean erase
  because production NVS settings are intentionally deferred until Step 5.
- Optional WASM Tier 3 remained disabled as recorded at build time; CSI-only
  Home Alarm operation was active.
- No raw serial log, MAC address, credential, private CSI, or other unique
  identifier was retained.
- Step 3 verdict: PASS for clean build/hash/full-flash/boot. This is not VPS or
  end-to-end acceptance.

## Step 4 evidence — VPS deployment and network closure

Record, when authorized:

- VPS SSH/firewall authorization outcome;
- mode-`0600` production environment-file check outcome without values;
- pinned image/configuration identifiers and Compose command outcomes;
- temporary discovery opening start/end and removal outcome;
- confirmation that `RUVIEW_UDP_ALLOW` and the firewall use the same home
  `/32`, without recording the real address; and
- proof that no broad discovery/firewall rule remains.

### VPS deployment and network closure — 2026-08-13T06:21:17Z

- Direct SSH and VPS firewall authority were confirmed through the
  operator-controlled terminal; no operator identity was recorded.
- The production `.env` was created with mode `0600`; the four
  required key names were verified. Values were not displayed or recorded,
  and the file remains ignored by Git.
- `docker compose config --quiet`, `docker compose pull`,
  `docker compose build --pull`, and `docker compose up -d`: PASS.
- Pinned sensing image:
  `docker.io/ruvnet/wifi-densepose@sha256:fac235102bebc8a9bfc5445645bc6908d02cf0244154e59b7bab297a574b5fae`.
- Fresh Compose checks: `compose_services_healthy=true` for
  `sensing-server` and `telegram-alarm`. Authenticated `/health` and
  `/api/v1/sensing/latest` returned HTTP 200
  (`authenticated_health=true`, `authenticated_latest=true`), and an
  unauthenticated latest request was rejected
  (`unauthenticated_latest_rejected=true`). These are VPS
  deployment-boundary checks, not proof of live ESP32 sensing.
- Fresh listener checks: `tcp3000_loopback_only=true` and
  `udp5005_listener=true`.
- Operator-attested redacted UFW verifier output was
  `ufw_active=true udp5005_lines=1 exact_source_lines=1 broad_lines=`. The
  empty `broad_lines=` field means zero matches. Thus one exact UDP/5005
  source rule matched the application `/32` internally
  (`same_home_/32_match=true`), with no broad or discovery rule remaining
  (`no_broad_or_discovery_rule=true`); the real address is intentionally
  omitted.
- No temporary discovery opening was used
  (`temporary_discovery_rule=false`): the direct SSH `SSH_CONNECTION` source
  supplied the home egress address. The same `/32` was used for
  `RUVIEW_UDP_ALLOW` and UFW.
- Both Hermes gateways remained active/running with unchanged `NRestarts=0`
  (`hermes_preserved=true`). The unrelated `camofox-browser` remained running
  with its loopback endpoint healthy (`camofox_preserved=true`) and was not
  modified.
- Step 4 verdict: PASS for VPS deployment and network-boundary closure. Step 5
  NVS provisioning, live ESP32 sensing, Telegram lifecycle checks, restart
  restoration, and rollback remain pending.

## Step 5 evidence — live lifecycle, restoration, and rollback

Record, when authorized:

- NVS provisioning outcome;
- redacted serial evidence of DHCP and UDP sends;
- live health reports `source: esp32` and advancing tick/latest-data outcomes;
- authorized and unauthorized Telegram control outcomes;
- arm, intrusion, continuous-absence all-clear, and offline/recovery outcomes;
- alarm-container and VPS restart restoration outcomes;
- rollback identifiers, procedure outcome, and repeated post-rollback checks;
  and
- redacted serial/end-to-end evidence references.

## Final Level 4 verdict

Level 4 may be marked `PASS` only after Steps 2–5 are complete with no open
blocker and the canonical status checklist is updated in the same closeout.
Until then, this section intentionally contains no verdict; completion state
lives only in `docs/status/home-alarm-v2.md`.
