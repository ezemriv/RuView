# RuView home alarm operator runbook

This Compose deployment combines the pinned RuView ESP32 sensing service with a restricted,
stateful Telegram alarm. Treat this as an operator runbook, not proof of real-hardware success:
record serial output and authenticated end-to-end evidence for every physical installation.

Current project status, completed software work, and the sequential integration/Level 4
checklist are maintained in [`docs/status/home-alarm-v2.md`](../../docs/status/home-alarm-v2.md).
Agents must complete and mark only the first unchecked step there.

For execution by a separate Codex session already running on the VPS, use the
scoped [`VPS-HANDOFF.md`](VPS-HANDOFF.md). That agent owns only VPS Step 4;
the Mac session retains ownership of the physical ESP32 and later Step 5.

## Prepare secrets and deployment

On the VPS, create the production environment file from the reviewed template and protect it:

```bash
cd deploy/home-alarm
cp .env.example .env
chmod 600 .env
```

Fill in the three distinct production secrets and the planned source allow-list; never paste
them into shell history, issue text, logs, or source control. Inspect the resolved deployment,
then pull, rebuild from pinned inputs, and start it:

```bash
docker compose pull
docker compose build --pull
docker compose config --quiet
docker compose up -d
```

`config --quiet` validates the production file without rendering its runtime token values.

`sensing-server` uses `kill -0 1` as a container healthcheck. That proves process liveness,
not API readiness. Verify `/health` and an authenticated
`/api/v1/sensing/latest` response independently.

## Build and initially flash display-less ESP32-S3 firmware

From the repository root, use the pinned ESP-IDF image and the exact display-less defaults:

> This command removes `firmware/esp32-csi-node/build` and its generated
> `sdkconfig`. Run it only in the approved integration checkout after preserving
> any intentional local firmware configuration.

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd)/firmware/esp32-csi-node:/project" -w /project \
  espressif/idf:v5.4 bash -c \
  "rm -rf build sdkconfig && idf.py -DSDKCONFIG_DEFAULTS='sdkconfig.defaults;sdkconfig.defaults.devkitc' set-target esp32s3 && idf.py -DSDKCONFIG_DEFAULTS='sdkconfig.defaults;sdkconfig.defaults.devkitc' build"
sha256sum firmware/esp32-csi-node/build/bootloader/bootloader.bin \
  firmware/esp32-csi-node/build/partition_table/partition-table.bin \
  firmware/esp32-csi-node/build/ota_data_initial.bin \
  firmware/esp32-csi-node/build/esp32-csi-node.bin
```

Confirm the exact UART device, board, and intended full-flash target with the operator before
any initial full flash. Follow the authoritative
[`firmware/esp32-csi-node/README.md` flash procedure](../../firmware/esp32-csi-node/README.md#2-flash),
derive the exact command and offsets from the pinned build output, record them in
[`verification/level4-acceptance.md`](verification/level4-acceptance.md), and re-confirm them
with the operator before execution.
Record the four SHA-256 values (bootloader, partition table, OTA data, and application binary)
with the serial boot log. Do not claim success from a build alone.

## Provision later NVS changes

For Wi-Fi or VPS changes after that initial full flash, use the interactive wrapper from this
directory. It has no password CLI argument; it prompts with hidden input, requires an exact
serial-port retype, forces ESP32-S3 plus UDP port `5005`, supplies a private temporary state
directory, and invokes the upstream NVS writer in process.
The helper rejects redirected or piped stdin; run it only from an interactive terminal.

```bash
cd deploy/home-alarm
uv run --extra provision python scripts/provision_esp32.py \
  --port /dev/cu.usbserial-XXXX --ssid "Home-2G" \
  --vps-ip 203.0.113.10 --node-id 1
```

The upstream operation is NVS-only: it calls `esptool write_flash` at offset `0x9000`; it does
not perform a full firmware flash. Confirm the serial port and board before accepting the prompt.

## Allow only the home source

Before permanently opening UDP, use a temporary, time-bounded discovery rule and capture the
observed source address from the VPS firewall/logs. Remove the temporary discovery rule, then
install the same home address as a `/32` in both places:

```dotenv
RUVIEW_UDP_ALLOW=203.0.113.42/32
```

Apply that exact `/32` to the VPS UDP/5005 firewall rule as well. Do not leave a broad UDP rule
or discovery rule in place.

## Acceptance and rollback

With real hardware attached, retain the serial boot/runtime log and check all of the following:

1. `/health` reports `status: ok` and `source: esp32`.
2. Authenticated `/api/v1/sensing/latest` returns current ESP32 data.
3. Only the configured Telegram chat can arm/disarm; an unauthorized chat is ignored.
4. An armed present transition produces an intrusion notification, and sustained healthy absence
   produces all-clear.
5. Restart the alarm and confirm its armed state and Telegram offset restoration notification.
6. Test rollback with the previously recorded image/configuration and confirm the same API and
   Telegram checks after rollback.

These software checks and Compose status do not replace serial and end-to-end hardware evidence.
Append each authorized phase to [`verification/level4-acceptance.md`](verification/level4-acceptance.md)
and update the matching checkbox in the canonical status document in the same commit.
