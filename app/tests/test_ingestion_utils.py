"""
Unit tests for app/data_ingestion/ingestion_utils.py.

All Tuya API interaction is mocked — no network calls are ever made.
"""
import json

import pytest

from app.data_ingestion.ingestion_utils import (
    fetch_status_logs,
    get_time_range_ms,
    load_device_mapping,
)


# --- get_time_range_ms ---


def test_get_time_range_ms_window_math():
    hours_ago = 3
    start_ms, end_ms = get_time_range_ms(hours_ago)

    assert isinstance(start_ms, int)
    assert isinstance(end_ms, int)
    assert start_ms < end_ms

    expected_delta_ms = hours_ago * 60 * 60 * 1000
    actual_delta_ms = end_ms - start_ms
    # Allow a small tolerance for the time elapsed between the two
    # datetime.now() calls inside the function.
    assert abs(actual_delta_ms - expected_delta_ms) < 1000


def test_get_time_range_ms_zero_hours():
    start_ms, end_ms = get_time_range_ms(0)
    assert 0 <= end_ms - start_ms < 1000


def test_get_time_range_ms_accepts_logger():
    calls = []

    class FakeLogger:
        def info(self, message):
            calls.append(message)

    get_time_range_ms(1, logger=FakeLogger())
    assert len(calls) == 1
    assert "Querying logs" in calls[0]


# --- load_device_mapping ---


def test_load_device_mapping_success(tmp_path):
    mapping = {"device-1": "Living Room Lamp", "device-2": "Bedroom Fan"}
    mapping_file = tmp_path / "device_mapping.json"
    mapping_file.write_text(json.dumps(mapping), encoding="utf-8")

    result = load_device_mapping(str(mapping_file))

    assert result == mapping


def test_load_device_mapping_missing_file_returns_none(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"

    result = load_device_mapping(str(missing_path))

    assert result is None


def test_load_device_mapping_invalid_json_returns_none(tmp_path):
    bad_file = tmp_path / "bad_mapping.json"
    bad_file.write_text("{not valid json", encoding="utf-8")

    result = load_device_mapping(str(bad_file))

    assert result is None


def test_load_device_mapping_logs_errors(tmp_path):
    calls = []

    class FakeLogger:
        def error(self, message):
            calls.append(message)

        def info(self, message):
            pass

    missing_path = tmp_path / "nope.json"
    result = load_device_mapping(str(missing_path), logger=FakeLogger())

    assert result is None
    assert any("not found" in c for c in calls)


# --- fetch_status_logs pagination ---


class FakeOpenAPIClient:
    """Mocked Tuya OpenAPI client that serves canned paginated responses."""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        page = self._pages[len(self.calls) - 1]
        return page


def test_fetch_status_logs_aggregates_paginated_results():
    pages = [
        {
            "success": True,
            "result": {
                "logs": [{"code": "switch_1", "value": True, "event_time": 1}],
                "has_more": True,
                "last_row_key": "row-1",
            },
        },
        {
            "success": True,
            "result": {
                "logs": [
                    {"code": "switch_1", "value": False, "event_time": 2},
                    {"code": "switch_1", "value": True, "event_time": 3},
                ],
                "has_more": False,
                "last_row_key": "row-2",
            },
        },
    ]
    client = FakeOpenAPIClient(pages)

    logs = fetch_status_logs(client, "device-1", "switch_1", 0, 1000)

    assert len(logs) == 3
    assert [log["event_time"] for log in logs] == [1, 2, 3]
    # Two pages requested.
    assert len(client.calls) == 2
    # Second request should carry the last_row_key returned by the first page.
    _, second_params = client.calls[1]
    assert second_params["last_row_key"] == "row-1"


def test_fetch_status_logs_stops_when_has_more_false():
    pages = [
        {
            "success": True,
            "result": {
                "logs": [{"code": "switch_1", "value": True, "event_time": 1}],
                "has_more": False,
                "last_row_key": "",
            },
        },
    ]
    client = FakeOpenAPIClient(pages)

    logs = fetch_status_logs(client, "device-1", "switch_1", 0, 1000)

    assert len(logs) == 1
    assert len(client.calls) == 1


def test_fetch_status_logs_stops_on_api_error():
    pages = [
        {"success": False, "msg": "boom"},
    ]
    client = FakeOpenAPIClient(pages)

    logs = fetch_status_logs(client, "device-1", "switch_1", 0, 1000)

    assert logs == []
    assert len(client.calls) == 1


def test_fetch_status_logs_stops_on_missing_last_row_key():
    # has_more True but no last_row_key returned — must not loop forever.
    pages = [
        {
            "success": True,
            "result": {
                "logs": [{"code": "switch_1", "value": True, "event_time": 1}],
                "has_more": True,
                "last_row_key": "",
            },
        },
    ]
    client = FakeOpenAPIClient(pages)

    logs = fetch_status_logs(client, "device-1", "switch_1", 0, 1000)

    assert len(logs) == 1
    assert len(client.calls) == 1
