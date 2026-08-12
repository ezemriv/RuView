"""Tests for authenticated, schema-validated RuView polling."""

import httpx
import pytest
from pydantic import SecretStr

from ruview_alarm.models import SensorSample
from ruview_alarm.ruview import RuViewClient, RuViewError


def client_for(
    handler: httpx.AsyncBaseTransport | httpx.MockTransport,
) -> tuple[RuViewClient, httpx.AsyncClient]:
    """Build the adapter with an in-memory HTTP transport."""
    client = httpx.AsyncClient(transport=handler, base_url="http://ruview.test")
    return (
        RuViewClient(
            client=client,
            base_url="http://ruview.test",
            api_token=SecretStr("test-ruview-token"),
        ),
        client,
    )


async def test_sample_returns_healthy_esp32_presence_with_bearer_auth() -> None:
    """The valid ESP32 health and latest pair returns the latest observation."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok", "source": "esp32", "tick": 7, "clients": 0},
            )
        return httpx.Response(
            200,
            json={"source": "esp32", "tick": 8, "classification": {"presence": True}},
        )

    ruv_client, client = client_for(httpx.MockTransport(handler))
    try:
        sample = await ruv_client.sample()
    finally:
        await client.aclose()

    assert sample == SensorSample(healthy_esp32=True, presence=True, tick=8)
    assert [request.url.path for request in requests] == ["/health", "/api/v1/sensing/latest"]
    assert [request.headers["Authorization"] for request in requests] == [
        "Bearer test-ruview-token",
        "Bearer test-ruview-token",
    ]


@pytest.mark.parametrize(
    ("health", "expected_requests"),
    [
        ({"status": "ok", "source": "simulator", "tick": 7, "clients": 0}, 1),
        ({"status": "degraded", "source": "esp32", "tick": 7, "clients": 0}, 1),
    ],
)
async def test_sample_short_circuits_honest_unhealthy_health(
    health: dict[str, object], expected_requests: int
) -> None:
    """A non-ESP32 or non-ok health report remains unhealthy without sensing."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=health)

    ruv_client, client = client_for(httpx.MockTransport(handler))
    try:
        sample = await ruv_client.sample()
    finally:
        await client.aclose()

    assert sample == SensorSample(healthy_esp32=False)
    assert len(requests) == expected_requests
    assert requests[0].headers["Authorization"] == "Bearer test-ruview-token"


async def test_sample_returns_unhealthy_when_latest_reports_no_data_yet() -> None:
    """An empty sensing stream is an honest unhealthy result, not a retryable failure."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok", "source": "esp32", "tick": 7, "clients": 0},
            )
        return httpx.Response(200, json={"status": "no data yet"})

    ruv_client, client = client_for(httpx.MockTransport(handler))
    try:
        sample = await ruv_client.sample()
    finally:
        await client.aclose()

    assert sample == SensorSample(healthy_esp32=False)
    assert len(requests) == 2


async def test_sample_returns_unhealthy_when_latest_source_is_not_esp32() -> None:
    """A latest observation from another source cannot establish ESP32 health."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok", "source": "esp32", "tick": 7, "clients": 0},
            )
        return httpx.Response(
            200,
            json={"source": "simulator", "tick": 8, "classification": {"presence": True}},
        )

    ruv_client, client = client_for(httpx.MockTransport(handler))
    try:
        sample = await ruv_client.sample()
    finally:
        await client.aclose()

    assert sample == SensorSample(healthy_esp32=False)


@pytest.mark.parametrize(
    "latest",
    [
        {"source": "esp32", "tick": 6, "classification": {"presence": True}},
        {"source": "esp32", "tick": 8, "classification": {"presence": "true"}},
        {"source": "esp32", "classification": {"presence": True}},
    ],
)
async def test_sample_wraps_invalid_latest_schema_without_secrets(latest: dict[str, object]) -> None:
    """Malformed sensing data raises a redacted retryable error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok", "source": "esp32", "tick": 7, "clients": 0},
            )
        return httpx.Response(200, json=latest)

    ruv_client, client = client_for(httpx.MockTransport(handler))
    try:
        with pytest.raises(RuViewError) as error:
            await ruv_client.sample()
    finally:
        await client.aclose()

    assert error.value.operation == "latest"
    assert error.value.status_code is None
    assert "ruview.test" not in str(error.value)
    assert "test-ruview-token" not in str(error.value)


async def test_sample_wraps_http_failure_without_url_or_token() -> None:
    """HTTP failures become redacted retryable adapter errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    ruv_client, client = client_for(httpx.MockTransport(handler))
    try:
        with pytest.raises(RuViewError) as error:
            await ruv_client.sample()
    finally:
        await client.aclose()

    assert error.value.operation == "health"
    assert error.value.status_code == 503
    assert "ruview.test" not in str(error.value)
    assert "test-ruview-token" not in str(error.value)
