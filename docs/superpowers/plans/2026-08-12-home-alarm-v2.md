# RuView Home Alarm v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pinned, restart-safe Telegram alarm around upstream RuView, plus a secure local ESP32 provisioning helper and a reproducible VPS Compose deployment.

**Architecture:** Run the immutable upstream sensing image unchanged and add one small Python 3.12 sidecar that owns Telegram control, alarm transitions, persistence, and supervision. Keep sensing HTTP private, expose only loopback HTTP and public allowlisted UDP, and treat software/container verification separately from ESP32/VPS acceptance.

**Tech Stack:** Python 3.12, `uv`, Pydantic Settings 2, HTTPX 0.28, pytest/pytest-asyncio, Docker Compose v2, upstream RuView v2235, ESP-IDF 5.4.

## Global Constraints

- The RuView source baseline is release `v2235`, commit `de27336fa1db971d4689fd2db19610e8a7966dee`; do not modify upstream Rust sensing or firmware algorithms.
- The production sensing image is `docker.io/ruvnet/wifi-densepose@sha256:fac235102bebc8a9bfc5445645bc6908d02cf0244154e59b7bab297a574b5fae`; never use `latest`.
- The production firmware is built from the same commit with ESP-IDF 5.4 and `firmware/esp32-csi-node/sdkconfig.defaults.devkitc`.
- The alarm runtime is Python `>=3.12,<3.13`, managed and locked with `uv`.
- Poll sensing every 5 seconds; declare it offline after 30 continuous seconds; emit all-clear only after 60 continuous seconds without presence.
- Transient network retries use delays `1, 2, 4, 8, 16, 30` seconds, capped at 30 seconds.
- Persistent JSON has exactly `version`, `armed`, and `telegram_offset`; missing state starts disarmed, while corrupt or unsupported state terminates startup.
- Persist state with a mode-`0600` temporary file, file `fsync`, atomic `os.replace`, and parent-directory `fsync`.
- Accept Telegram control only from `TELEGRAM_CHAT_ID`; Telegram and RuView use different tokens.
- Never put real tokens, chat IDs, Wi-Fi credentials, or raw/private CSI in source, fixtures, Compose files, image layers, command lines, or logs.
- Publish RuView HTTP only as `127.0.0.1:3000:3000`; publish UDP `5005:5005/udp`; never publish port 3001.
- Production uses `CSI_SOURCE=esp32`, `RUVIEW_UDP_BIND=0.0.0.0`, a required `RUVIEW_UDP_ALLOW`, and `RUVIEW_API_TOKEN` bearer authentication.
- Both containers use `restart: unless-stopped`, drop all capabilities, enable `no-new-privileges`, and have independent health checks.
- Unit, service-integration, and container verification prove software behavior only. Claim real operation only after captured hardware logs and the VPS/Telegram walk-through in the design spec.
- Preserve the repository-root untracked `uv.lock`; all Python lockfile work belongs under `deploy/home-alarm/uv.lock`.

## File Map

- `deploy/home-alarm/src/ruview_alarm/config.py`: environment parsing and validated runtime settings.
- `deploy/home-alarm/src/ruview_alarm/models.py`: persistent, Telegram, sensing, event, and heartbeat contracts.
- `deploy/home-alarm/src/ruview_alarm/state.py`: durable atomic state storage.
- `deploy/home-alarm/src/ruview_alarm/alarm.py`: pure alarm state machine.
- `deploy/home-alarm/src/ruview_alarm/ruview.py`: authenticated RuView HTTP adapter.
- `deploy/home-alarm/src/ruview_alarm/telegram.py`: secret-safe Telegram Bot API adapter and update parser.
- `deploy/home-alarm/src/ruview_alarm/service.py`: async orchestration, persistence, retries, notifications, and shutdown.
- `deploy/home-alarm/src/ruview_alarm/healthcheck.py`: validates the service heartbeat for Docker.
- `deploy/home-alarm/src/ruview_alarm/__main__.py`: logging setup and process entry point.
- `deploy/home-alarm/scripts/provision_esp32.py`: confirmed in-process wrapper around upstream NVS provisioning.
- `deploy/home-alarm/tests/`: unit, service-integration, Compose-contract, provisioning, and container-smoke tests.
- `deploy/home-alarm/Dockerfile`, `compose.yaml`, `compose.smoke.yaml`, `.env.example`: immutable runtime and verification packaging.
- `deploy/home-alarm/README.md`, `AGENTS.md`: operator runbook and subsystem guidance.

---

### Task 1: Package, validated settings, and shared contracts

**Files:**
- Create: `deploy/home-alarm/pyproject.toml`
- Create: `deploy/home-alarm/src/ruview_alarm/__init__.py`
- Create: `deploy/home-alarm/src/ruview_alarm/config.py`
- Create: `deploy/home-alarm/src/ruview_alarm/models.py`
- Create: `deploy/home-alarm/tests/test_config.py`
- Create: `deploy/home-alarm/tests/test_models.py`

