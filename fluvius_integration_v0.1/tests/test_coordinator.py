# pytest-asyncio test for FluviusCoordinator
import pytest

from datetime import datetime, timezone

# Import the coordinator class from the integration
from custom_components.fluvius_electricity_belgium import FluviusCoordinator

@pytest.mark.asyncio
async def test_coordinator_fetch_and_parse(monkeypatch):
    """
    Test that coordinator fetches data using a mocked token fetch and HTTP session,
    and that returned data is parsed as expected by sensors (consumption/injection/net).
    """
    # Prepare fake hass with minimal async_add_executor_job
    class FakeHass:
        async def async_add_executor_job(self, func, *args):
            # Simulate sync token fetch helper being run in executor
            return func(*args)

    hass = FakeHass()

    # Mock token fetch helper in module to return a fake bearer token
    def fake_fetch_token(username, password):
        return "Bearer faketoken"

    monkeypatch.setattr(
        "custom_components.fluvius_electricity_belgium._fetch_bearer_token_sync",
        fake_fetch_token,
    )

    # Create sample API response data (one period with a consumption and an injection reading)
    sample_api_response = [
        {
            "d": datetime.now(timezone.utc).isoformat(),
            "de": datetime.now(timezone.utc).isoformat(),
            "v": [
                {"dc": 1, "t": 1, "st": 0, "v": 1.5, "vs": 2, "u": 3},
                {"dc": 2, "t": 1, "st": 0, "v": 0.6, "vs": 2, "u": 3},
            ],
        }
    ]

    # Create fake session.get response
    class FakeResponse:
        def __init__(self, status, json_data):
            self.status = status
            self._json = json_data

        async def text(self):
            import json
            return json.dumps(self._json)

        async def json(self):
            return self._json

    class FakeSession:
        async def get(self, url, params=None, headers=None, timeout=None):
            # Return a 200 with sample json
            return FakeResponse(200, sample_api_response)

    # Monkeypatch async_get_clientsession to return our fake session
    monkeypatch.setattr(
        "custom_components.fluvius_electricity_belgium.async_get_clientsession",
        lambda hass_arg: FakeSession(),
    )

    # Instantiate coordinator with fake credentials and small time window
    coordinator = FluviusCoordinator(
        hass=hass,
        name="test",
        username="user@example.com",
        password="pass",
        ean="5414XXXXXXXXXXXXX",
        meter_id="1SAG1111111111",
        api_base="https://mijn.fluvius.be",
        granularity="1",
        time_window_hours=1,
        update_interval=60,
    )

    # Run update to fetch data
    data = await coordinator._async_update_data()

    # Validate data came back and matches sample
    assert isinstance(data, list)
    assert len(data) == 1
    day = data[0]
    assert "v" in day
    readings = day["v"]
    assert any(r.get("dc") == 1 for r in readings)
    assert any(r.get("dc") == 2 for r in readings)

    # Also test simple consumption/injection/net computations using the same logic as sensors
    total_consumption = 0.0
    total_injection = 0.0
    for day in data:
        for reading in day.get("v", []):
            val = reading.get("v", 0)
            if reading.get("dc") == 1:
                total_consumption += float(val)
            elif reading.get("dc") == 2:
                total_injection += float(val)

    assert total_consumption == pytest.approx(1.5)
    assert total_injection == pytest.approx(0.6)
    assert (total_consumption - total_injection) == pytest.approx(0.9)
