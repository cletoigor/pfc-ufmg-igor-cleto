"""
Home-automation copilot orchestrator.

Wires the three tools in app/agent/tools.py into the Anthropic beta Tool
Runner (`client.beta.messages.tool_runner`, confirmed against the installed
`anthropic==1.2.0` SDK: decorate tool functions with `@beta_tool`, pass them
in `tools=[...]`, then iterate the runner — each iteration yields a
BetaMessage, and `runner.generate_tool_call_response()` returns the executed
tool_result message for that turn — until Claude stops calling tools).

Importing this module does NOT require ANTHROPIC_API_KEY: the Anthropic
client is constructed lazily inside `run_agent`, not at import time.
"""
from app.agent.tools import control_device, get_device_state, query_iot_data
from app.agent.tuya_control import load_device_registry

MODEL = "claude-opus-5"
MAX_TOKENS = 4096


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


def run_agent(user_message: str, *, dry_run: bool = True, history: list | None = None) -> dict:
    """Runs one turn of the home-automation copilot to completion.

    Args:
        user_message: The user's natural-language request.
        dry_run: Threaded through to `control_device` — when True (the
            default), any actuation the agent decides to perform is
            simulated (no real Tuya API call).
        history: Optional prior conversation as a list of Anthropic message
            dicts (`{"role": ..., "content": ...}`), to continue a
            multi-turn conversation. A copy is used and extended; the
            caller's list is not mutated.

    Returns:
        {"reply": <final assistant text>, "tool_trace": [{"tool": name, "input": ..., "output": ...}, ...]}
    """
    # Imported lazily so a missing/unset ANTHROPIC_API_KEY never breaks import.
    import anthropic

    client = anthropic.Anthropic()

    messages = list(history) if history else []
    messages.append({"role": "user", "content": user_message})

    from anthropic import beta_tool

    control_device_func = control_device.func

    @beta_tool
    def _control_device(device_name: str, action: str) -> str:
        """Actuate a named device (turn it on/off/toggle).

        Args:
            device_name: The device's friendly name (e.g. "Fita de LED"),
                matched case-insensitively against the device registry.
            action: One of "on", "off", or "toggle".
        """
        return control_device_func(device_name=device_name, action=action, dry_run=dry_run)

    tools = [
        query_iot_data,
        get_device_state,
        _control_device,
    ]

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=_build_system_prompt(),
        tools=tools,
        messages=messages,
    )

    tool_trace = []
    final_message = None

    for message in runner:
        final_message = message

        pending_tool_uses = {
            block.id: block for block in message.content if block.type == "tool_use"
        }

        tool_response = runner.generate_tool_call_response()
        if tool_response is not None and pending_tool_uses:
            result_blocks = tool_response.get("content", []) if isinstance(tool_response, dict) else []
            for result_block in result_blocks:
                tool_use_id = (
                    result_block.get("tool_use_id")
                    if isinstance(result_block, dict)
                    else getattr(result_block, "tool_use_id", None)
                )
                block = pending_tool_uses.get(tool_use_id)
                if block is None:
                    continue
                output = (
                    result_block.get("content")
                    if isinstance(result_block, dict)
                    else getattr(result_block, "content", None)
                )
                tool_trace.append(
                    {"tool": block.name, "input": block.input, "output": output}
                )

    reply_text = ""
    if final_message is not None:
        text_blocks = [b.text for b in final_message.content if b.type == "text"]
        reply_text = "\n".join(text_blocks)

    return {"reply": reply_text, "tool_trace": tool_trace}