**Interfaces:**
- Produces: `Settings`, `PersistedState`, `SensorSample`, `TelegramUpdate`, `AlarmAction`, `AlarmEventKind`, and `AlarmEvent`.
- `Settings` fields: `telegram_bot_token: SecretStr`, `telegram_chat_id: int`, `ruview_api_token: SecretStr`, `ruview_base_url: AnyHttpUrl`, `telegram_base_url: AnyHttpUrl`, `state_path: Path`, `health_path: Path`, `poll_seconds: float`, `all_clear_seconds: float`, `offline_seconds: float`, `telegram_poll_seconds: int`.
- `SensorSample` fields: `healthy_esp32: bool`, `presence: bool | None`, `tick: int | None`.

- [ ] **Step 1: Write the package metadata and failing settings/model tests**

Create a `hatchling` package rooted at `src`, require Python `>=3.12,<3.13`, and declare runtime dependencies `httpx>=0.28.1,<0.29` and `pydantic-settings>=2.10,<3`. Add an optional `provision` extra with `esptool>=5,<6` and `esp-idf-nvs-partition-gen>=0.2,<0.4`. Add development dependencies `pytest>=8.4,<9`, `pytest-asyncio>=1.1,<2`, and `ruff>=0.12,<0.13`. Configure pytest with `asyncio_mode = "auto"` and Ruff for Python 3.12 with a 100-character line length.

Use named tests `test_settings_require_all_three_credentials`, `test_settings_apply_documented_defaults`, `test_settings_accept_constructor_overrides_without_env_file`, `test_validation_error_does_not_include_secret_values`, `test_persisted_state_has_exact_versioned_shape`, `test_sensor_sample_rejects_presence_without_healthy_esp32`, and `test_alarm_action_accepts_only_arm_disarm_status`. For example, the shape assertion is:

```python
def test_persisted_state_has_exact_versioned_shape() -> None:
    state = PersistedState(armed=True, telegram_offset=123456789)
    assert state.model_dump() == {
        "version": 1,
        "armed": True,
        "telegram_offset": 123456789,
    }
```

The documented defaults are `http://sensing-server:3000`, `https://api.telegram.org`, `/data/state.json`, `/tmp/ruview-alarm-health.json`, `5.0`, `60.0`, `30.0`, and `20` respectively. Secret-leak assertions must test a sentinel such as `DO_NOT_RENDER_ME` without printing it.

- [ ] **Step 2: Run the focused tests and verify the import failure**

Run: `cd deploy/home-alarm && uv run pytest tests/test_config.py tests/test_models.py -v`

Expected: FAIL because `ruview_alarm.config` and `ruview_alarm.models` do not exist.

- [ ] **Step 3: Implement the exact contracts and settings validation**

Define the contracts with these signatures and invariants:

```python
class PersistedState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    armed: bool = False
    telegram_offset: int | None = Field(default=None, ge=0)

class SensorSample(BaseModel):
    healthy_esp32: bool
    presence: bool | None = None
    tick: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_presence_only_for_healthy_source(self) -> Self:
        if not self.healthy_esp32 and (self.presence is not None or self.tick is not None):
            raise ValueError("unhealthy samples cannot carry sensing data")
        return self

class TelegramUpdate(BaseModel):
    update_id: int = Field(ge=0)
    chat_id: int | None = None
    action: AlarmAction | None = None
    callback_id: str | None = None

class AlarmEvent(BaseModel):
    kind: AlarmEventKind
    text: str
```

Use `StrEnum` values `arm`, `disarm`, `status` and event kinds `status`, `intrusion`, `all_clear`, `sensor_offline`, `sensor_recovered`. Reject a `SensorSample` where `healthy_esp32` is false but `presence` is not `None` or `tick` is set.

Implement `Settings(BaseSettings)` with `SettingsConfigDict(case_sensitive=False, env_file=None, extra="ignore")`, the exact field names above, positive timing validation, and a model-level check that the unwrapped Telegram and RuView tokens differ. Override `__repr__`/`__str__` only if a test proves Pydantic's default secret redaction is insufficient.

- [ ] **Step 4: Run unit checks**

Run: `cd deploy/home-alarm && uv run pytest tests/test_config.py tests/test_models.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run ruff check src tests/test_config.py tests/test_models.py`

Expected: PASS with no diagnostics.

- [ ] **Step 5: Commit the package foundation**

```bash
git add deploy/home-alarm/pyproject.toml deploy/home-alarm/src deploy/home-alarm/tests/test_config.py deploy/home-alarm/tests/test_models.py
git commit -m "feat(alarm): add validated configuration contracts"
```

### Task 2: Durable alarm state

**Files:**
- Create: `deploy/home-alarm/src/ruview_alarm/state.py`
- Create: `deploy/home-alarm/tests/test_state.py`

**Interfaces:**
- Consumes: `PersistedState` from Task 1.
- Produces: `load_state(path: Path) -> PersistedState` and `save_state(path: Path, state: PersistedState) -> None`.

- [ ] **Step 1: Write failing persistence tests**

Write named tests for missing-file defaults, round-trip restoration, atomic replacement/mode, file and directory `fsync`, corrupt JSON, unsupported versions, and extra fields. The round-trip contract is:

```python
def test_round_trip_restores_armed_and_offset(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    expected = PersistedState(armed=True, telegram_offset=42)
    save_state(path, expected)
    assert load_state(path) == expected
```

Patch `os.replace` in the atomicity test and assert the source is in the destination directory and ends with `.tmp`; assert the destination was absent before replacement. Patch `os.fsync` in the durability test and assert it receives both a regular-file descriptor and the opened directory descriptor.

- [ ] **Step 2: Verify red tests**

