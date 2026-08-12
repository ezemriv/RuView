# RuView Home Alarm v2 Design

**Status:** Implemented and Levels 1–3 verified on 2026-08-12

**Implementation outcome:** The implementation completed on
`codex/upstream-home-alarm-v2-implementation` through `cc66b478`. The dated
software evidence is in
`deploy/home-alarm/verification/software-verification.md`. This design is the
historical architectural contract; mutable status and the strictly sequential
integration/Level 4 checklist live only in
`docs/status/home-alarm-v2.md`. Do not re-execute its completed implementation
work.

## Goal

Deliver a maintainable home-presence alarm that receives CSI from one
Freenove ESP32-S3-WROOM Board Lite, evaluates RuView's presence result on a
Contabo VPS, and sends authenticated Telegram controls and alerts. The system
must survive service and VPS restarts without silently disarming.

Software verification is separate from hardware acceptance. Unit,
integration, and container checks can establish software behavior; only a
captured ESP32 boot/runtime log and an end-to-end walk-through can establish
real-hardware operation.

## Baseline and upgrade strategy

- Base the integration branch on upstream release `v2235`, commit
  `de27336fa1db971d4689fd2db19610e8a7966dee`.
- Keep the existing fork `main` unchanged as the historical rollback point.
- Run the upstream RuView container without source modifications. Resolve its
  multi-architecture manifest for commit `de27336...` and record the selected
  immutable image digest in the deployment configuration before deployment.
- Build ESP32-S3 firmware from the same pinned source commit with ESP-IDF 5.4
  and the display-less `sdkconfig.defaults.devkitc` overlay.
- Treat future upstream upgrades as deliberate version changes: update the
  pin, run all software gates, perform hardware acceptance, and only then
  deploy. Never track `latest` automatically.

This replaces the old design where Telegram and RuView shared one custom
container. Keeping them separate avoids carrying a permanent patch across
upstream reorganizations and lets each process restart independently.

## Architecture

```text
Freenove ESP32-S3
    |
    | UDP/5005 (CSI; source-IP restricted after cutover discovery)
    v
Contabo VPS
    +-- ruview-sensing container
    |      +-- HTTP/3000 on private Compose network
    |      +-- HTTP/3000 published on VPS loopback only
    |      +-- bearer-token protection
    |
    +-- telegram-alarm container
           +-- polls /health and /api/v1/sensing/latest
           +-- persists alarm state in a named volume
           +-- long-polls the Telegram Bot API
```

Only SSH and UDP port 5005 are publicly reachable. The RuView HTTP API is
published as `127.0.0.1:3000` for optional SSH-tunnel access and is also
reachable by the alarm service over a private Compose network. Port 3001 is
not published because the alarm does not use the WebSocket interface.

## Components

### Upstream sensing service

The `ruview-sensing` Compose service uses the pinned upstream image and runs
with the explicit ESP32 source. It binds HTTP to the container interface,
requires `RUVIEW_API_TOKEN`, binds CSI UDP to `0.0.0.0:5005`, and requires an
explicit source allowlist after source-IP discovery. Its HTTP port maps only
to VPS loopback.

The initial cutover may open UDP 5005 only long enough to observe the actual
CGNAT egress address of the home connection. Deployment then replaces the
temporary unrestricted setting with that single `/32` source address at both
the RuView allowlist and the VPS firewall. A later home-IP change fails closed
and is reported as sensor downtime. The allowlist reduces exposure but does
not authenticate UDP packets; source spoofing remains a protocol limitation.

### Telegram alarm service

The custom application is an independently built Python 3.12 service managed
with `uv`. It uses Pydantic settings for environment validation and an async
HTTP client for RuView and Telegram. It has four focused responsibilities:

1. Accept `/arm`, `/disarm`, `/status`, and equivalent inline-keyboard actions
   only from the configured Telegram chat ID.
2. Poll RuView every 5 seconds and read
   `classification.presence` only when `/health` reports source `esp32`.
3. Emit one intrusion notification on an absent-to-present transition while
   armed, then one all-clear notification after 60 continuous seconds without
   presence.
4. Detect loss and recovery of real sensing data and report each transition
   once.

The service uses bounded exponential retry delays of 1, 2, 4, 8, 16, and at
most 30 seconds for transient HTTP failures. A sensor is offline after 30
continuous seconds without a healthy ESP32 response. Recovery is recognized
on the first subsequent healthy response. Telegram delivery errors are logged
without secrets and retried; they never mutate alarm state.

If either long-polling or sensing supervision exits unexpectedly, the process
exits so Docker can restart the whole alarm service. The service must not
continue in a partially failed state.

### Persistent state

The alarm writes one versioned JSON document to a named Docker volume:

```json
{
  "version": 1,
  "armed": true,
  "telegram_offset": 123456789
}
```

Writes use a temporary file, `fsync`, atomic replacement, and directory
`fsync`. A missing state file creates a disarmed system. A valid saved file
restores both the last arm state and Telegram update offset. Invalid or
unsupported state makes the process fail closed instead of guessing.

