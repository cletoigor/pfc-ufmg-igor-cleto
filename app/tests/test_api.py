"""
Tests for app/api/server.py (the Starlette backend).

Uses starlette.testclient.TestClient (sync, requests-like interface backed by
httpx). `/api/agent/stream` is exercised with `run_agent` monkeypatched to a
stub — never a real Ollama/Gemini/Anthropic call.
"""
import json

import pytest
from starlette.testclient import TestClient

from app.api import data_access, server


@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Same isolation as test_data_access.py — never touch real app/data/."""
    fake_warehouse = tmp_path / "warehouse.duckdb"
    fake_staging_glob = str(tmp_path / "staging" / "**" / "*.parquet")
    fake_mart_globs = {
        key: str(tmp_path / "marts" / key / "**" / "*.parquet")
        for key in data_access.MART_GLOBS
    }
    monkeypatch.setattr(data_access, "WAREHOUSE_DB_PATH", str(fake_warehouse))
    monkeypatch.setattr(data_access, "MART_GLOBS", fake_mart_globs)
    monkeypatch.setattr(data_access, "STAGING_GLOB", fake_staging_glob)

    mapping_path = tmp_path / "device_mapping.json"
    mapping_path.write_text(json.dumps({"d1": "Lamp", "d2": "Fan"}))
    monkeypatch.setattr(data_access, "DEVICE_MAPPING_PATH", str(mapping_path))
    yield


@pytest.fixture
def client():
    return TestClient(server.app)


# --- /api/overview ---


def test_overview_returns_200_and_empty_shape_with_no_data(client):
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["empty"] is True
    assert body["source"] is None
    assert body["all_devices"] == ["Fan", "Lamp"]
    assert len(body["kpis"]) == 4


def _seed_warehouse(tmp_path_factory=None, *, monkeypatch=None):
    pass  # placeholder not used; see inline seeding in the filtering test below


def test_overview_devices_filter(monkeypatch, tmp_path):
    import duckdb
    import pandas as pd

    warehouse = tmp_path / "wh.duckdb"
    conn = duckdb.connect(str(warehouse))
    try:
        end = pd.Timestamp("2026-09-06 22:51:24")
        conn.execute(
            """
            CREATE TABLE device_state_intervals AS SELECT * FROM (VALUES
                ('d1', 'Lamp', 'switch_1', TIMESTAMP '2026-09-06 17:00:00', ?, 231.4, true),
                ('d2', 'Fan',  'switch_1', TIMESTAMP '2026-09-06 18:00:00', ?, 171.4, true)
            ) t(device_id, device_name, switch_code, interval_start, interval_end,
                duration_minutes, is_on)
            """,
            [end, end],
        )
        conn.execute(
            """
            CREATE TABLE device_metrics_daily AS SELECT * FROM (VALUES
                ('d1', 'Lamp', DATE '2026-09-06', 10, TIMESTAMP '2026-09-06 17:10:00', 2),
                ('d2', 'Fan',  DATE '2026-09-06', 15, TIMESTAMP '2026-09-06 22:51:24', 3)
            ) t(device_id, device_name, event_day, event_count, last_seen_at, on_event_count)
            """
        )
        conn.execute(
            """
            CREATE TABLE device_on_time_daily AS SELECT * FROM (VALUES
                ('d1', 'Lamp', DATE '2026-09-06', 231.4, 1, 231.4, 0.0),
                ('d2', 'Fan',  DATE '2026-09-06', 171.4, 1, 171.4, 0.0)
            ) t(device_id, device_name, event_day, on_minutes, on_sessions,
                longest_session_minutes, overnight_on_minutes)
            """
        )
    finally:
        conn.close()
    monkeypatch.setattr(data_access, "WAREHOUSE_DB_PATH", str(warehouse))

    client = TestClient(server.app)
    resp = client.get("/api/overview", params={"days": "all", "devices": "Lamp"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["all_devices"] == ["Fan", "Lamp"]
    assert body["timeline"]["lanes"] == ["Lamp"]
    assert {e["device"] for e in body["on_time"]} == {"Lamp"}


# --- /api/health ---


def test_health_returns_200_and_never_raises(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "data_source", "latest_event", "freshness_label",
        "provider", "provider_label", "model", "available", "guidance",
    }
    assert body["available"] in (True, False)


# --- /api/agent/stream ---


def _parse_sse(text: str):
    """Parses a raw SSE stream body into a list of (event, data) pairs."""
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        events.append((event_name, data))
    return events


def test_agent_stream_forwards_events_in_order_and_suppresses_done(monkeypatch, client):
    def fake_run_agent(question, *, dry_run=True, history=None, on_event=None):
        on_event({"type": "model_call", "iteration": 1})
        on_event({"type": "tool_call_start", "tool": "query_iot_data", "input": {"sql": "SELECT 1"}})
        on_event({"type": "tool_call_end", "tool": "query_iot_data", "output": "{}",
                   "duration_ms": 5, "is_error": False})
        on_event({"type": "done", "reply": "The answer is 1."})
        return {"reply": "The answer is 1.", "tool_trace": [{"tool": "query_iot_data"}]}

    monkeypatch.setattr("app.agent.agent.run_agent", fake_run_agent)

    resp = client.get("/api/agent/stream", params={"q": "hi", "dry_run": "1"})
    assert resp.status_code == 200

    events = _parse_sse(resp.text)
    kinds = [e[0] for e in events]

    assert "done" not in kinds
    assert kinds == ["model_call", "tool_call_start", "tool_call_end", "result"]

    tool_start = events[1][1]
    assert tool_start["tool"] == "query_iot_data"
    assert tool_start["label"] == "Querying the warehouse"

    result = events[-1][1]
    assert result["reply"] == "The answer is 1."


def test_agent_stream_emits_error_event_with_http_200_on_exception(monkeypatch, client):
    def raising_run_agent(question, *, dry_run=True, history=None, on_event=None):
        on_event({"type": "model_call", "iteration": 1})
        raise RuntimeError("503 UNAVAILABLE: model overloaded")

    monkeypatch.setattr("app.agent.agent.run_agent", raising_run_agent)

    resp = client.get("/api/agent/stream", params={"q": "hi", "dry_run": "1"})
    assert resp.status_code == 200

    events = _parse_sse(resp.text)
    kinds = [e[0] for e in events]
    assert kinds[-1] == "error"
    assert "overloaded" in events[-1][1]["message"].lower()
