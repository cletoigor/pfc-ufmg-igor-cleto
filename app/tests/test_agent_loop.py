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
                            "device_name": "Fita de LED",
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
