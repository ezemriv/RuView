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
- explicit flash authorization outcome;
- VPS SSH/firewall authorization outcome; and
- mode-`0600` production environment-file check outcome without values.

## Step 3 evidence — firmware and ESP32-S3

Record, when authorized:

- pinned RuView commit and ESP-IDF image/version;
- SHA-256 for bootloader, partition table, OTA data, and application binary;
- exact flash offsets/command derived from the pinned build output;
- re-confirmed board/UART target and flash outcome;
- NVS provisioning outcome; and
- redacted serial evidence of boot, DHCP, and UDP sends.

## Step 4 evidence — VPS deployment and network closure

Record, when authorized:

- pinned image/configuration identifiers and Compose command outcomes;
- temporary discovery opening start/end and removal outcome;
- confirmation that `RUVIEW_UDP_ALLOW` and the firewall use the same home
  `/32`, without recording the real address; and
- proof that no broad discovery/firewall rule remains.

## Step 5 evidence — live lifecycle, restoration, and rollback

Record, when authorized:

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
