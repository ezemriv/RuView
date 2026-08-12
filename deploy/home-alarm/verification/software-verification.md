# Home Alarm Software Verification

> This is dated Levels 1–3 evidence, not the living task tracker. Current state
> and sequential next steps are maintained in
> [`docs/status/home-alarm-v2.md`](../../../docs/status/home-alarm-v2.md).

**Date (UTC):** 2026-08-12T13:46:26Z
**Fix-wave base commit:** `53c7c9eaeadfbe7120ed15cd62b4c87600c4f826`
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

Result: PASS — 121 passed, 1 deselected in 1.29s (exit 0). This includes
the hermetic service-integration scenarios for authenticated adapter traffic,
Telegram control, sensing transitions, failure isolation, and client cleanup.

```console
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv run ruff check src tests scripts
```

Result: PASS — `All checks passed!` (exit 0).

## Level 2: service integration evidence

```console
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv run pytest tests/test_service_integration.py -q
```

Result: PASS — 5 passed in 0.43s (exit 0). These tests exercise the
authenticated RuView and Telegram HTTP adapters with the supervised service,
including alarm transitions, update durability, authorization, failure
isolation, restoration, and client shutdown.

## Level 3: immutable container smoke gate

```console
UV_CACHE_DIR=/private/tmp/ruview-home-alarm-uv-cache uv run pytest tests/test_container_smoke.py -v -m container
```

Result: PASS — 1 passed, 4 deselected in 40.27s (exit 0).

The gate keeps two evidence paths separate:

- **MEASURED:** the running sensing container used the exact immutable image
  digest above with `CSI_SOURCE=simulated`; its bearer boundary accepted the
  sentinel only, its responses reported an honest non-ESP32 source, HTTP was
  loopback-only, and neither production UDP nor port 3001 was published.
- **SYNTHETIC:** only the alarm-under-test was routed to the clearly named
  `fake-sensing` service. Credential-free request counts proved that the alarm
  container made bearer-authenticated `/health` and latest-sensing requests.
  The test then drove false -> true -> false synthetic presence through HTTP,
  observed intrusion and all-clear messages from the real alarm container,
  and recreated that container to verify its armed state was restored.

The synthetic service is not RuView simulation evidence and is not real ESP32
or CSI evidence.

```console
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
docker image ls --format '{{.Repository}}:{{.Tag}}' | rg '^ruview-alarm-smoke-' || true
docker volume ls --format '{{.Name}}' | rg '^ruview-alarm-smoke-' || true
```

Post-smoke read-only Docker check: only the pre-existing `ruview-alarm`
container remained, and no `ruview-alarm-smoke-*` volumes remained. The smoke
test itself verified cleanup of its exact unique project and alarm image.

## Compose and repository checks

```console
cd deploy/home-alarm
docker compose --env-file tests/fixtures/compose.env config --quiet
git status --short
git diff --check
git ls-files deploy/home-alarm | sort
git diff -- uv.lock
```

Results: Compose configuration PASS with no rendered output (exit 0);
whitespace check PASS (exit 0); status contained only the intended final-fix
files before commit; tracked home-alarm paths were listed for review. The
ignored SDD workspace and local Python caches are not tracked source.
`git diff -- uv.lock` exited 0 with no output; `uv.lock` was not modified.

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

Levels 1–3 are complete: locked dependencies, the full unit/service-integration
suite, Ruff, Compose validation, the immutable RuView boundary checks, and the
synthetic alarm-container sensing lifecycle passed. Level 4 remains
operator-assisted and unperformed; this record makes no hardware or VPS claim.

## Final branch-tip confirmation

After the final review fixes and project-memory update, the same software gate
was rerun at `cc66b478`:

- frozen sync passed with the tracked lock unchanged;
- 121 non-container tests passed and 1 container test was deselected;
- Ruff and `docker compose ... config --quiet` passed; and
- the container smoke passed with 1 selected test and 4 support tests deselected.

This confirms Levels 1–3 at the implementation tip. It does not change the
unperformed Level 4 verdict.

## Local integration confirmation

**Date (UTC):** 2026-08-12T17:09:08Z
**Target branch:** `codex/upstream-home-alarm-v2`
**Merge commit:** `8f3563f6103b4829113bdd2d69690c17c7a01956`

The authorized local merge used `--no-ff` and preserved the implementation
branch for rollback. On the merged checkout:

- frozen sync installed the 39 locked packages without changing the tracked
  lock file;
- the non-container gate passed with 121 tests and 1 deselected container test;
- Ruff and production Compose validation passed;
- the isolated container gate passed with 1 selected test and 4 support tests
  deselected; and
- the unrelated root `uv.lock` remained untracked and unchanged.

The socket-based tests and Docker smoke required local permissions unavailable
inside the command sandbox. Their permission-enabled reruns passed without a
code change. Four exact `ruview-alarm-smoke-*` image tags left by interrupted
verification were removed; the final read-only check found no smoke image or
volume, and the pre-existing `ruview-alarm` container remained running.

This is software integration evidence only. Level 4 physical ESP32/VPS
acceptance remains unperformed.
