"""
LLM provider abstraction for the home-automation copilot.

Three providers are available, selected via `get_provider()`:
    - GeminiProvider (default) — Google's Gemini API, free tier via an AI
      Studio key (`GEMINI_API_KEY`/`GOOGLE_API_KEY`). Model from
      `GEMINI_MODEL` env (default "gemini-3.6-flash").
    - OllamaProvider — a local, keyless open-weight model served by Ollama
      (https://ollama.com). Model from `OLLAMA_MODEL` env (default
      "qwen3:8b"), optional `OLLAMA_HOST`. Select with `LLM_PROVIDER=ollama`.
    - AnthropicProvider (optional) — a thin wrapper so the agent can still be
      pointed at the Anthropic API by setting `LLM_PROVIDER=anthropic` (and
      ANTHROPIC_API_KEY).

Importing this module must NEVER require a running Ollama server, an
installed `anthropic`/`google-genai` package, or any API key: every
client/model import is constructed lazily, inside methods, not at import
time or in `__init__`.

Response shape confirmed against the installed `ollama==0.6.2` package
(`app/.venv/lib/python3.12/site-packages/ollama/_types.py`):
    resp = client.chat(model=..., messages=[...], tools=[...])
    resp.message                       -> ollama._types.Message
    resp.message.content               -> str | None (assistant text)
    resp.message.tool_calls            -> Sequence[Message.ToolCall] | None
    tool_call.function.name            -> str
    tool_call.function.arguments       -> Mapping[str, Any] (already a dict,
                                           NOT a JSON string to parse)
A `ConnectionError` is raised by the client when Ollama isn't reachable
(`ollama._client.CONNECTION_ERROR_MESSAGE`, wraps httpx.ConnectError).

Gemini shapes confirmed against the installed `google-genai==2.20.0` package
(`app/.venv/lib/python3.12/site-packages/google/genai/`):
    client = genai.Client(api_key=...)
    types.FunctionDeclaration(name=..., description=..., parameters_json_schema=<schema>)
    types.Tool(function_declarations=[...])
    types.AutomaticFunctionCallingConfig(disable=True)  # we dispatch manually
    types.GenerateContentConfig(system_instruction=..., tools=[...], automatic_function_calling=...)
    response = client.models.generate_content(model=..., contents=[types.Content, ...], config=...)
    response.function_calls  -> Optional[list[types.FunctionCall]] (None, not [], when empty)
    fc.name / fc.args        -> str / dict (already a dict, not JSON text)
    response.text            -> Optional[str] (concatenation of text parts)
    types.Part.from_function_call(name=..., args=<dict>)
    types.Part.from_function_response(name=..., response=<dict>)
    types.Content(role="user"/"model", parts=[...])
    types.Part.thought_signature -> Optional[bytes] (alias "thoughtSignature").
        Gemini 3.x models set this on every function_call Part in the
        response; it must be set back on the replayed Part on the next turn
        (`part.thought_signature = <saved bytes>`) or the API 400s with
        "Function call is missing a thought_signature" — see
        https://ai.google.dev/gemini-api/docs/thought-signatures.
"""
import os


class LLMResponse:
    """Normalized result of one `LLMProvider.chat()` call.

    Attributes:
        assistant_message: dict in `{"role": "assistant", ...}` shape, ready
            to append to the running `messages` list as-is.
        tool_calls: list of `{"name": str, "arguments": dict}` dicts — empty
            when the model didn't request any tool calls.
    """

    def __init__(self, assistant_message: dict, tool_calls: list[dict], reply_text: str = ""):
        self.assistant_message = assistant_message
        self.tool_calls = tool_calls
        self.reply_text = reply_text


