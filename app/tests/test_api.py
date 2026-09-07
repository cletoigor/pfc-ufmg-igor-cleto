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
        conn.execute("CREATE SCHEMA gold")
        end = pd.Timestamp("2026-09-06 22:51:24")
        conn.execute(
            """
            CREATE TABLE gold.device_state_intervals AS SELECT * FROM (VALUES
                ('d1', 'Lamp', 'switch_1', TIMESTAMP '2026-09-06 17:00:00', ?, 231.4, true),
                ('d2', 'Fan',  'switch_1', TIMESTAMP '2026-09-06 18:00:00', ?, 171.4, true)
            ) t(device_id, device_name, switch_code, interval_start, interval_end,
                duration_minutes, is_on)
            """,
            [end, end],
        )
        conn.execute(
            """
            CREATE TABLE gold.device_metrics_daily AS SELECT * FROM (VALUES
                ('d1', 'Lamp', DATE '2026-09-06', 10, TIMESTAMP '2026-09-06 17:10:00', 2),
                ('d2', 'Fan',  DATE '2026-09-06', 15, TIMESTAMP '2026-09-06 22:51:24', 3)
            ) t(device_id, device_name, event_day, event_count, last_seen_at, on_event_count)
            """
        )
        conn.execute(
            """
            CREATE TABLE gold.device_on_time_daily AS SELECT * FROM (VALUES
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


# --- energy + analysis routes ---
#
# The autouse fixture above points every data path at an empty tmp dir, so
# these assert the contract that matters most for a fresh clone: a page with no
# warehouse behind it still gets a 200 and an empty-state payload to render,
# never a 500.


@pytest.mark.parametrize(
    "url",
    [
        "/api/house/summary",
        "/api/house/summary?days=30&devices=Lamp",
        "/api/device/Lamp/summary",
        "/api/analysis/cusum?device=Lamp",
        "/api/analysis/profiles",
        "/api/analysis/peaks",
    ],
)
def test_energy_routes_return_200_and_an_empty_shape_with_no_data(client, url):
    resp = client.get(url)

    assert resp.status_code == 200
    body = resp.json()
    assert body["empty"] is True
    assert body["empty_reason"]
    assert body["source"] is None


def test_device_summary_404s_for_a_device_that_is_not_in_the_mapping(client):
    resp = client.get("/api/device/Toaster/summary")

    assert resp.status_code == 404
    assert "Unknown device" in resp.json()["empty_reason"]


def test_cusum_requires_a_device(client):
    resp = client.get("/api/analysis/cusum")

    assert resp.status_code == 400
    assert "device" in resp.json()["error"]


@pytest.mark.parametrize("query", ["k=-1", "h=0", "h=-2"])
def test_cusum_rejects_out_of_range_parameters(client, query):
    resp = client.get(f"/api/analysis/cusum?device=Lamp&{query}")

    assert resp.status_code == 400


def test_cusum_echoes_the_parameters_it_ran_with(client, monkeypatch):
    captured = {}

    def _fake_build(device, k, h, days, start=None, end=None):
        captured.update({"device": device, "k": k, "h": h, "days": days, "start": start, "end": end})
        return {"empty": False, "device": device, "k": k, "h": h}

    monkeypatch.setattr(server, "build_cusum", _fake_build)

    body = client.get("/api/analysis/cusum?device=Lamp&k=0.25&h=3.5&days=14").json()

    assert captured == {"device": "Lamp", "k": 0.25, "h": 3.5, "days": 14, "start": None, "end": None}
    assert body["k"] == 0.25 and body["h"] == 3.5


def test_unparseable_days_falls_back_to_the_default_rather_than_erroring(client):
    assert client.get("/api/house/summary?days=banana").status_code == 200
    assert client.get("/api/house/summary?days=all").status_code == 200


def test_an_absolute_range_overrides_the_trailing_window(client, monkeypatch):
    """"Yesterday" and a custom range cannot be expressed as a trailing window."""
    captured = {}

    def _fake(days=7, devices=None, start=None, end=None):
        captured.update({"days": days, "start": start, "end": end})
        return {"empty": True, "empty_reason": "x", "source": None}

    monkeypatch.setattr(server, "build_house_summary", _fake)
    client.get("/api/house/summary?days=7&start=2026-09-06&end=2026-09-06")

    assert str(captured["start"]) == "2026-09-06"
    assert str(captured["end"]) == "2026-09-06"


def test_a_malformed_date_is_ignored_rather_than_erroring(client, monkeypatch):
    captured = {}

    def _fake(days=7, devices=None, start=None, end=None):
        captured.update({"days": days, "start": start, "end": end})
        return {"empty": True, "empty_reason": "x", "source": None}

    monkeypatch.setattr(server, "build_house_summary", _fake)
    resp = client.get("/api/house/summary?start=not-a-date")

    assert resp.status_code == 200
    assert captured == {"days": 7, "start": None, "end": None}


# --- actuation: toggles and scenes ---


@pytest.fixture
def scenes_path(tmp_path, monkeypatch):
    from app.scenes import store

    path = str(tmp_path / "scheduled_scenes.json")
    monkeypatch.setattr(store, "SCENES_PATH", path)
    return path


@pytest.fixture(autouse=True)
def never_touch_tuya(monkeypatch):
    """Belt and braces: no test in this file may reach the Tuya API."""
    from app.agent import tuya_control

    def _refuse(device_id, commands, *, dry_run=True):
        assert dry_run is True, "a test tried to send a live Tuya command"
        return {"dry_run": True, "device_id": device_id, "payload": {"commands": commands}}

    monkeypatch.setattr(tuya_control, "send_device_command", _refuse)
    # tuya_control reads the registry from its own module-level path, which the
    # data_access isolation above does not cover, so point it at the same fake
    # two-device mapping the rest of this file uses.
    monkeypatch.setattr(tuya_control, "load_device_registry", lambda *a, **k: {"d1": "Lamp", "d2": "Fan"})


def test_scenes_start_empty(client, scenes_path):
    assert client.get("/api/scenes").json() == {"scenes": []}


def test_creating_a_scene_returns_201_and_lists_it(client, scenes_path):
    resp = client.post(
        "/api/scenes",
        json={
            "name": "Evening wind-down",
            "actions": {"Lamp": "off"},
            "schedule": {"time": "22:30", "days_of_week": [0, 1, 2], "recurring": True},
        },
    )

    assert resp.status_code == 201
    scene = resp.json()
    assert scene["id"] and scene["name"] == "Evening wind-down"

    listed = client.get("/api/scenes").json()["scenes"]
    assert [s["name"] for s in listed] == ["Evening wind-down"]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "actions": {"Lamp": "off"}},
        {"name": "X", "actions": {}},
        {"name": "X", "actions": {"Toaster": "off"}},           # not in the mapping
        {"name": "X", "actions": {"Lamp": "explode"}},
        {"name": "X", "actions": {"Lamp": "off"}, "schedule": {"time": "25:00", "days_of_week": [0]}},
    ],
)
def test_invalid_scenes_are_rejected_with_400(client, scenes_path, body):
    resp = client.post("/api/scenes", json=body)

    assert resp.status_code == 400
    assert resp.json()["error"]


def test_deleting_a_scene(client, scenes_path):
    scene_id = client.post(
        "/api/scenes", json={"name": "X", "actions": {"Lamp": "off"}}
    ).json()["id"]

    assert client.delete(f"/api/scenes/{scene_id}").status_code == 200
    assert client.delete(f"/api/scenes/{scene_id}").status_code == 404
    assert client.get("/api/scenes").json()["scenes"] == []


def test_running_an_unknown_scene_is_a_404(client, scenes_path):
    assert client.post("/api/scenes/nope/run", json={}).status_code == 404


def test_running_a_scene_is_dry_run_unless_the_caller_arms_it(client, scenes_path):
    """The safety gate: only an explicit `dry_run: false` sends anything."""
    scene_id = client.post(
        "/api/scenes", json={"name": "X", "actions": {"Lamp": "off"}}
    ).json()["id"]

    assert client.post(f"/api/scenes/{scene_id}/run", json={}).json()["dry_run"] is True
    assert (
        client.post(f"/api/scenes/{scene_id}/run", json={"dry_run": True}).json()["dry_run"]
        is True
    )
    # Anything that is not literally false leaves the gate closed.
    for value in ("false", 0, None, "no"):
        assert (
            client.post(f"/api/scenes/{scene_id}/run", json={"dry_run": value}).json()["dry_run"]
            is True
        ), f"{value!r} must not arm the command"


def test_toggling_a_device_is_dry_run_by_default(client):
    body = client.post("/api/devices/Lamp/toggle", json={"action": "off"}).json()

    assert body["dry_run"] is True
    assert body["action"] == "off"
    assert body["payload"]["commands"][0]["value"] is False


def test_toggle_rejects_an_unknown_action(client):
    assert client.post("/api/devices/Lamp/toggle", json={"action": "spin"}).status_code == 400


def test_toggle_404s_for_an_unknown_device(client):
    assert client.post("/api/devices/Toaster/toggle", json={"action": "on"}).status_code == 404
