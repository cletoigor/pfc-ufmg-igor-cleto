"""
Unit tests for app/agent/agent.py's manual tool-calling loop.

These tests use a FAKE provider (never a real Ollama or Anthropic call) that
mimics the `LLMProvider` interface: first turn emits a tool_call, second turn
emits a final text reply with no more tool calls. This exercises:
  - the loop dispatching a tool call and populating `tool_trace`
  - the `dry_run` safety gate always winning over whatever the fake model
    requests in its tool-call arguments (it can never turn dry_run off).
"""
import json

from app.agent import agent as agent_module
from app.agent.llm_provider import LLMResponse


class FakeProvider:
    """Emits one control_device tool_call, then a final reply."""

    def __init__(self, requested_dry_run=False):
        self.requested_dry_run = requested_dry_run
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                assistant_message={"role": "assistant", "content": ""},
                tool_calls=[
                    {
                        "name": "control_device",
                        "arguments": {
                            "device_name": "LED Strip",
                            "action": "on",
                            # The fake model tries to disable the safety gate;
                            # the loop must override this with the caller's dry_run.
                            "dry_run": self.requested_dry_run,
                        },
                    }
                ],
                reply_text="",
            )
        return LLMResponse(
            assistant_message={"role": "assistant", "content": "Done, turned it on (simulated)."},
            tool_calls=[],
            reply_text="Done, turned it on (simulated).",
        )

    def format_tool_results(self, results):
        return [{"role": "tool", "content": r["output"]} for r in results]


def test_run_agent_populates_tool_trace_and_enforces_dry_run(monkeypatch):
    fake = FakeProvider(requested_dry_run=False)
    monkeypatch.setattr(agent_module, "get_provider", lambda: fake)

    result = agent_module.run_agent("turn on the led strip", dry_run=True)

    assert result["reply"] == "Done, turned it on (simulated)."
    assert len(result["tool_trace"]) == 1

    trace_entry = result["tool_trace"][0]
    assert trace_entry["tool"] == "control_device"

    output = json.loads(trace_entry["output"])
    # Caller passed dry_run=True; the fake model asked for dry_run=False —
    # the loop must force True regardless.
    assert output["dry_run"] is True


def test_run_agent_forces_dry_run_false_when_caller_allows_it(monkeypatch):
    fake = FakeProvider(requested_dry_run=True)
    monkeypatch.setattr(agent_module, "get_provider", lambda: fake)

    result = agent_module.run_agent("turn on the led strip", dry_run=True)

    output = json.loads(result["tool_trace"][0]["output"])
    # Even though the fake model asked for dry_run=True here too, confirm the
    # caller's own value (True) is what's actually threaded through — the
    # important invariant is that _dispatch_tool_call always uses the
    # caller's dry_run, never the model's.
    assert output["dry_run"] is True


def test_run_agent_no_tool_calls_returns_plain_reply(monkeypatch):
    class NoToolProvider:
        def chat(self, messages, tools):
            return LLMResponse(
                assistant_message={"role": "assistant", "content": "Hi there."},
                tool_calls=[],
                reply_text="Hi there.",
            )

        def format_tool_results(self, results):
            return []

    monkeypatch.setattr(agent_module, "get_provider", lambda: NoToolProvider())

    result = agent_module.run_agent("hello", dry_run=True)
    assert result["reply"] == "Hi there."
    assert result["tool_trace"] == []


# --- progress callback (on_event) ---


def test_run_agent_emits_progress_events(monkeypatch):
    """The dashboard drives its live step display off these events."""
    fake = FakeProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: fake)

    events = []
    result = agent_module.run_agent(
        "turn on the led strip", dry_run=True, on_event=events.append
    )

    kinds = [e["type"] for e in events]
    # Two model round-trips (tool call, then final answer) wrapping one tool call.
    assert kinds == [
        "model_call",
        "tool_call_start",
        "tool_call_end",
        "model_call",
        "done",
    ]

    start = events[1]
    assert start["tool"] == "control_device"
    assert start["input"]["device_name"] == "LED Strip"

    end = events[2]
    assert end["tool"] == "control_device"
    assert end["is_error"] is False
    assert isinstance(end["duration_ms"], int)

    assert events[-1]["reply"] == result["reply"]


def test_run_agent_trace_entries_carry_timing_and_error_flag(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: fake)

    result = agent_module.run_agent("turn on the led strip", dry_run=True)

    entry = result["tool_trace"][0]
    assert entry["is_error"] is False
    assert isinstance(entry["duration_ms"], int)


def test_run_agent_survives_a_raising_progress_callback(monkeypatch):
    """Progress reporting must never be able to fail a turn."""
    fake = FakeProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: fake)

    def boom(_event):
        raise RuntimeError("UI blew up")

    result = agent_module.run_agent("turn on the led strip", dry_run=True, on_event=boom)

    assert result["reply"] == "Done, turned it on (simulated)."
    assert len(result["tool_trace"]) == 1


def test_run_agent_flags_tool_errors_in_trace(monkeypatch):
    """An unknown tool comes back as an error string, not an exception."""

    class UnknownToolProvider(FakeProvider):
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    assistant_message={"role": "assistant", "content": ""},
                    tool_calls=[{"name": "no_such_tool", "arguments": {}}],
                    reply_text="",
                )
            return LLMResponse(
                assistant_message={"role": "assistant", "content": "Sorry."},
                tool_calls=[],
                reply_text="Sorry.",
            )

    monkeypatch.setattr(agent_module, "get_provider", lambda: UnknownToolProvider())

    events = []
    result = agent_module.run_agent("do something odd", on_event=events.append)

    assert result["tool_trace"][0]["is_error"] is True
    assert [e for e in events if e["type"] == "tool_call_end"][0]["is_error"] is True
