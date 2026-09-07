"""
Starlette backend for the web UI (see docs/api_contract.md — the frozen
integration contract `app/web/` is built against).

FastAPI is deliberately NOT used here (not installed in app/.venv/); this is
a plain Starlette app using only starlette/uvicorn/jinja2/httpx/anyio, which
are already in the venv.

Run with: python -m app.api.server [--port 8000]
"""
import asyncio
import json
import os
from datetime import datetime

import anyio
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.api.data_access import (
    build_health,
    build_overview,
    friendly_agent_error,
    load_device_mapping,
)
from app.api.energy_access import (
    build_cusum,
    build_device_detail,
    build_house_summary,
    build_peaks,
    build_profiles,
)

_API_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_API_DIR)
_WEB_DIR = os.path.join(_APP_DIR, "web")
_INDEX_PATH = os.path.join(_WEB_DIR, "index.html")
_STATIC_DIR = os.path.join(_WEB_DIR, "static")

# Human phrase for each tool, shown next to its SSE events. Unknown tools
# (there shouldn't be any — this mirrors app/agent/tools.py's TOOLS registry)
# fall back to the raw tool name.
TOOL_LABELS = {
    "query_iot_data": "Querying the warehouse",
    "get_device_state": "Reading device state",
    "control_device": "Preparing a device command",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def index(request):
    if os.path.exists(_INDEX_PATH):
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    # The web/ build isn't in place yet — a plain placeholder beats a 500 or
    # a StaticFiles 404 while the frontend is being built in parallel.
    return HTMLResponse(
        "<html><body><h1>Home IoT Copilot API</h1>"
        "<p>app/web/index.html not found yet. API routes are live at "
        "/api/overview, /api/health and /api/agent/stream.</p></body></html>"
    )


async def overview(request):
    start, end = _range_params(request)
    payload = build_overview(
        days=_days_param(request),
        devices=_devices_param(request),
        start=start,
        end=end,
    )
    return JSONResponse(payload)


async def health(request):
    return JSONResponse(build_health())


# ---------------------------------------------------------------------------
# Query-parameter parsing shared by the energy routes.
# ---------------------------------------------------------------------------


def _days_param(request, default="7"):
    """`days=7` | `days=all`. Anything unparseable falls back to the default."""
    raw = request.query_params.get("days", default)
    if raw is None or str(raw).lower() == "all":
        return None
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return int(default)


def _devices_param(request):
    raw = request.query_params.get("devices")
    if not raw:
        return None
    names = [name.strip() for name in raw.split(",") if name.strip()]
    return names or None


def _range_params(request):
    """`start=YYYY-MM-DD&end=YYYY-MM-DD` for the absolute period presets.

    "Yesterday" and a custom range cannot be expressed as a trailing window, so
    the energy routes accept explicit bounds alongside `days`. A malformed date
    is ignored rather than rejected: the window simply falls back to `days`,
    which is a better outcome for a dashboard than an error card.
    """
    def _parse(name):
        raw = request.query_params.get(name)
        if not raw:
            return None
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    return _parse("start"), _parse("end")


def _float_param(request, name, default):
    try:
        return float(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default


async def house_summary(request):
    start, end = _range_params(request)
    return JSONResponse(
        build_house_summary(
            days=_days_param(request), devices=_devices_param(request), start=start, end=end
        )
    )


async def device_detail(request):
    device = request.path_params["device"]
    start, end = _range_params(request)
    payload = build_device_detail(device, days=_days_param(request), start=start, end=end)
    # An unknown device is a client error, but the payload still carries the
    # empty-state shape so the page can render an explanation rather than
    # dealing with a bare status code.
    status = 404 if payload.get("empty") and payload.get("known") else 200
    return JSONResponse(payload, status_code=status)


async def analysis_cusum(request):
    device = request.query_params.get("device")
    if not device:
        return JSONResponse({"error": "A `device` query parameter is required."}, status_code=400)

    k = _float_param(request, "k", 0.5)
    h = _float_param(request, "h", 5.0)
    if k < 0 or h <= 0:
        return JSONResponse(
            {"error": "k must be >= 0 and h must be > 0."}, status_code=400
        )

    start, end = _range_params(request)
    return JSONResponse(
        build_cusum(device, k=k, h=h, days=_days_param(request, "all"), start=start, end=end)
    )


async def analysis_profiles(request):
    start, end = _range_params(request)
    return JSONResponse(
        build_profiles(
            devices=_devices_param(request),
            days=_days_param(request, "all"),
            start=start,
            end=end,
        )
    )


async def analysis_peaks(request):
    try:
        limit = int(request.query_params.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    start, end = _range_params(request)
    return JSONResponse(
        build_peaks(
            devices=_devices_param(request),
            days=_days_param(request),
            limit=limit,
            start=start,
            end=end,
        )
    )


async def agent_stream(request):
    """SSE endpoint streaming one `run_agent` turn's progress.

    `run_agent` (app/agent/agent.py) is synchronous and blocking, so it is run
    in a worker thread via `anyio.to_thread.run_sync`; its `on_event`
    callback (invoked from that thread) pushes onto an `asyncio.Queue` via
    `loop.call_soon_threadsafe` so the async generator below can drain it and
    yield SSE frames as they happen, rather than buffering until the turn ends.
    """
    question = request.query_params.get("q", "")
    dry_run = request.query_params.get("dry_run", "1") not in ("0", "false", "False")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()  # sentinel: worker thread has finished (result or error)

    def on_event(event: dict) -> None:
        # Called from the worker thread — never touch the queue directly.
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def run_in_thread():
        # Imported lazily so importing this module never requires a
        # configured LLM provider.
        from app.agent.agent import run_agent

        try:
            result = run_agent(question, dry_run=dry_run, on_event=on_event)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "result", **result})
        except Exception as e:  # pylint: disable=broad-except
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "message": friendly_agent_error(e)}
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

    async def event_generator():
        worker = asyncio.create_task(anyio.to_thread.run_sync(run_in_thread))
        try:
            while True:
                event = await queue.get()
                if event is _DONE:
                    break

                kind = event["type"]
                if kind == "done":
                    # Superseded by `result` — never forwarded on its own.
                    continue
                if kind == "model_call":
                    yield _sse("model_call", {"iteration": event["iteration"]})
                elif kind == "tool_call_start":
                    yield _sse("tool_call_start", {
                        "tool": event["tool"],
                        "label": TOOL_LABELS.get(event["tool"], event["tool"]),
                        "input": event.get("input") or {},
                    })
                elif kind == "tool_call_end":
                    yield _sse("tool_call_end", {
                        "tool": event["tool"],
                        "duration_ms": event.get("duration_ms"),
                        "is_error": event.get("is_error", False),
                        "output": event.get("output"),
                    })
                elif kind == "result":
                    yield _sse("result", {
                        "reply": event.get("reply", ""),
                        "tool_trace": event.get("tool_trace", []),
                    })
                elif kind == "error":
                    yield _sse("error", {"message": event["message"]})
        finally:
            await worker

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disables response buffering on nginx-fronted deployments so SSE
            # frames actually reach the browser as they are yielded.
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Actuation: manual toggles and scenes.
#
# Both are guarded by the same rule the agent's `control_device` tool uses —
# dry-run is the default, and only an explicit `dry_run: false` from the caller
# can turn it off. The unattended Dagster scheduler has its own, separate gate
# (SCENE_EXECUTION_DRY_RUN); see app/scenes/executor.py.
# ---------------------------------------------------------------------------