class LLMProvider:
    """Base interface every provider implements."""

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError

    def format_tool_results(self, results: list[dict]) -> list[dict]:
        """Wraps executed tool outputs as provider-native message(s) to append.

        Args:
            results: list of `{"name", "arguments", "output", ...}` dicts, one
                per tool call executed this turn (in `chat()`'s order).
        """
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    """Local, keyless provider backed by a running Ollama server."""

    DEFAULT_MODEL = "qwen3:8b"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or os.environ.get("OLLAMA_MODEL", self.DEFAULT_MODEL)
        self.host = host or os.environ.get("OLLAMA_HOST")
        self._client = None

    def _get_client(self):
        # Imported lazily so importing this module never requires the
        # `ollama` package (or a reachable server) to be present.
        if self._client is None:
            import ollama

            self._client = ollama.Client(host=self.host) if self.host else ollama.Client()
        return self._client

    def is_available(self) -> bool:
        try:
            client = self._get_client()
            models = {m.model for m in client.list().models}
        except Exception:
            # Covers: `ollama` not installed, server unreachable
            # (ConnectionError), malformed responses, etc. — never raise.
            return False
        if self.model in models:
            return True
        # Also accept a bare match ignoring an explicit ":latest" tag, since
        # `ollama list` may report either form depending on how the model
        # was pulled.
        return any(
            m == self.model or m.split(":")[0] == self.model.split(":")[0]
            for m in models
        )

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        client = self._get_client()
        response = client.chat(model=self.model, messages=messages, tools=tools)
        message = response.message

        assistant_message = {
            "role": message.role,
            "content": message.content or "",
        }

        tool_calls = []
        if message.tool_calls:
            # Preserve the raw tool_calls on the assistant message we replay
            # back to the model, in the same shape the client accepts.
            assistant_message["tool_calls"] = [
                {
                    "function": {
                        "name": tc.function.name,
                        "arguments": dict(tc.function.arguments),
                    }
                }
                for tc in message.tool_calls
            ]
            for tc in message.tool_calls:
                tool_calls.append(
                    {
                        "name": tc.function.name,
                        "arguments": dict(tc.function.arguments),
                    }
                )

        return LLMResponse(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            reply_text=message.content or "",
        )

    def format_tool_results(self, results: list[dict]) -> list[dict]:
        """Wraps executed tool outputs as Ollama `{"role": "tool", ...}` messages.

        Args:
            results: list of `{"name", "arguments", "output", ...}` dicts, one
                per tool call executed this turn (in the same order they were
                returned by `chat()`).
        """
        return [{"role": "tool", "content": r["output"]} for r in results]


class AnthropicProvider(LLMProvider):
    """Optional provider backed by the Anthropic API (requires a key)."""

    DEFAULT_MODEL = "claude-opus-5"
    MAX_TOKENS = 4096

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", self.DEFAULT_MODEL)
        self._client = None

    def _get_client(self):
        # Imported lazily so importing this module never requires the
        # `anthropic` package or an API key to be present.
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def is_available(self) -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
        anthropic_tools = []
        for tool in tools:
            fn = tool["function"]
            anthropic_tools.append(
                {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return anthropic_tools

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        client = self._get_client()

        system = None
        anthropic_messages = []
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content")
            else:
                anthropic_messages.append(m)

        response = client.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            system=system,
            tools=self._to_anthropic_tools(tools),
            messages=anthropic_messages,
        )

        text_blocks = [b.text for b in response.content if b.type == "text"]
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        assistant_message = {
            "role": "assistant",
            "content": [
                block.model_dump() if hasattr(block, "model_dump") else block
                for block in response.content
            ],
        }

        tool_calls = [
            {"name": b.name, "arguments": dict(b.input), "id": b.id}
            for b in tool_use_blocks
        ]

        reply_text = "\n".join(text_blocks)

        return LLMResponse(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            reply_text=reply_text,
        )

    def format_tool_results(self, results: list[dict]) -> list[dict]:
        """Wraps executed tool outputs as a single Anthropic `tool_result` user message."""
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["id"],
                        "content": r["output"],
                    }
                    for r in results
                ],
            }
        ]


