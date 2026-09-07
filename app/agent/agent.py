"""
Home-automation copilot orchestrator.

Drives a bounded, manual tool-calling loop against a provider-neutral LLM
backend (see app/agent/llm_provider.py — Ollama by default, Anthropic
optionally): send `messages` + the tool schemas in app/agent/tools.py to
`provider.chat(...)`; if the model requests tool calls, dispatch them
against the `TOOLS` registry, append the results back into `messages` in the
provider's native format, and re-call — until the model stops calling tools
or `MAX_ITERATIONS` is hit.

Importing this module does NOT require a running Ollama server, an
installed `anthropic` package, or any API key: the provider is constructed
lazily inside `run_agent`, not at import time.
"""
import time
from typing import Callable

from app.agent.llm_provider import get_provider
from app.agent.tools import TOOLS, openai_tool_specs
from app.agent.tuya_control import load_device_registry

MAX_ITERATIONS = 6


def _build_system_prompt() -> str:
    registry = load_device_registry()
    device_list = "\n".join(f"  - {name} (id: {device_id})" for device_id, name in registry.items())

    return f"""You are a home-automation copilot for a small IoT setup built on the Tuya \
Cloud platform. You know about exactly these {len(registry)} devices:

{device_list}

You have access to a DuckDB-backed metrics warehouse. All timestamps in it are \
already in the devices' LOCAL time, so you can compare hours of the day \
directly and never need a timezone conversion.

Event-count rollups (how often a device reported anything):
  - device_metrics_hourly(device_id, device_name, event_hour, event_count, last_seen_at, on_event_count)
  - device_metrics_daily(device_id, device_name, event_day, event_count, last_seen_at, on_event_count)

Duration tables (how long a device was actually on) — prefer these for any \
question about time spent on, usage, or "how long":
  - device_state_intervals(device_id, device_name, interval_start, interval_end, duration_minutes, is_on)
      One row per contiguous stretch in a single state. Filter `WHERE is_on` \
for the periods a device was running.
  - device_on_time_daily(device_id, device_name, event_day, on_minutes, on_sessions, longest_session_minutes, overnight_on_minutes)
      Per device per day. `on_minutes` is total time on that day (an overnight \
session is split across the two days it touches); `on_sessions` counts the \
sessions that started that day; `longest_session_minutes` is the longest single \
stretch; `overnight_on_minutes` is time on between 00:00 and 06:00.

Energy tables (how much a device actually consumed) — prefer these for any \
question about energy, consumption, kWh, watts, cost, or electrical readings:
  - device_power_hourly(device_id, device_name, event_hour, energy_kwh, power_w_mean, power_w_max, power_w_min, voltage_v_mean, voltage_v_max, voltage_v_min, current_ma_mean, current_ma_max, current_ma_min, sample_count)
  - device_power_daily(...) — the same rolled up per `event_day`, plus `peak_hour`.
  - device_cusum_baseline(device_id, device_name, hour_of_day, mu0, sigma0, n_obs)
      The Phase I statistical baseline: the mean and sample standard deviation \
of hourly energy for each hour of the day, which the CUSUM control charts \
monitor new readings against.

Do not answer an energy question with on-time. "Which device used the most \
energy" is `sum(energy_kwh)` from device_power_daily, not `sum(on_minutes)`: a \
low-power device left on all night uses less than a heater running for an hour.

`event_count` is the number of raw events recorded in that bucket; \
`on_event_count` is a proxy for how many of those events turned the device on \
(a count of switch-like state changes reporting true); `last_seen_at` is the \
timestamp of the most recent event in that bucket.

Note that some devices are *supposed* to run overnight (a mosquito repellent, a \
fan), so a high `overnight_on_minutes` is only interesting when it is unusual \
for that particular device — compare a day against that device's own typical \
value rather than flagging every device that was on at night.

For any question about historical usage, trends, counts, durations, or "when \
was X last seen", write a DuckDB SQL query and call the `query_iot_data` tool — \
prefer aggregating in SQL over pulling raw rows. For "what's the current/last state \
of device X" questions, prefer `get_device_state`. For instructions to \
actuate a device ("turn on the fan", "desligue a fita de led"), map the \
device's friendly name and the requested action ("on"/"off"/"toggle") and \
call `control_device`. Only ever refer to devices from the list above — if \
the user names something not on the list, say so instead of guessing an ID.

Be concise. When you report the result of a SQL query or a device command, \
summarize it in plain language for the user rather than dumping raw JSON.

IMPORTANT — never overstate what a device command did. `control_device` \
returns a result containing a `dry_run` flag. When `dry_run` is true the \
command was NOT sent and the device did NOT change: say so explicitly (e.g. \
"Dry run is on, so I prepared the command but didn't send it — the LED Strip \
is unchanged"), and never phrase it as though the device was actually \
switched. If the result contains an `error` field, report that the command \
failed and why. Only state that a device was actually turned on or off when \
`dry_run` is false and `success` is true."""