def _dry_run_from(body: dict) -> bool:
    """Anything other than an explicit false leaves the safety gate closed."""
    return body.get("dry_run", True) is not False


async def _json_body(request) -> dict:
    try:
        body = await request.json()
    except Exception:  # pylint: disable=broad-except
        return {}
    return body if isinstance(body, dict) else {}


async def list_scenes(request):
    from app.scenes import load_scenes

    return JSONResponse({"scenes": load_scenes()})


async def create_scene_route(request):
    from app.scenes import SceneValidationError, create_scene

    body = await _json_body(request)
    try:
        scene = create_scene(body, known_devices=set(load_device_mapping().values()))
    except SceneValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(scene, status_code=201)


async def delete_scene_route(request):
    from app.scenes import delete_scene

    if not delete_scene(request.path_params["scene_id"]):
        return JSONResponse({"error": "No scene with that id."}, status_code=404)
    return JSONResponse({"deleted": True})


async def run_scene_route(request):
    from app.scenes import get_scene, mark_executed, run_scene

    scene = get_scene(request.path_params["scene_id"])
    if scene is None:
        return JSONResponse({"error": "No scene with that id."}, status_code=404)

    dry_run = _dry_run_from(await _json_body(request))
    outcome = run_scene(scene, dry_run=dry_run)
    if not dry_run:
        mark_executed(scene["id"])
    return JSONResponse(outcome)


async def toggle_device(request):
    """Turn one device on or off.

    Deliberately does not go through the agent: a toggle is a direct command
    and should not cost a model call, nor depend on an LLM provider being
    configured.
    """
    from app.agent.tools import resolve_switch_code
    from app.agent.tuya_control import (
        load_device_registry,
        resolve_device_id,
        send_device_command,
    )

    device_name = request.path_params["device"]
    body = await _json_body(request)
    action = str(body.get("action", "")).strip().lower()
    if action not in ("on", "off"):
        return JSONResponse(
            {"error": "`action` must be either 'on' or 'off'."}, status_code=400
        )

    registry = load_device_registry()
    device_id = resolve_device_id(device_name, registry)
    if device_id is None:
        return JSONResponse(
            {"error": f"Unknown device: {device_name!r}."}, status_code=404
        )

    dry_run = _dry_run_from(body)
    commands = [{"code": resolve_switch_code(device_id), "value": action == "on"}]
    outcome = send_device_command(device_id, commands, dry_run=dry_run)
    return JSONResponse(
        {
            "device": device_name,
            "action": action,
            "dry_run": dry_run,
            "ok": not outcome.get("error"),
            "payload": outcome.get("payload", {"commands": commands}),
            "error": outcome.get("error"),
        }
    )


routes = [
    Route("/", index),
    Route("/api/overview", overview),
    Route("/api/health", health),
    Route("/api/house/summary", house_summary),
    Route("/api/device/{device}/summary", device_detail),
    Route("/api/analysis/cusum", analysis_cusum),
    Route("/api/analysis/profiles", analysis_profiles),
    Route("/api/analysis/peaks", analysis_peaks),
    Route("/api/scenes", list_scenes),
    Route("/api/scenes", create_scene_route, methods=["POST"]),
    Route("/api/scenes/{scene_id}", delete_scene_route, methods=["DELETE"]),
    Route("/api/scenes/{scene_id}/run", run_scene_route, methods=["POST"]),
    Route("/api/devices/{device}/toggle", toggle_device, methods=["POST"]),
    Route("/api/agent/stream", agent_stream),
]

# Static assets are only mounted if app/web/static/ exists — StaticFiles
# raises at construction time on a missing directory, and the web/ build may
# not be in place yet while this backend is developed in parallel.
if os.path.isdir(_STATIC_DIR):
    routes.append(Mount("/static", app=StaticFiles(directory=_STATIC_DIR), name="static"))

app = Starlette(routes=routes)


def main():
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Home IoT Copilot API server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
