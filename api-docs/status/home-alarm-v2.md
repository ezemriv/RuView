# RuView Home Alarm v2 — Current State and Next Steps

**Last reconciled:** 2026-08-12
**Current branch:** `main`; Home Alarm/upstream merge commit `89fb575c`
**Historical source branches:** `codex/upstream-home-alarm-v2-implementation`
and `codex/upstream-home-alarm-v2` (merged and deleted locally); the historical
remote `home-security-telegram` branch remains as a rollback reference
**Implementation and software-verification tip:** `cc66b478`
**Upstream baseline:** RuView `v2235` at `de27336fa1db971d4689fd2db19610e8a7966dee`

This is the canonical living status and restart handoff for Home Alarm v2.
Historical design, implementation, and evidence documents remain authoritative
for their own scope, but mutable status and next-step ownership live here.

## Current verdict

- Software implementation is complete.
- Levels 1–3 are complete and independently reviewed.
- Home Alarm v2 and its upstream baseline are merged into local `main` at
  `89fb575c`; the VPS has not been deployed.
- Level 4 is in progress: the physical ESP32-S3 has been clean-erased,
  full-flashed, and boot-verified. VPS deployment, NVS network provisioning,
  and live end-to-end acceptance remain, so the real home alarm is not yet
  operational.
- No real token, chat ID, Wi-Fi credential, VPS secret, or private CSI was
  read or committed.

## How the project reached this state

### Work that existed before the resumed session

- The earlier `home-security-telegram` approach and historical fork `main`
  remain available as rollback/history; v2 deliberately replaced the shared
  custom-container design with an immutable upstream RuView container plus a
  separate Python alarm sidecar.
- The approved v2 design and executable plan were committed on an integration
  branch based directly on upstream RuView `v2235`.
- Tasks 1–8 had already delivered validated contracts, strict durable state,
  deterministic alarm transitions, authenticated RuView and Telegram clients,
  four supervised loops, hardened Compose packaging, service integration
  fakes, and an initial container-smoke gate.
- A crash handoff recorded Task 9 as partially drafted and Task 10 as pending.
  That external attachment is now obsolete and is superseded by this file.

### Work completed after the crash

- Finished the TTY-only ESP32-S3 NVS provisioning wrapper, secret-safe
  runbook, scoped agent instructions, and `.env` ignore rules.
- Ran and recorded the complete locked software gate.
- Performed task-level and whole-branch reviews, then fixed every Important
  finding:
  - exact, duplicate-free persisted-state validation;
  - bounded best-effort Telegram callback acknowledgement;
  - secret-safe `docker compose config --quiet` validation;
  - rejection of redirected provisioning input;
  - honest separation of immutable RuView `MEASURED` checks from `SYNTHETIC`
    alarm lifecycle checks;
  - configured alarm timing thresholds; and
  - the full `1, 2, 4, 8, 16, 30` sensing retry schedule.
- Added tracked project memory so future agents can find the architecture,
  evidence boundary, runbook, and this handoff without relying on a session.

## Delivered system

- `deploy/home-alarm/src/ruview_alarm/`: Python 3.12 alarm service, strict
  state, authenticated adapters, deterministic engine, supervision, and
  healthcheck.
- `deploy/home-alarm/compose.yaml`: immutable RuView sensing plus a non-root,
  read-only alarm service with loopback-only HTTP and allowlisted UDP.
- `deploy/home-alarm/scripts/provision_esp32.py`: interactive TTY-only,
  password-prompted, ESP32-S3 NVS-only provisioning.
- `deploy/home-alarm/tests/`: unit, service-integration, Compose, provisioning,
  and container-smoke verification.
- `deploy/home-alarm/README.md`: operator build, provision, deploy, acceptance,
  and rollback runbook.

## Latest verified software evidence

The dated evidence record is
[`deploy/home-alarm/verification/software-verification.md`](../../deploy/home-alarm/verification/software-verification.md).
The feature-tip and merged-checkout reruns established:

- frozen dependency sync: passed with the tracked lock unchanged;
- non-container suite: 121 passed, 1 container test deselected;
- Ruff: passed;
- production Compose validation: passed without rendering secrets; and
- container smoke: 1 passed, 4 support tests deselected.

The container gate keeps evidence honest:

- `MEASURED`: immutable RuView digest, bearer boundary, non-ESP32 simulation
  source, port restrictions, runtime configuration, and cleanup.
- `SYNTHETIC`: alarm-originated authenticated polling of a clearly named fake
  ESP32-shaped service, intrusion/all-clear lifecycle, and armed-state restore.

Neither path is real ESP32/VPS evidence.

## Sequential next-step protocol

Agents must execute this checklist strictly from the first unchecked step.

1. Work on only one unchecked step at a time.
2. Read the linked instructions and verify prerequisites before mutation.
3. Do not start a later step while the current step is incomplete or blocked.
4. A checkbox may change to `[x]` only after its listed evidence exists.
5. In the same commit that completes a step, add a non-sensitive outcome
   summary and link to its detailed evidence here, update **Current verdict**,
   and identify the new first unchecked step.
6. If blocked, add a concise `Blocked:` note under that step and stop. Never
   mark a blocked, skipped, or simulated gate complete.
7. Hardware, VPS, firewall, deployment, secret handling, push, PR, and merge
   actions require the explicit authority named by repository instructions.

## Next steps

### 1. Integrate the feature branch

- [x] Merge `codex/upstream-home-alarm-v2-implementation` into
  `codex/upstream-home-alarm-v2` locally, preserving the implementation branch
  until the merged result is verified.

