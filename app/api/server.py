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

import anyio
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.api.data_access import build_health, build_overview, friendly_agent_error

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
    days_param = request.query_params.get("days", "7")
    days = None if days_param.lower() == "all" else int(days_param)

    devices_param = request.query_params.get("devices")
    devices = [d.strip() for d in devices_param.split(",") if d.strip()] if devices_param else None

    payload = build_overview(days=days, devices=devices)
    return JSONResponse(payload)


async def health(request):
    return JSONResponse(build_health())


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


routes = [
    Route("/", index),
    Route("/api/overview", overview),
    Route("/api/health", health),
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