Run: `cd deploy/home-alarm && uv run pytest tests/test_state.py -v`

Expected: FAIL on missing `ruview_alarm.state`.

- [ ] **Step 3: Implement missing-file defaults and strict load**

```python
def load_state(path: Path) -> PersistedState:
    if not path.exists():
        return PersistedState()
    return PersistedState.model_validate_json(path.read_bytes())
```

Do not catch Pydantic or JSON validation exceptions: startup must stop on ambiguity.

- [ ] **Step 4: Implement atomic, durable, private save**

Create the parent with mode `0700`, create the temporary file with `tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")`, immediately call `os.fchmod(fd, 0o600)`, write canonical UTF-8 JSON plus a newline, flush and `fsync`, replace it, then open the parent directory with `os.O_DIRECTORY` and `fsync` it. Unlink only the known temporary path in the exception path.

- [ ] **Step 5: Run persistence and style checks**

Run: `cd deploy/home-alarm && uv run pytest tests/test_state.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run ruff check src/ruview_alarm/state.py tests/test_state.py`

Expected: PASS.

- [ ] **Step 6: Commit durable state**

```bash
git add deploy/home-alarm/src/ruview_alarm/state.py deploy/home-alarm/tests/test_state.py
git commit -m "feat(alarm): persist restart-safe alarm state"
```

### Task 3: Pure alarm transition engine

**Files:**
- Create: `deploy/home-alarm/src/ruview_alarm/alarm.py`
- Create: `deploy/home-alarm/tests/test_alarm.py`

**Interfaces:**
- Consumes: `AlarmAction`, `AlarmEvent`, `AlarmEventKind`, `PersistedState`, and `SensorSample` from Task 1.
- Produces: `AlarmEngine.restore(state)`, `AlarmEngine.command(action)`, `AlarmEngine.observe(sample, now)`, `AlarmEngine.snapshot(offset)`.
- Use monotonic seconds (`float`) for transition durations; only human-facing message text mentions state, not internal timestamps.

- [ ] **Step 1: Write failing state-machine tests with a fake clock**

Use direct numeric times so boundary behavior is unambiguous. Cover new/disarmed state, armed restoration, idempotent commands, absent-to-present intrusion, disarmed suppression, presence on first sample after an armed restart, all-clear timing/reset, offline/recovery deduplication, unhealthy presence isolation, and disarm during an incident. A boundary assertion is:

```python
def test_all_clear_requires_60_continuous_seconds_absent() -> None:
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True))
    engine.observe(SensorSample(healthy_esp32=True, presence=True, tick=1), 0.0)
    engine.observe(SensorSample(healthy_esp32=True, presence=False, tick=2), 1.0)
    assert engine.observe(SensorSample(healthy_esp32=True, presence=False, tick=3), 60.999) == []
    events = engine.observe(SensorSample(healthy_esp32=True, presence=False, tick=4), 61.0)
    assert [event.kind for event in events] == [AlarmEventKind.ALL_CLEAR]
```

At boundaries, assert no offline event at `29.999`, one at `30.0`, no all-clear at `59.999`, and one at `60.0`.

- [ ] **Step 2: Verify the engine tests fail**

Run: `cd deploy/home-alarm && uv run pytest tests/test_alarm.py -v`

Expected: FAIL on missing `ruview_alarm.alarm`.

- [ ] **Step 3: Implement runtime state and commands**

Use one class with these methods:

```python
class AlarmEngine:
    def restore(self, state: PersistedState) -> None:
        raise NotImplementedError

    def command(self, action: AlarmAction) -> list[AlarmEvent]:
        raise NotImplementedError

    def observe(self, sample: SensorSample, now: float) -> list[AlarmEvent]:
        raise NotImplementedError

    def snapshot(self, offset: int | None) -> PersistedState:
        raise NotImplementedError
```

Keep only runtime fields required by the spec: armed, previous healthy presence, active incident, absence start, unhealthy start, and offline-notified flag. `arm` must initialize transition tracking so the next healthy present sample can raise an intrusion; `disarm` must clear any incident/countdown. Status text must explicitly say `armed` or `disarmed`.

- [ ] **Step 4: Implement exact transition timing**

Healthy samples clear the unhealthy timer and emit one recovery only if offline was previously notified. Unhealthy samples start the timer and never change presence. While armed, a false-to-true transition emits one intrusion and opens an incident; an open incident closes only after 60 uninterrupted seconds of healthy absence. Repeated samples in the same state emit nothing.

- [ ] **Step 5: Run engine regression checks**

Run: `cd deploy/home-alarm && uv run pytest tests/test_alarm.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run ruff check src/ruview_alarm/alarm.py tests/test_alarm.py`

Expected: PASS.

- [ ] **Step 6: Commit the engine**

```bash
git add deploy/home-alarm/src/ruview_alarm/alarm.py deploy/home-alarm/tests/test_alarm.py
git commit -m "feat(alarm): add deterministic alarm transitions"
```

### Task 4: Authenticated RuView adapter

**Files:**
- Create: `deploy/home-alarm/src/ruview_alarm/ruview.py`
- Create: `deploy/home-alarm/tests/test_ruview.py`

