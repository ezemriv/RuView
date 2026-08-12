# Home Alarm Software Verification

**Date (UTC):** 2026-08-12T12:59:17Z
**Evidence commit (before this record):** `562b07ac8f9b72bda48733b7655c65b2098b1e3d`
**Pinned sensing image:** `docker.io/ruvnet/wifi-densepose@sha256:fac235102bebc8a9bfc5445645bc6908d02cf0244154e59b7bab297a574b5fae`

This is a reproducible software evidence record. It is not hardware or VPS
acceptance evidence. No hardware, VPS, network configuration, or secrets were
used for these gates.

## Tooling

- Project interpreter: Python 3.12.11
- uv: 0.10.9 (`f675560f3`, 2026-03-06)
- Docker: 29.1.3 (`f52814d`)
- Docker Compose: v2.40.3-desktop.1

All `uv` commands used `UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache`.

## Level 1: locked dependencies, tests, and lint

```console
cd deploy/home-alarm
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv sync --frozen --all-extras --dev
```

Result: PASS — `Audited 39 packages in 3ms`. The tracked lock was unchanged.

```console
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv run pytest -v -m 'not container'
```

Result: PASS — 109 passed, 1 deselected in 1.21s (exit 0).

```console
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv run ruff check src tests scripts
```

Result: PASS — `All checks passed!` (exit 0).

## Level 3: immutable container smoke gate

```console
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv run pytest tests/test_container_smoke.py -v -m container
```

Result: PASS — 1 passed, 4 deselected in 120.31s (exit 0). The immutable
container recreation test ran and passed.

```console
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
docker image ls --format '{{.Repository}}:{{.Tag}}' | rg '^ruview-alarm-smoke-' || true
docker volume ls --format '{{.Name}}' | rg '^ruview-alarm-smoke-' || true
```

Post-smoke read-only Docker check: only the pre-existing `ruview-alarm`
container remained; no `ruview-alarm-smoke-*` containers or volumes remained.
There were unrelated, pre-existing smoke-tagged images with identifiers that
did not match this run; this record does not attribute them to the run or
claim their removal. The smoke test itself verified cleanup of its exact,
unique image.

## Compose and repository checks

```console
cd deploy/home-alarm
docker compose --env-file tests/fixtures/compose.env config --quiet
git status --short
git diff --check
git ls-files deploy/home-alarm | sort
git diff -- uv.lock
```

Results: Compose configuration PASS (exit 0); status had no tracked changes
before this evidence file; whitespace check PASS (exit 0); tracked home-alarm
paths were listed for review. The ignored SDD workspace and local Python caches
are not tracked source. `git diff -- uv.lock` exited 0 with no output;
`uv.lock` was not staged or modified.

## Acceptance still required (Level 4)

No Level 4 claim is made. An operator must still obtain the confirmed physical
ESP32-S3 serial port; build, hash, and full-flash the pinned ESP-IDF firmware;
capture redacted serial DHCP/UDP evidence; obtain VPS SSH/firewall access and
a mode-`0600` environment file through a secure channel; deploy the pinned
Compose stack; restrict the discovered home egress address to a `/32` in both
allowlists; and verify live sensing, Telegram authorization, alarm lifecycle,
restart restoration, and rollback readiness. Store only hashes, outcomes, and
redacted logs.

## Gate status

Levels 1–3 are complete: locked dependencies, the full non-container suite,
Ruff, Compose configuration, and the immutable container smoke gate passed.
Level 4 remains operator-assisted and unperformed.
