# Project Memory Index

This directory contains tracked, non-sensitive memory for future agents.

## Usage

- Read this file before substantial repository work.
- Open only the memory files relevant to the current task.
- Treat memory as navigation, not authority; verify against current source, tests, accepted ADRs, and repository instructions.
- After substantial work or durable decisions, use `$codex-project-update`.

## Map

| Path | Purpose | Status |
|---|---|---|
| `docs/status/home-alarm-v2.md` | Canonical living status, restart handoff, and strictly sequential next-step checklist. | Active source of truth |
| `memory/architecture/home-alarm-v2.md` | Durable Home Alarm v2 architecture, evidence boundaries, validation routes, and remaining operator acceptance. | Active |
| `deploy/home-alarm/verification/level4-acceptance.md` | Canonical redacted evidence record for operator-assisted hardware/VPS acceptance; sequencing and completion state stay in the status document. | Evidence template |