**Interfaces:**
- Consumes: `SensorSample` and Settings values from Task 1.
- Produces: `RuViewClient(client: httpx.AsyncClient, base_url: str, api_token: SecretStr)` and `async sample() -> SensorSample`.
- Verified upstream schemas: `/health` returns `status`, `source`, `tick`, and `clients`; `/api/v1/sensing/latest` returns `source`, `tick`, and `classification.presence` or `{"status":"no data yet"}`.

- [ ] **Step 1: Write HTTPX MockTransport tests**

Cover bearer headers on both endpoints, a healthy ESP32 sample, non-ESP32 short-circuiting, `no data yet`, mismatched latest source, invalid schema, and HTTP failure using captured `httpx.Request` objects. The happy-path assertion is:

```python
sample = await ruv_client.sample()
assert sample == SensorSample(healthy_esp32=True, presence=True, tick=8)
assert [request.headers["Authorization"] for request in requests] == [
    "Bearer test-ruview-token",
    "Bearer test-ruview-token",
]
```

For a healthy response, use health `{"status":"ok","source":"esp32","tick":7,"clients":0}` and latest `{"source":"esp32","tick":8,"classification":{"presence":true}}` to prove that an advancing tick between requests is valid. Assert the header is exactly `Authorization: Bearer test-ruview-token` in the captured request, but never interpolate it into assertions on exception text.

- [ ] **Step 2: Verify adapter tests fail**

Run: `cd deploy/home-alarm && uv run pytest tests/test_ruview.py -v`

Expected: FAIL on missing `ruview_alarm.ruview`.

- [ ] **Step 3: Implement strict schema parsing and source gating**

Use private Pydantic response models with `extra="ignore"`. Request `/health` first; only request `/api/v1/sensing/latest` when status is `ok` and source is `esp32`. Return an unhealthy sample for an honest non-ESP32 source or `no data yet`. Wrap HTTP/status/schema failures as `RuViewError(operation: str, status_code: int | None)` whose string contains no URL or token; the service owns retry timing. Require latest source `esp32`, a nondecreasing tick value, and a real boolean presence value, but do not require equality with the earlier health tick because sensing can advance between requests.

- [ ] **Step 4: Run adapter tests and lint**

Run: `cd deploy/home-alarm && uv run pytest tests/test_ruview.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run ruff check src/ruview_alarm/ruview.py tests/test_ruview.py`

Expected: PASS.

- [ ] **Step 5: Commit the RuView adapter**

```bash
git add deploy/home-alarm/src/ruview_alarm/ruview.py deploy/home-alarm/tests/test_ruview.py
git commit -m "feat(alarm): add authenticated RuView polling"
```

### Task 5: Authorized, secret-safe Telegram adapter

**Files:**
- Create: `deploy/home-alarm/src/ruview_alarm/telegram.py`
- Create: `deploy/home-alarm/tests/test_telegram.py`

**Interfaces:**
- Consumes: `AlarmAction` and `TelegramUpdate` from Task 1.
- Produces: `TelegramClient(client, base_url, bot_token, allowed_chat_id)`, `async get_updates(offset, timeout)`, `async acknowledge_callback(callback_id)`, and `async send_message(text)`.
- `get_updates` returns every update ID, including unauthorized or unrecognized updates, so the service can persist `update_id + 1` and avoid replay loops.

- [ ] **Step 1: Write fake Bot API tests**

Use `httpx.MockTransport` and cover authorized text commands, authorized callback actions, unauthorized updates, unknown commands, offset/long-poll parameters, callback acknowledgement, configured-chat delivery, Bot API errors, and transport-error redaction. A representative authorization assertion is:

```python
updates = await telegram.get_updates(offset=41, timeout=20)
assert updates == [TelegramUpdate(update_id=41, chat_id=123, action=AlarmAction.ARM)]
assert captured_request.url.params["offset"] == "41"
assert captured_request.url.params["timeout"] == "20"
```

Recognize `/arm`, `/disarm`, and `/status` after stripping the optional `@botname`; inline callback data is exactly `arm`, `disarm`, or `status`. The public exception is `TelegramError(operation: str, status_code: int | None)` and its string must not contain the request URL or token.

- [ ] **Step 2: Verify Telegram tests fail**

Run: `cd deploy/home-alarm && uv run pytest tests/test_telegram.py -v`

Expected: FAIL on missing `ruview_alarm.telegram`.

- [ ] **Step 3: Implement Bot API calls with redacted errors**

Build the tokenized route only inside a private `_call(method, payload)` method. Never log `request.url`, an HTTPX exception string, payload dictionaries, or settings. Validate Bot API envelopes such as `{"ok": true, "result": []}` and raise `TelegramError` with only operation/status metadata otherwise.

Each `TelegramUpdate` must include its ID. Populate `action` only for the configured chat ID; retain `callback_id` for authorized callbacks so the service can acknowledge them. `send_message` must include an inline keyboard containing Arm, Disarm, and Status callback buttons.

- [ ] **Step 4: Run Telegram tests and lint**

Run: `cd deploy/home-alarm && uv run pytest tests/test_telegram.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run ruff check src/ruview_alarm/telegram.py tests/test_telegram.py`

Expected: PASS.

- [ ] **Step 5: Commit the Telegram adapter**

```bash
git add deploy/home-alarm/src/ruview_alarm/telegram.py deploy/home-alarm/tests/test_telegram.py
git commit -m "feat(alarm): add authorized Telegram controls"
```

