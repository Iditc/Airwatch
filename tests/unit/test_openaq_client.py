from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.data.openaq_client import OpenAQClient


@pytest.fixture
def mock_client() -> OpenAQClient:
    return OpenAQClient(api_key="test_key")


class TestGetIsraelCountryId:
    def test_finds_israel(self, mock_client: OpenAQClient) -> None:
        mock_response = {
            "results": [
                {"id": 1, "code": "US", "name": "United States"},
                {"id": 42, "code": "IL", "name": "Israel"},
            ]
        }
        with patch.object(mock_client, "_get", return_value=mock_response):
            assert mock_client.get_israel_country_id() == 42

    def test_raises_if_not_found(self, mock_client: OpenAQClient) -> None:
        mock_response = {"results": [{"id": 1, "code": "US", "name": "United States"}]}
        with (
            patch.object(mock_client, "_get", return_value=mock_response),
            pytest.raises(ValueError, match="IL not found"),
        ):
            mock_client.get_israel_country_id()


class TestGetStations:
    def test_parses_stations(self, mock_client: OpenAQClient) -> None:
        mock_response = {
            "results": [
                {
                    "id": 100,
                    "name": "Haifa Nesher",
                    "locality": "Haifa",
                    "coordinates": {"latitude": 32.79, "longitude": 35.04},
                    "sensors": [
                        {"parameter": {"name": "pm25"}},
                        {"parameter": {"name": "pm10"}},
                    ],
                }
            ]
        }
        with patch.object(mock_client, "_get", return_value=mock_response):
            stations = mock_client.get_stations(country_id=42)
        assert len(stations) == 1
        assert stations[0].name == "Haifa Nesher"
        assert stations[0].pollutants == ["pm25", "pm10"]
        assert stations[0].latitude == 32.79

    def test_handles_missing_locality(self, mock_client: OpenAQClient) -> None:
        mock_response = {
            "results": [
                {
                    "id": 101,
                    "name": "Unknown Station",
                    "coordinates": {"latitude": 31.0, "longitude": 34.0},
                    "sensors": [],
                }
            ]
        }
        with patch.object(mock_client, "_get", return_value=mock_response):
            stations = mock_client.get_stations()
        assert stations[0].city == "Unknown"
        assert stations[0].pollutants == []


class TestGetSensorIds:
    def test_parses_sensors(self, mock_client: OpenAQClient) -> None:
        mock_response = {
            "results": [
                {
                    "sensors": [
                        {"id": 101, "parameter": {"name": "pm25"}},
                        {"id": 102, "parameter": {"name": "no2"}},
                    ]
                }
            ]
        }
        with patch.object(mock_client, "_get", return_value=mock_response):
            sensors = mock_client.get_sensor_ids(location_id=100)
        assert sensors == {"pm25": 101, "no2": 102}

    def test_empty_sensors(self, mock_client: OpenAQClient) -> None:
        mock_response: dict[str, list[dict[str, list[object]]]] = {"results": [{"sensors": []}]}
        with patch.object(mock_client, "_get", return_value=mock_response):
            sensors = mock_client.get_sensor_ids(location_id=100)
        assert sensors == {}


class TestGetMeasurements:
    def test_parses_measurements(self, mock_client: OpenAQClient) -> None:
        mock_response = {
            "results": [
                {
                    "period": {"datetimeTo": {"utc": "2025-01-15T10:00:00Z"}},
                    "parameter": {"name": "pm25", "units": "µg/m³"},
                    "value": 42.5,
                }
            ]
        }
        with patch.object(mock_client, "_get", return_value=mock_response):
            readings = mock_client.get_measurements(sensor_id=101, station_id="100")
        assert len(readings) == 1
        assert readings[0].pollutant == "pm25"
        assert readings[0].value == 42.5
        assert readings[0].station_id == "100"


class TestRetryLogic:
    def test_retries_on_rate_limit(self, mock_client: OpenAQClient) -> None:
        rate_limit_response = httpx.Response(
            429,
            request=httpx.Request("GET", "https://api.openaq.org/v3/countries"),
        )
        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.raise_for_status = MagicMock()
        ok_response.json.return_value = {"results": []}

        mock_client.client.get = MagicMock(  # type: ignore[assignment]
            side_effect=[
                httpx.HTTPStatusError(
                    "rate limited",
                    request=MagicMock(),
                    response=rate_limit_response,
                ),
                ok_response,
            ]
        )
        with patch("src.data.openaq_client.time.sleep"):
            result = mock_client._get("/countries")
        assert result == {"results": []}