class GeminiProvider(LLMProvider):
    """Default provider backed by the Gemini API (free tier via an AI Studio key).

    Manual function calling is used throughout (`automatic_function_calling`
    disabled) so the agent's tool-dispatch loop — and its dry-run safety
    gate — stays in full control, exactly as with the other providers.
    """

    DEFAULT_MODEL = "gemini-3.6-flash"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("GEMINI_MODEL", self.DEFAULT_MODEL)
        self._client = None

    def _get_client(self):
        # Imported lazily so importing this module never requires the
        # `google-genai` package or an API key to be present.
        if self._client is None:
            from google import genai

            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            self._client = genai.Client(api_key=api_key)
        return self._client

    def is_available(self) -> bool:
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            return False
        try:
            from google.genai import types  # noqa: F401
        except Exception:
            # Covers: `google-genai` not installed, or any import-time error.
            return False
        return True

    @staticmethod
    def _to_gemini_tools(tools: list[dict]):
        from google.genai import types

        declarations = []
        for tool in tools:
            fn = tool["function"]
            declarations.append(
                types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters_json_schema=fn.get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                )
            )
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _to_gemini_contents(messages: list[dict]):
        """Converts the neutral `messages` list into Gemini `contents` + system text.

        Recognizes the plain `{"role": "system"/"user", "content": str}`
        shapes `run_agent` seeds the conversation with, plus this provider's
        own native shapes appended by `chat()`/`format_tool_results()`:
            {"role": "assistant", "content": str, "tool_calls": [{"name","arguments"}, ...]}
            {"role": "tool", "tool_results": [{"name","output"}, ...]}
        """
        from google.genai import types

        system_instruction = None
        contents = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_instruction = m.get("content")
                continue
            if role == "tool":
                parts = [
                    types.Part.from_function_response(
                        name=tr["name"], response={"result": tr["output"]}
                    )
                    for tr in m.get("tool_results", [])
                ]
                contents.append(types.Content(role="user", parts=parts))
                continue

            gemini_role = "model" if role == "assistant" else "user"
            parts = []
            content = m.get("content")
            if content:
                parts.append(types.Part.from_text(text=content))
            for call in m.get("tool_calls", []):
                part = types.Part.from_function_call(
                    name=call["name"], args=call.get("arguments", {})
                )
                # Gemini 3.x requires the exact `thought_signature` bytes the
                # model attached to this function_call Part to be replayed
                # back unchanged on the next turn — dropping it 400s with
                # "Function call is missing a thought_signature". Captured in
                # chat() below and carried on the normalized tool_call dict.
                sig = call.get("thought_signature")
                if sig is not None:
                    part.thought_signature = sig
                parts.append(part)
            contents.append(types.Content(role=gemini_role, parts=parts))
        return contents, system_instruction

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        from google.genai import types

        client = self._get_client()
        contents, system_instruction = self._to_gemini_contents(messages)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=self._to_gemini_tools(tools),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = client.models.generate_content(
            model=self.model, contents=contents, config=config
        )

        reply_text = response.text or ""

        # Read tool calls directly off the response's Parts (not the
        # `.function_calls` convenience property) so we can also capture each
        # function_call Part's `thought_signature` — Gemini 3.x models
        # attach one to every function_call Part, and it MUST be replayed
        # back verbatim on the next turn's request or the API 400s with
        # "Function call is missing a thought_signature" (see
        # https://ai.google.dev/gemini-api/docs/thought-signatures).
        tool_calls = []
        candidates = response.candidates or []
        if candidates and candidates[0].content and candidates[0].content.parts:
            for part in candidates[0].content.parts:
                fc = part.function_call
                if fc is None:
                    continue
                tool_calls.append(
                    {
                        "name": fc.name,
                        "arguments": dict(fc.args or {}),
                        "thought_signature": part.thought_signature,
                    }
                )

        assistant_message = {
            "role": "assistant",
            "content": reply_text,
            "tool_calls": tool_calls,
        }

        return LLMResponse(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            reply_text=reply_text,
        )

    def format_tool_results(self, results: list[dict]) -> list[dict]:
        """Wraps executed tool outputs as a single native `{"role": "tool", ...}` message."""
        return [
            {
                "role": "tool",
                "tool_results": [
                    {"name": r["name"], "output": r["output"]} for r in results
                ],
            }
        ]


def get_provider() -> LLMProvider:
    """Selects an `LLMProvider` via the `LLM_PROVIDER` env var (default "gemini")."""
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if provider_name == "anthropic":
        return AnthropicProvider()
    if provider_name == "ollama":
        return OllamaProvider()
    return GeminiProvider()