### Task 6: Supervised service, retry policy, and health contract

**Files:**
- Create: `deploy/home-alarm/src/ruview_alarm/service.py`
- Create: `deploy/home-alarm/src/ruview_alarm/healthcheck.py`
- Create: `deploy/home-alarm/src/ruview_alarm/__main__.py`
- Create: `deploy/home-alarm/tests/test_service.py`
- Create: `deploy/home-alarm/tests/test_healthcheck.py`

**Interfaces:**
- Consumes: all Tasks 1–5 interfaces.
- Produces: `retry_delays() -> Iterator[float]`, `AlarmService`, `async run_alarm(settings: Settings) -> None`, `write_heartbeat(path, snapshot)`, and `check_health(path, now) -> int`.
- The service has four supervised loops: sensing, Telegram long-poll, notification delivery, and watchdog heartbeat.

- [ ] **Step 1: Write failing retry, persistence, supervision, and health tests**

Use fakes with `asyncio.Event` synchronization, never real sleeps or network. Cover restored startup status, state-before-notification ordering, offset persistence for every update, callback-after-durability ordering, delivery retry isolation, RuView outage behavior, Telegram outage behavior, unexpected task exit, graceful cancellation/client closure, and fresh/stale heartbeat validation. The retry contract is asserted exactly:

```python
def test_retry_delays_are_1_2_4_8_16_then_30_forever() -> None:
    assert list(itertools.islice(retry_delays(), 8)) == [1, 2, 4, 8, 16, 30, 30, 30]
```

Assert retry delays with `list(itertools.islice(retry_delays(), 8)) == [1, 2, 4, 8, 16, 30, 30, 30]`. Health data must name `main`, `sensing`, `telegram`, and `notifications`; reject sensing/notification ages over 45 seconds or Telegram age over 60 seconds.

- [ ] **Step 2: Verify service tests fail**

Run: `cd deploy/home-alarm && uv run pytest tests/test_service.py tests/test_healthcheck.py -v`

Expected: FAIL on missing service and healthcheck modules.

- [ ] **Step 3: Implement sequencing and isolated retry loops**

Construct one shared `httpx.AsyncClient` per remote service, each with explicit connect/read/write/pool timeouts. Load state before tasks start, restore the engine, queue `Alarm restored: armed` or `Alarm restored: disarmed`, then use `asyncio.TaskGroup` for the four loops.

For every Telegram update: compute `next_offset = update_id + 1`; if authorized, apply the command; synchronously save the new state/offset; acknowledge an authorized callback; then enqueue resulting notifications. Unauthorized and unknown updates still persist the offset. Notification failures remain on the delivery worker and never roll back state.

For sensing: call `sample`, pass it to `engine.observe(sample, loop.time())`, and enqueue events. Poll every 5 seconds on success. On transient adapter failure, pass `SensorSample(healthy_esp32=False)` to the engine, continue through the exact retry sequence, and cap each sleep so the engine is observed often enough to cross its 30-second offline threshold.

- [ ] **Step 4: Implement task liveness and process entry**

Write heartbeats atomically to `/tmp/ruview-alarm-health.json` as UTC epoch seconds for `main`, `sensing`, `telegram`, and `notifications`. The watchdog writes every 10 seconds and raises if any loop heartbeat exceeds its threshold. `check_health` returns exit code 0 only when the file is strict JSON and all four entries are fresh.

`__main__.py` configures UTC logging, loads `Settings`, runs `asyncio.run(run_alarm(settings))`, and exits non-zero on invalid settings/state or unexpected task failure without logging secret-bearing exception values.

- [ ] **Step 5: Run service, health, and full unit checks**