Consequently, an armed installation restores as armed after a container or
VPS restart, while a new installation starts disarmed. Startup sends a status
message that makes the restored state explicit. If presence is already
detected after an armed restart, the normal transition logic produces an
intrusion alert.

### Secure ESP32 provisioning helper

A local helper wraps upstream's provisioner for the one-board home-alarm use
case. It:

- confirms the exact serial port and ESP32-S3 target;
- prompts for the Wi-Fi password without echoing it or placing it in shell
  history;
- requires SSID, VPS IPv4 address, UDP port 5005, and node ID together;
- invokes upstream provisioning in-process with a private temporary state
  directory, so the Wi-Fi password is not retained in upstream's per-port JSON
  state;
- flashes only the NVS partition at `0x9000` for a network/target change; and
- prints no credential values.

The helper never flashes unattended. Full firmware flashing remains a
separate, explicitly confirmed operation using offsets derived from the pinned
build, followed by a captured serial log.

## Configuration and secrets

The committed example environment documents these required values without
real secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `RUVIEW_API_TOKEN`
- `RUVIEW_UDP_ALLOW`

Runtime `.env` files remain ignored, must have mode `0600`, and are copied to
the VPS through an operator-controlled secure channel. Tokens and Wi-Fi
credentials never appear in Compose files, source, test fixtures, Docker image
layers, or logs. Telegram and RuView use different tokens.

## Health, supervision, and recovery

- Both services use `restart: unless-stopped` and independent health checks.
- The sensing health check proves its process is alive; the alarm's active
  polling determines whether real ESP32 data is available.
- Alarm health proves its main event loop and all supervised worker loops are alive.
- A RuView outage does not disarm the alarm or rewrite stored state.
- A Telegram outage does not stop sensing supervision.
- Sensor-offline and sensor-recovered messages are transition-based to prevent
  alert storms.
- Deployment uses a manual, pinned Compose update. Rollback restores the prior
  image pin and alarm image, then verifies persisted state before service
  start.

## Verification

### Level 1: unit tests

Tests cover:

- configuration validation without exposing secret values;
- authorization by Telegram chat ID;
- arm, disarm, and status behavior;
- atomic state save/load and rejection of corrupt or unsupported state;
- intrusion and 60-second all-clear transitions;
- armed-state restoration and detection immediately after restart;
- 30-second offline detection and single recovery notification;
- bearer authorization on RuView requests; and
- retry delay bounds.

### Level 2: service integration tests

Local fake RuView and Telegram endpoints exercise long polling, callback
acknowledgement, authenticated sensing reads, queued update offsets, Telegram
delivery failures, sensor loss, recovery, and graceful shutdown. Tests use no
real Telegram token, CSI data, or external network.

### Level 3: container verification

- Validate the rendered Compose configuration with all example substitutions.
- Build the alarm image from a clean context.
- Start the pinned RuView service in explicit simulation mode for this test
  only and independently verify its bearer boundary, honest non-ESP32 source,
  and restricted ports.
- Route only the alarm-under-test to a clearly named synthetic ESP32-shaped
  HTTP service. Verify alarm-originated bearer-authenticated polling through
  credential-free request evidence, drive a sensing transition, and restore
  armed state after container recreation.
- Confirm the host publishes RuView HTTP only on `127.0.0.1` and does not
  publish port 3001.
- Scan the resulting diff and image configuration for secrets.

Levels 1 through 3 must pass before software implementation is considered
complete.

### Level 4: hardware and VPS acceptance

With physical board access and VPS credentials:

1. Build the pinned display-less ESP32-S3 firmware and capture its hashes.
2. Flash the firmware only after confirming the detected UART port and board.
3. Provision the new 2.4 GHz Wi-Fi and temporary VPS UDP target.
4. Capture the serial boot/runtime log showing DHCP and successful UDP sends.
5. Observe the true home egress IP on the VPS, then install the `/32` RuView
   and firewall allowlists.
6. Verify `/health` reports `esp32`, the sensing tick advances, and
   `/api/v1/sensing/latest` contains live data.
7. Arm through Telegram, perform a walk-through, receive intrusion and
   all-clear messages, and verify unauthorized chat actions are ignored.
8. Reboot the containers and VPS, confirm the prior armed state returns, and
   repeat a presence event.

This level is the only basis for claiming that the deployed hardware alarm is
operational.

Record its redacted evidence in
`deploy/home-alarm/verification/level4-acceptance.md`; use
`docs/status/home-alarm-v2.md` for sequencing and completion state.

## Explicitly excluded

- Home Assistant, Matter, HOMECORE, camera snapshots, multi-room meshes, model
  training, pose accuracy work, automatic upstream updates, and automatic
  production deployment.
- Changes to upstream Rust sensing logic or firmware algorithms unless a
  pinned baseline defect blocks the defined acceptance test.
- Public HTTP/WebSocket access to the sensing UI.