**Outcome (2026-08-12):** merged locally as `8f3563f6`; frozen sync,
121 non-container tests, Ruff, Compose validation, and the isolated container
smoke all passed on the merged checkout. The unrelated root `uv.lock` and the
pre-existing `ruview-alarm` container were preserved. The clean feature
worktree and now-merged local source branch were then removed; their commits
remain in the merge history. See
[`Local integration confirmation`](../../deploy/home-alarm/verification/software-verification.md#local-integration-confirmation).

**Prerequisite:** explicit user choice to merge locally.
**Complete when:** the target branch contains the feature commits, the merged
worktree has no tracked changes (the known unrelated root `uv.lock` remains
preserved), frozen sync/non-container/Ruff/Compose/container gates pass without
a skip, and the merge commit plus command outcomes are recorded here.

### 2. Prepare ESP32 Level 4 inputs

- [x] Confirm the exact physical ESP32-S3 board and UART port and obtain
  explicit authorization for the read-only probe and later full flash after
  final target confirmation.

**Outcome (2026-08-12):** packaging and authorized read-only probes confirmed
a Freenove ESP32-S3-WROOM Board Lite (`FNK0099`, revision `A`), ESP32-S3 QFN56
revision 0.2, 8 MB PSRAM, 8 MB quad flash, and UART
`/dev/cu.wchusbserial58FA0422681`. The source photo and all unique identifiers
were deliberately not retained. Full-flash authorization was granted subject
to final target confirmation. See the Step 2 entries in the
[`Level 4 acceptance record`](../../deploy/home-alarm/verification/level4-acceptance.md#step-2-evidence--operator-inputs-and-authority).

**Depends on:** Step 1.
**Complete when:** the confirmed non-secret device/target identifiers and
authority decisions are recorded in
[`deploy/home-alarm/verification/level4-acceptance.md`](../../deploy/home-alarm/verification/level4-acceptance.md);
no credential value is committed.

### 3. Build, hash, and flash the ESP32-S3

- [x] Follow the pinned ESP-IDF 5.4 display-less build in the runbook, record
  the four firmware hashes, derive and record the exact build-produced flash
  offsets/command using the authoritative
  [`firmware/esp32-csi-node/README.md`](../../firmware/esp32-csi-node/README.md#2-flash),
  re-confirm the board and UART target, perform the explicitly authorized
  initial full flash, and capture a redacted serial boot log. NVS network
  provisioning is deferred until the VPS exists in Step 5.

**Outcome (2026-08-12):** after final target confirmation, the entire 8 MB
flash was erased and the four hashed images were written at `0x0`, `0x8000`,
`0xf000`, and `0x20000`; esptool verified every region. A bounded redacted
serial observation confirmed the display-less MGMT+DATA CSI path, edge tier 2,
and live CSI callbacks. Wi-Fi/UDP delivery remains intentionally unavailable
until Step 5 provisioning. See
[`Clean flash and boot`](../../deploy/home-alarm/verification/level4-acceptance.md#clean-flash-and-boot--2026-08-12t173147z).

**Depends on:** Step 2.
**Complete when:** hashes, command outcomes, confirmed target, and redacted
serial evidence are stored in the acceptance record. The command and offsets
must match the pinned build output; a build alone is not completion.

### 4. Deploy and close the VPS network boundary

- [ ] Confirm VPS SSH/firewall authority, create the production mode-`0600`
  `.env` through an operator-controlled channel, deploy the pinned Compose
  stack, temporarily discover the home egress address, then install the same
  `/32` in `RUVIEW_UDP_ALLOW` and the VPS UDP/5005 firewall rule and remove the
  discovery opening.

When a separate Codex session runs on the VPS, route it through the scoped
[`VPS-HANDOFF.md`](../../deploy/home-alarm/VPS-HANDOFF.md). The VPS agent must
complete only this step and return its redacted evidence commit before the Mac
session begins Step 5.

**Depends on:** Step 3.
**Complete when:** deployment/config checks pass and redacted evidence proves
both allowlists use the same `/32` with no broad discovery rule left active.

### 5. Execute live alarm acceptance and rollback

- [ ] Provision the ESP32 NVS with the home Wi-Fi and deployed VPS target,
  capture redacted serial DHCP/UDP evidence, then verify live `source: esp32`,
  advancing ticks/latest data, Telegram authorization,
  arm/intrusion/all-clear, alarm/container/VPS restart restore, and rollback
  to the recorded prior images/configuration.

**Depends on:** Step 4.
**Complete when:** a dated redacted acceptance record contains outcomes for
every Level 4 check, serial/end-to-end evidence, and the rollback exercise.

### 6. Close the workstream

- [ ] Mark Level 4 operational, update design/runbook/memory/status, and move
  this workstream out of active project memory.

**Depends on:** Step 5.
**Complete when:** all prior checkboxes are `[x]`, no blocker remains, tracked
documentation links the Level 4 evidence, and no unsupported capability claim
or sensitive value appears in the diff.

## Authoritative references

- [Implemented design](../superpowers/specs/2026-08-12-home-alarm-v2-design.md)
- [Completed implementation plan](../superpowers/plans/2026-08-12-home-alarm-v2.md)
- [Operator runbook](../../deploy/home-alarm/README.md)
- [Software evidence](../../deploy/home-alarm/verification/software-verification.md)
- [Level 4 acceptance record](../../deploy/home-alarm/verification/level4-acceptance.md)
- [Scoped agent instructions](../../deploy/home-alarm/AGENTS.md)
- [Durable architecture memory](../../memory/architecture/home-alarm-v2.md)

## Preserved safety notes

- The repository-root untracked `uv.lock` in the normal checkout is unrelated;
  preserve it. The intended tracked lock is `deploy/home-alarm/uv.lock`.
- Do not stop, delete, reconfigure, or reuse an unrelated container named
  `ruview-alarm`; smoke tests use uniquely named ephemeral resources.
- Nothing in Levels 1–3 authorizes a flash, VPS change, deployment, publication,
  merge, push, or PR.
