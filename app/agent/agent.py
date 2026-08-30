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

You have access to a DuckDB-backed metrics warehouse with two tables:
  - device_metrics_hourly(device_id, device_name, event_hour, event_count, last_seen_at, on_event_count)
  - device_metrics_daily(device_id, device_name, event_day, event_count, last_seen_at, on_event_count)

`event_count` is the number of raw events recorded in that bucket; \
`on_event_count` is a proxy for how many of those events turned the device on \
(a count of switch-like state changes reporting true); `last_seen_at` is the \
timestamp of the most recent event in that bucket.

For any question about historical usage, trends, counts, or "when was X last \
seen", write a DuckDB SQL query and call the `query_iot_data` tool — prefer \
aggregating in SQL over pulling raw rows. For "what's the current/last state \
of device X" questions, prefer `get_device_state`. For instructions to \
actuate a device ("turn on the fan", "desligue a fita de led"), map the \
device's friendly name and the requested action ("on"/"off"/"toggle") and \
call `control_device`. Only ever refer to devices from the list above — if \
the user names something not on the list, say so instead of guessing an ID.

Be concise. When you report the result of a SQL query or a device command, \
summarize it in plain language for the user rather than dumping raw JSON."""


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


def run_agent(user_message: str, *, dry_run: bool = True, history: list | None = None) -> dict:
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

    Returns:
        {"reply": <final assistant text>, "tool_trace": [{"tool": name, "input": ..., "output": ...}, ...]}
    """
    # Constructed lazily so a missing/unset API key or unreachable Ollama
    # never breaks import — only calling run_agent() touches the network.
    provider = get_provider()

    messages = list(history) if history else []
    messages.insert(0, {"role": "system", "content": _build_system_prompt()})
    messages.append({"role": "user", "content": user_message})

    tools = openai_tool_specs()

    tool_trace = []
    reply_text = ""

    for _ in range(MAX_ITERATIONS):
        response = provider.chat(messages, tools)
        messages.append(response.assistant_message)
        reply_text = response.reply_text

        if not response.tool_calls:
            break

        results = []
        for call in response.tool_calls:
            output = _dispatch_tool_call(call["name"], call.get("arguments", {}), dry_run=dry_run)
            entry = dict(call)
            entry["output"] = output
            results.append(entry)
            tool_trace.append({"tool": call["name"], "input": call.get("arguments", {}), "output": output})

        messages.extend(provider.format_tool_results(results))
    else:
        # Hit MAX_ITERATIONS without the model settling on a final answer.
        if not reply_text:
            reply_text = (
                "I wasn't able to finish within the allotted number of tool "
                "calls. Please try rephrasing your request."
            )

    return {"reply": reply_text, "tool_trace": tool_trace}