Run: `cd deploy/home-alarm && uv run pytest tests/test_service.py tests/test_healthcheck.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run pytest -v -m 'not container'`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run ruff check src tests`

Expected: PASS.

- [ ] **Step 6: Commit the supervised service**

```bash
git add deploy/home-alarm/src/ruview_alarm/service.py deploy/home-alarm/src/ruview_alarm/healthcheck.py deploy/home-alarm/src/ruview_alarm/__main__.py deploy/home-alarm/tests/test_service.py deploy/home-alarm/tests/test_healthcheck.py
git commit -m "feat(alarm): supervise sensing and Telegram loops"
```

### Task 7: Reproducible container and production Compose contract

**Files:**
- Create: `deploy/home-alarm/Dockerfile`
- Create: `deploy/home-alarm/compose.yaml`
- Create: `deploy/home-alarm/.env.example`
- Create: `deploy/home-alarm/.dockerignore`
- Create: `deploy/home-alarm/tests/test_compose.py`
- Create: `deploy/home-alarm/tests/fixtures/compose.env`
- Create: `deploy/home-alarm/uv.lock`

**Interfaces:**
- Consumes: the package and entry points from Tasks 1–6.
- Produces: production services `sensing-server` and `telegram-alarm`, private network `alarm-net`, and named volume `alarm-state`.

- [ ] **Step 1: Write static Compose and secret-safety tests**

Parse `docker compose --env-file tests/fixtures/compose.env config --format json` and assert:

```python
assert sensing["image"] == "docker.io/ruvnet/wifi-densepose@sha256:fac235102bebc8a9bfc5445645bc6908d02cf0244154e59b7bab297a574b5fae"
assert sensing["ports"] == [
    {"target": 3000, "published": "3000", "host_ip": "127.0.0.1", "protocol": "tcp", "mode": "ingress"},
    {"target": 5005, "published": "5005", "protocol": "udp", "mode": "ingress"},
]
assert sensing["environment"]["CSI_SOURCE"] == "esp32"
assert sensing["environment"]["RUVIEW_UDP_BIND"] == "0.0.0.0"
assert sensing["environment"]["RUVIEW_UDP_ALLOW"] == "198.51.100.42/32"
assert "3001" not in rendered
```

Also assert both services use `unless-stopped`, `cap_drop: [ALL]`, `no-new-privileges:true`, health checks, and only `alarm-net`; assert the alarm service is read-only, non-root, has `/tmp` as tmpfs, and mounts `alarm-state` at `/data`. Recursively scan committed deployment files and the rendered config to prove sentinel fixture secrets occur only in the generated test process input, not in source or Dockerfile layers.

- [ ] **Step 2: Verify packaging tests fail**

Run: `cd deploy/home-alarm && uv run pytest tests/test_compose.py -v`

Expected: FAIL because production packaging does not exist.

- [ ] **Step 3: Build the locked, non-root alarm image**

Use a multi-stage `python:3.12-slim` Dockerfile. Install a pinned `uv` binary copied from `ghcr.io/astral-sh/uv:0.10.9`, run `uv sync --frozen --no-dev`, copy only the virtual environment and package into a final image, create UID/GID 10001, and run `/app/.venv/bin/python -m ruview_alarm`. The health check command is `/app/.venv/bin/python -m ruview_alarm.healthcheck`.

Run: `cd deploy/home-alarm && uv lock`

Expected: `deploy/home-alarm/uv.lock` pins all direct and transitive dependencies without touching the repository-root `uv.lock`.

- [ ] **Step 4: Implement the exact production Compose boundary**

Configure `sensing-server` with the immutable digest, `CSI_SOURCE=esp32`, routable UDP bind and required allowlist, bearer token, loopback TCP publication, UDP publication, and a process health check. Configure `telegram-alarm` from the local Dockerfile with the required settings and `depends_on: sensing-server: condition: service_healthy`. Use mapping-form environment substitutions that fail when `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `RUVIEW_API_TOKEN`, or `RUVIEW_UDP_ALLOW` are unset.

`.env.example` uses only documentation values:

```dotenv
TELEGRAM_BOT_TOKEN=replace-with-telegram-bot-token
TELEGRAM_CHAT_ID=123456789
RUVIEW_API_TOKEN=replace-with-a-distinct-ruview-api-token
RUVIEW_UDP_ALLOW=198.51.100.42/32
```

- [ ] **Step 5: Validate config, lock, image, and tests**

Run: `cd deploy/home-alarm && uv sync --frozen --all-extras --dev`

Expected: PASS without changing `uv.lock`.

Run: `cd deploy/home-alarm && uv run pytest tests/test_compose.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && docker compose --env-file tests/fixtures/compose.env config --quiet`

Expected: exit 0.

Run: `cd deploy/home-alarm && docker build --pull --no-cache -t ruvnet/home-alarm:test .`

Expected: image builds successfully and runs as UID 10001.

- [ ] **Step 6: Commit reproducible deployment packaging**

```bash
git add deploy/home-alarm/pyproject.toml deploy/home-alarm/uv.lock deploy/home-alarm/Dockerfile deploy/home-alarm/compose.yaml deploy/home-alarm/.env.example deploy/home-alarm/.dockerignore deploy/home-alarm/tests/test_compose.py deploy/home-alarm/tests/fixtures/compose.env
git commit -m "feat(alarm): add pinned VPS deployment"
```

### Task 8: Service-integration and container smoke verification

**Files:**
- Create: `deploy/home-alarm/tests/fakes.py`
- Create: `deploy/home-alarm/tests/fake_telegram_api.py`
- Create: `deploy/home-alarm/tests/test_service_integration.py`
- Create: `deploy/home-alarm/tests/test_container_smoke.py`
- Create: `deploy/home-alarm/compose.smoke.yaml`
- Modify: `deploy/home-alarm/pyproject.toml`

**Interfaces:**
- Consumes: production service, image, and Compose interfaces from Tasks 1–7.
- Produces: hermetic fake RuView/Telegram service fixtures and a `container` pytest marker.

- [ ] **Step 1: Write the in-process service integration scenarios**

Start local `asyncio` HTTP servers on ephemeral loopback ports and exercise the real HTTP adapters plus service. Cover authorized arm → presence → all-clear with persisted offset, callback acknowledgement plus unauthorized chat suppression, delivery failure plus sensor loss/recovery, armed recreation plus immediate presence, and graceful client shutdown. The first scenario must end with assertions equivalent to:

```python
saved = load_state(settings.state_path)
assert saved.armed is True
assert saved.telegram_offset == 12
assert fake_telegram.message_texts == [
    "Alarm restored: disarmed",
    "Alarm armed",
    "Intrusion detected: presence changed from absent to present",
    "All clear: no presence for 60 continuous seconds",
]
```

The fake RuView endpoint must reject a missing/wrong bearer token; the fake Telegram endpoint must record updates, callback acknowledgements, and outbound messages. Inject short polling/offline/all-clear values through `Settings` constructor overrides so the suite completes quickly without weakening production defaults.

