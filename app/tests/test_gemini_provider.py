"""
Unit tests for the Gemini provider (app/agent/llm_provider.py::GeminiProvider).

These tests NEVER hit the real Gemini API: the `google.genai` client is
monkeypatched with a fake whose `models.generate_content` returns canned
`google.genai.types` response objects — first a function call, then a final
text reply. This exercises:
  - `is_available()` requires a key AND a working `google-genai` import, and
    never raises even with no key/package.
  - `chat()` normalizes a function_call Part (read off
    `response.candidates[0].content.parts`, not the `.function_calls`
    convenience property) into the neutral `{"name", "arguments"}` tool_calls
    shape the agent loop expects.
  - Gemini 3.x attaches a `thought_signature` to each function_call Part,
    which MUST be replayed back verbatim on the next turn's request or the
    API 400s ("Function call is missing a thought_signature"). `chat()`
    captures it onto the normalized tool_call dict, and the neutral-message
    -> `contents` builder sets it back onto the rebuilt Part — this is
    asserted directly (a regression here previously broke live Gemini 3.x
    calls without any of the mocked tests catching it).
  - a full `run_agent()` loop through `GeminiProvider` populates `tool_trace`
    and preserves the dry_run safety gate, exactly like the other providers.
"""
import json

import pytest

from google.genai import types

from app.agent import agent as agent_module
from app.agent.llm_provider import GeminiProvider, get_provider


class FakeModels:
    """Stands in for `client.models`, returning canned responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


def _function_call_part(name, args, thought_signature=None):
    """Builds a real `types.Part` carrying a function_call, optionally with
    the `thought_signature` bytes Gemini 3.x attaches to it."""
    part = types.Part.from_function_call(name=name, args=args)
    if thought_signature is not None:
        part.thought_signature = thought_signature
    return part


def _fake_response(parts=None, text=None):
    """Builds a minimal object mimicking `types.GenerateContentResponse`'s
    public surface used by the provider: `.candidates[0].content.parts` and
    `.text`. `chat()` reads tool calls off `.candidates`, not the
    `.function_calls` convenience property, specifically so it can also read
    each Part's `thought_signature`.
    """

    class _Resp:
        pass

    resp = _Resp()
    resp.candidates = [types.Candidate(content=types.Content(role="model", parts=parts or []))]
    resp.text = text
    return resp


def test_is_available_false_with_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    provider = GeminiProvider()
    assert provider.is_available() is False


def test_is_available_true_with_key_and_working_import(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    provider = GeminiProvider()
    assert provider.is_available() is True


def test_is_available_never_raises_on_broken_import(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    provider = GeminiProvider()

    import builtins

    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "google.genai":
            raise RuntimeError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    assert provider.is_available() is False


def test_get_provider_defaults_to_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_provider(), GeminiProvider)


def test_chat_normalizes_function_call_then_final_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    provider = GeminiProvider()

    sig = b"thought-sig-123"
    responses = [
        _fake_response(
            parts=[
                _function_call_part(
                    "get_device_state",
                    {"device_name": "LED Strip"},
                    thought_signature=sig,
                )
            ],
            text=None,
        ),
        _fake_response(parts=[], text="Done!"),
    ]
    provider._client = FakeClient(responses)

    messages = [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "what's the led strip doing?"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_device_state",
                "description": "d",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    r1 = provider.chat(messages, tools)
    assert r1.tool_calls == [
        {
            "name": "get_device_state",
            "arguments": {"device_name": "LED Strip"},
            "thought_signature": sig,
        }
    ]
    assert r1.assistant_message["role"] == "assistant"

    messages.append(r1.assistant_message)
    messages.extend(
        provider.format_tool_results(
            [{"name": "get_device_state", "arguments": {}, "output": "{}"}]
        )
    )

    r2 = provider.chat(messages, tools)
    assert r2.tool_calls == []
    assert r2.reply_text == "Done!"

    # The second request must replay the thought_signature verbatim on the
    # rebuilt function_call Part, or Gemini 3.x 400s.
    second_contents = provider._client.models.calls[1]["contents"]
    replayed_sigs = [
        part.thought_signature
        for content in second_contents
        for part in content.parts
        if part.function_call is not None
    ]
    assert sig in replayed_sigs


def test_run_agent_through_gemini_populates_tool_trace_and_enforces_dry_run(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    provider = GeminiProvider()

    responses = [
        _fake_response(
            parts=[
                _function_call_part(
                    "control_device",
                    {"device_name": "LED Strip", "action": "on", "dry_run": False},
                    thought_signature=b"sig-xyz",
                )
            ],
            text=None,
        ),
        _fake_response(parts=[], text="Done, turned it on (simulated)."),
    ]
    provider._client = FakeClient(responses)

    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)

    result = agent_module.run_agent("turn on the led strip", dry_run=True)

    assert result["reply"] == "Done, turned it on (simulated)."
    assert len(result["tool_trace"]) == 1

    trace_entry = result["tool_trace"][0]
    assert trace_entry["tool"] == "control_device"

    output = json.loads(trace_entry["output"])
    # The fake model asked for dry_run=False; the caller passed dry_run=True —
    # the loop must force True regardless (provider-agnostic safety gate).
    assert output["dry_run"] is True
