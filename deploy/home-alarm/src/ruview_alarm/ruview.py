"""Authenticated client for the RuView sensing service."""

from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt, ValidationError

from ruview_alarm.models import SensorSample


class RuViewError(Exception):
    """A retryable RuView transport, status, or schema failure."""

    def __init__(self, operation: str, status_code: int | None = None) -> None:
        """Record the failed operation without retaining sensitive request details."""
        self.operation = operation
        self.status_code = status_code
        detail = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"RuView {operation} request failed{detail}")


class _HealthResponse(BaseModel):
    """The portion of a RuView health response required by the adapter."""

    model_config = ConfigDict(extra="ignore", strict=True)

    status: str
    source: str
    tick: StrictInt = Field(ge=0)
    clients: StrictInt = Field(ge=0)


class _Classification(BaseModel):
    """The sensing classification carried by a latest response."""

    model_config = ConfigDict(extra="ignore", strict=True)

    presence: StrictBool


class _LatestResponse(BaseModel):
    """The portion of a RuView latest-sensing response required by the adapter."""

    model_config = ConfigDict(extra="ignore", strict=True)

    source: str
    tick: StrictInt = Field(ge=0)
    classification: _Classification


class RuViewClient:
    """Poll the authenticated RuView API for a trustworthy ESP32 observation."""

    _HEALTH_PATH: ClassVar[str] = "/health"
    _LATEST_PATH: ClassVar[str] = "/api/v1/sensing/latest"

    def __init__(self, client: httpx.AsyncClient, base_url: str, api_token: SecretStr) -> None:
        """Create an adapter using the caller-owned HTTP client."""
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token

    async def sample(self) -> SensorSample:
        """Return the latest ESP32 sample or an honest unhealthy observation."""
        health = self._parse_health(await self._request("health", self._HEALTH_PATH))
        if health.status != "ok" or health.source != "esp32":
            return SensorSample(healthy_esp32=False)

        latest_payload = await self._request("latest", self._LATEST_PATH)
        if latest_payload == {"status": "no data yet"}:
            return SensorSample(healthy_esp32=False)

        latest = self._parse_latest(latest_payload)
        if latest.source != "esp32":
            return SensorSample(healthy_esp32=False)
        if latest.tick < health.tick:
            raise RuViewError("latest")

        return SensorSample(healthy_esp32=True, presence=latest.classification.presence, tick=latest.tick)

    async def _request(self, operation: str, path: str) -> Any:
        """Fetch JSON, redacting transport and protocol details from raised errors."""
        try:
            response = await self._client.get(
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._api_token.get_secret_value()}"},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            raise RuViewError(operation, error.response.status_code) from None
        except (httpx.HTTPError, ValueError):
            raise RuViewError(operation) from None

    @staticmethod
    def _parse_health(payload: Any) -> _HealthResponse:
        """Validate the health schema and redact validation details on failure."""
        try:
            return _HealthResponse.model_validate(payload)
        except ValidationError:
            raise RuViewError("health") from None

    @staticmethod
    def _parse_latest(payload: Any) -> _LatestResponse:
        """Validate the sensing schema and redact validation details on failure."""
        try:
            return _LatestResponse.model_validate(payload)
        except ValidationError:
            raise RuViewError("latest") from None