- [ ] **Step 2: Verify integration scenarios fail before fixture support**

Run: `cd deploy/home-alarm && uv run pytest tests/test_service_integration.py -v`

Expected: FAIL because the fake servers and orchestration fixture are incomplete.

- [ ] **Step 3: Implement hermetic fakes and make integration tests pass**

Use only Python standard-library asyncio networking or the already locked HTTP stack; bind to `127.0.0.1` with port 0; never contact external hosts. Each fake exposes explicit methods to queue Telegram updates and set RuView health/latest state. Teardown closes listeners and asserts no background task remains.

Run: `cd deploy/home-alarm && uv run pytest tests/test_service_integration.py -v`

Expected: all tests PASS.

- [ ] **Step 4: Add the production-like Compose smoke environment**

The smoke override changes only `CSI_SOURCE` to `simulated`, removes production UDP publication, supplies sentinel credentials, points `TELEGRAM_BASE_URL` to a `telegram-fake` service, and mounts a temporary test volume. `tests/fake_telegram_api.py` is a standard-library HTTP service with Bot API-compatible `getUpdates`, `sendMessage`, and `answerCallbackQuery` routes plus test-only `/enqueue` and `/messages` control routes; it stores no credentials and is reachable from the host only on `127.0.0.1:18080`. The test must:

1. start the immutable RuView image and locally built alarm image;
2. verify unauthorized `/api/v1/sensing/latest` returns 401 and bearer-authenticated access succeeds;
3. recreate only `telegram-alarm` and verify its saved armed state remains true;
4. inspect published ports and assert only `127.0.0.1:3000` is present and 3001 is absent;
5. inspect the built alarm image environment/history and assert the sentinels are absent; and
6. always run `docker compose down --volumes --remove-orphans` for its uniquely named project in `finally`.

Mark this test `@pytest.mark.container`; skip only when `docker info` proves the daemon unavailable, and report that skip as an unmet Level 3 gate rather than a pass.

- [ ] **Step 5: Run all three software verification levels**

Run: `cd deploy/home-alarm && uv run pytest -v -m 'not container'`

Expected: all unit and service-integration tests PASS.

Run: `cd deploy/home-alarm && uv run pytest tests/test_container_smoke.py -v -m container`

Expected: PASS with the immutable RuView image and clean teardown; a Docker-unavailable skip blocks the software-complete claim.

Run: `cd deploy/home-alarm && uv run ruff check src tests scripts`

Expected: PASS.

- [ ] **Step 6: Commit the verification harness**

```bash
git add deploy/home-alarm/pyproject.toml deploy/home-alarm/tests/fakes.py deploy/home-alarm/tests/fake_telegram_api.py deploy/home-alarm/tests/test_service_integration.py deploy/home-alarm/tests/test_container_smoke.py deploy/home-alarm/compose.smoke.yaml
git commit -m "test(alarm): verify service and container recovery"
```

### Task 9: Secure ESP32 provisioning and operator documentation