def _dispatch_tool_call(name: str, arguments: dict, *, dry_run: bool) -> str:
    """Runs one tool call against the `TOOLS` registry.

    `dry_run` is threaded into `control_device` unconditionally — the
    caller's `dry_run` (the safety gate) always wins over anything the model
    puts in `arguments["dry_run"]`, so the model can never turn dry_run off
    on its own.
    """
    tool = TOOLS.get(name)
    if tool is None:
        return f"Error: unknown tool '{name}'."

    arguments = dict(arguments or {})
    if name == "control_device":
        arguments["dry_run"] = dry_run

    try:
        return tool["callable"](**arguments)
    except TypeError as e:
        return f"Error: invalid arguments for tool '{name}': {e}"


def run_agent(
    user_message: str,
    *,
    dry_run: bool = True,
    history: list | None = None,
    on_event: Callable[[dict], None] | None = None,
) -> dict:
    """Runs one turn of the home-automation copilot to completion.

    Args:
        user_message: The user's natural-language request.
        dry_run: Threaded through to `control_device` — when True (the
            default), any actuation the agent decides to perform is
            simulated (no real Tuya API call). This is enforced by
            `_dispatch_tool_call`, which overwrites whatever `dry_run` value
            (if any) the model supplies in its tool-call arguments — the
            model can never disable the safety gate itself.
        history: Optional prior conversation as a list of message dicts
            (provider-native shape), to continue a multi-turn conversation.
            A copy is used and extended; the caller's list is not mutated.
        on_event: Optional progress callback, invoked as the turn unfolds so a
            UI can show what the agent is doing instead of a single opaque
            spinner across up to MAX_ITERATIONS round-trips. Receives dicts:
              {"type": "model_call", "iteration": int}
              {"type": "tool_call_start", "tool": str, "input": dict}
              {"type": "tool_call_end", "tool": str, "output": str,
               "duration_ms": int, "is_error": bool}
              {"type": "done", "reply": str}
            A raising callback must not break the run, so exceptions from it are
            swallowed — progress reporting is never worth failing a turn over.

    Returns:
        {"reply": <final assistant text>,
         "tool_trace": [{"tool", "input", "output", "duration_ms", "is_error"}, ...]}
    """
    def emit(event: dict) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:  # pylint: disable=broad-except
            pass

    # Constructed lazily so a missing/unset API key or unreachable Ollama
    # never breaks import — only calling run_agent() touches the network.
    provider = get_provider()

    messages = list(history) if history else []
    messages.insert(0, {"role": "system", "content": _build_system_prompt()})
    messages.append({"role": "user", "content": user_message})

    tools = openai_tool_specs()

    tool_trace = []
    reply_text = ""

    for iteration in range(MAX_ITERATIONS):
        emit({"type": "model_call", "iteration": iteration + 1})
        response = provider.chat(messages, tools)
        messages.append(response.assistant_message)
        reply_text = response.reply_text

        if not response.tool_calls:
            break

        results = []
        for call in response.tool_calls:
            name = call["name"]
            arguments = call.get("arguments", {})
            emit({"type": "tool_call_start", "tool": name, "input": arguments})

            started = time.monotonic()
            output = _dispatch_tool_call(name, arguments, dry_run=dry_run)
            duration_ms = int((time.monotonic() - started) * 1000)

            # `_dispatch_tool_call` reports failures as a string rather than
            # raising (the model needs to see them as tool results), so the
            # prefix is the only signal a UI has to style them differently.
            is_error = isinstance(output, str) and output.startswith("Error:")

            emit({
                "type": "tool_call_end",
                "tool": name,
                "output": output,
                "duration_ms": duration_ms,
                "is_error": is_error,
            })

            entry = dict(call)
            entry["output"] = output
            results.append(entry)
            tool_trace.append({
                "tool": name,
                "input": arguments,
                "output": output,
                "duration_ms": duration_ms,
                "is_error": is_error,
            })

        messages.extend(provider.format_tool_results(results))
    else:
        # Hit MAX_ITERATIONS without the model settling on a final answer.
        if not reply_text:
            reply_text = (
                "I wasn't able to finish within the allotted number of tool "
                "calls. Please try rephrasing your request."
            )

    emit({"type": "done", "reply": reply_text})
    return {"reply": reply_text, "tool_trace": tool_trace}