**Files:**
- Create: `deploy/home-alarm/scripts/provision_esp32.py`
- Create: `deploy/home-alarm/tests/test_provision_esp32.py`
- Create: `deploy/home-alarm/README.md`
- Create: `deploy/home-alarm/AGENTS.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: upstream `firmware/esp32-csi-node/provision.py` and its flags `--port`, `--ssid`, `--password`, `--target-ip`, `--target-port`, `--node-id`, `--chip`, and `--state-dir`.
- Produces: interactive `main(argv: Sequence[str] | None = None) -> int`; no unattended or password-bearing CLI interface.

- [ ] **Step 1: Write provisioning safety tests**

Mock `input`, `getpass.getpass`, `tempfile.TemporaryDirectory`, `runpy.run_path`, and `sys.argv`. Cover literal VPS IPv4/nonempty SSID/node ID validation, fixed UDP port 5005, exact serial-port confirmation, cancellation, password prompting, in-process ESP32-S3 invocation, NVS-only arguments, and output/error redaction. The successful invocation must assert:

```python
assert upstream_argv == [
    str(provisioner_path),
    "--port", "/dev/cu.usbserial-TEST",
    "--chip", "esp32s3",
    "--ssid", "Home-2G",
    "--password", "test-wifi-secret",
    "--target-ip", "203.0.113.10",
    "--target-port", "5005",
    "--node-id", "1",
    "--state-dir", str(private_state_dir),
]
```

The expected internal upstream argument list contains `--chip esp32s3`, `--target-port 5005`, and the private temporary `--state-dir`. It must not contain a full-flash operation; upstream provisioning writes only NVS offset `0x9000`.

- [ ] **Step 2: Verify helper tests fail**

Run: `cd deploy/home-alarm && uv run pytest tests/test_provision_esp32.py -v`

Expected: FAIL because the wrapper does not exist.

- [ ] **Step 3: Implement the interactive in-process wrapper**

Accept only non-secret `--port`, `--ssid`, `--vps-ip`, and `--node-id`; validate node ID in the upstream range 0–255. Parse VPS target with `ipaddress.IPv4Address`; set UDP port internally to 5005; prompt with `getpass`; require the operator to retype the exact serial port; then run upstream's provisioner with `runpy.run_path(provisioner_path, run_name="__main__")` while temporarily replacing Python-level `sys.argv`. Restore `sys.argv` in `finally`, drop the local password reference after return, and use a private `TemporaryDirectory` so upstream's per-port JSON cannot persist.

- [ ] **Step 4: Write the operator runbook and local agent guidance**

Document exact commands and honest gates:

- create a mode-`0600` production `.env` from `.env.example`;
- build pinned display-less firmware with `espressif/idf:v5.4` and `-DSDKCONFIG_DEFAULTS='sdkconfig.defaults;sdkconfig.defaults.devkitc'`, then record SHA-256 hashes for the bootloader, partition table, OTA data, and app binaries;
- full-flash only after explicit UART/board confirmation, then use the helper for later Wi-Fi/VPS NVS changes;
- deploy with `docker compose pull`, `docker compose build --pull`, `docker compose config`, and `docker compose up -d`;
- perform temporary UDP source discovery, then install the same home `/32` in `RUVIEW_UDP_ALLOW` and the VPS firewall;
- validate `/health`, authenticated latest sensing, Telegram authorization, intrusion/all-clear, state restoration, and rollback;
- never claim hardware success without serial and end-to-end evidence.

The subsystem `AGENTS.md` records the package map, commands, pinning rule, secret boundaries, and distinction between software tests and hardware acceptance. The runbook uses `uv run --extra provision python scripts/provision_esp32.py` for NVS changes and the exact display-less Docker build command already documented in `sdkconfig.defaults.devkitc`. Add `deploy/home-alarm/.env` and `deploy/home-alarm/.env.*` to `.gitignore`, then explicitly unignore `.env.example` and `tests/fixtures/compose.env`.

- [ ] **Step 5: Run helper, documentation, secret, and full regression checks**

Run: `cd deploy/home-alarm && uv run pytest tests/test_provision_esp32.py -v`

Expected: all tests PASS.

Run: `cd deploy/home-alarm && uv run pytest -v -m 'not container' && uv run ruff check src tests scripts`

Expected: all checks PASS.

Run: `git grep -nE '(TELEGRAM_BOT_TOKEN|RUVIEW_API_TOKEN|password)[[:space:]]*=[[:space:]]*[^$<{]' -- . ':!docs/superpowers' ':!deploy/home-alarm/.env.example' ':!deploy/home-alarm/tests/fixtures/compose.env'`

Expected: no credential assignments in tracked production/test sources.

- [ ] **Step 6: Commit provisioning and runbook**

```bash
git add .gitignore deploy/home-alarm/scripts/provision_esp32.py deploy/home-alarm/tests/test_provision_esp32.py deploy/home-alarm/README.md deploy/home-alarm/AGENTS.md
git commit -m "docs(alarm): add secure provisioning and VPS runbook"
```

### Task 10: Final software gate and evidence record

**Files:**
- Create: `deploy/home-alarm/verification/software-verification.md`

**Interfaces:**
- Consumes: all implementation and verification artifacts.
- Produces: a dated, reproducible Level 1–3 evidence record; it must not claim Level 4 completion.

- [ ] **Step 1: Run the complete locked test and lint suite**

Run: `cd deploy/home-alarm && uv sync --frozen --all-extras --dev && uv run pytest -v -m 'not container' && uv run ruff check src tests scripts`

Expected: dependency lock unchanged, all tests PASS, Ruff PASS.

- [ ] **Step 2: Run the immutable container gate**

Run: `cd deploy/home-alarm && uv run pytest tests/test_container_smoke.py -v -m container`

Expected: PASS; Docker-unavailable or registry-unavailable skips/failures remain an open Level 3 gate.

- [ ] **Step 3: Verify Compose and repository cleanliness**

Run: `cd deploy/home-alarm && docker compose --env-file tests/fixtures/compose.env config --quiet`

Expected: exit 0.

Run: `git status --short && git diff --check && git ls-files deploy/home-alarm | sort`

Expected: no accidental root `uv.lock` staging, no whitespace errors, and only intended home-alarm files tracked.

- [ ] **Step 4: Record exact evidence without secrets**

Write the date, git commit, immutable RuView digest, Python/uv/Docker versions, each command, pass/fail count, and any explicitly unmet hardware/VPS gates. Do not paste environment values, IP addresses other than documentation ranges, bot identifiers, image environment dumps, or CSI payloads.

- [ ] **Step 5: Commit the software evidence**

```bash
git add deploy/home-alarm/verification/software-verification.md
git commit -m "test(alarm): record software verification evidence"
```

## Post-Implementation Hardware/VPS Acceptance

This is an operator-assisted acceptance sequence, not an implementation task and not a prerequisite for committing the software:

1. Obtain physical USB access to the Freenove ESP32-S3 and explicit confirmation of its detected serial port.
2. Build and hash the pinned ESP-IDF 5.4 firmware, full-flash it once with verified offsets, then capture a redacted serial boot/runtime log showing DHCP and UDP sends.
3. Obtain VPS SSH/firewall access and a real mode-`0600` `.env` via an operator-controlled secure channel.
4. Deploy the pinned Compose stack, briefly discover the home's real egress address, and close both application/firewall UDP allowlists to that `/32`.
5. Verify live ESP32 health/ticks, Telegram authorization, arm/intrusion/all-clear, container/VPS restart restoration, and rollback readiness.
6. Store only hashes, command outcomes, and redacted logs in the acceptance record; never commit secrets or raw/private CSI.
