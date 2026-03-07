"""Gemini API gateway — thin JSON-returning LLM wrapper."""

from __future__ import annotations

import json
import logging
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from backend.config import GEMINI_API_KEY, GEMINI_MODEL_FAST

logger = logging.getLogger(__name__)

_SAFETY_OFF = [
    types.SafetySetting(category=cat, threshold="OFF")
    for cat in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]

_MAX_RETRIES = 3


class GeminiGateway:
    """Wraps Google Gemini API calls. Returns parsed JSON."""

    def __init__(self, model: str = GEMINI_MODEL_FAST):
        self._model = model
        self._client = genai.Client(api_key=GEMINI_API_KEY)

    def _config(self, model: str, **extra) -> types.GenerateContentConfig:
        kwargs = {"safety_settings": _SAFETY_OFF, **extra}
        if "gemini-3-flash" in model:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL,
            )
        return types.GenerateContentConfig(**kwargs)

    def _generate(self, model: str, contents, config: types.GenerateContentConfig):
        for attempt in range(_MAX_RETRIES):
            try:
                return self._client.models.generate_content(
                    model=model, contents=contents, config=config,
                )
            except (ServerError, ClientError) as e:
                if attempt == _MAX_RETRIES - 1:
                    raise
                wait = (attempt + 1) * 5
                logger.warning("Gemini error (%s), retrying in %ds (attempt %d/%d)",
                               e, wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
        return None

    @staticmethod
    def _build_tool(declarations: list[dict]) -> types.Tool:
        return types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=d["name"],
                description=d["description"],
                parameters=GeminiGateway._json_schema_to_gemini(d["parameters"]),
            )
            for d in declarations
        ])

    def call(self, prompt: str, model: str | None = None) -> dict:
        """Send a prompt and return parsed JSON from the response."""
        model_used = model or self._model
        config = self._config(model_used)
        response = self._generate(model_used, prompt, config)
        return self._extract_json(response.text.strip())

    def call_with_tools(self, system_prompt: str, user_message: str,
                        tool_declarations: list[dict],
                        model: str | None = None) -> tuple[str | None, list[dict], types.Content]:
        """Single-turn call with function calling support."""
        model_used = model or self._model
        config = self._config(
            model_used,
            tools=[self._build_tool(tool_declarations)],
            system_instruction=system_prompt,
        )
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_message)])]
        response = self._generate(model_used, contents, config)
        return self._parse_tool_response(response)

    def continue_with_tool_results(self, history: list, tool_results: list[dict],
                                   tool_declarations: list[dict],
                                   model: str | None = None,
                                   extra_instruction: str | None = None) -> tuple[str | None, list[dict], types.Content]:
        """Continue a conversation after tool execution."""
        model_used = model or self._model
        config = self._config(model_used, tools=[self._build_tool(tool_declarations)])
        tool_parts = [
            types.Part.from_function_response(name=r["name"], response=r["result"])
            for r in tool_results
        ]
        if extra_instruction:
            tool_parts.append(types.Part.from_text(text=extra_instruction))
        tool_response_content = types.Content(parts=tool_parts)
        contents = [*history, tool_response_content]
        response = self._generate(model_used, contents, config)
        return self._parse_tool_response(response)

    @staticmethod
    def _parse_tool_response(response) -> tuple[str | None, list[dict], types.Content]:
        """Extract text and tool calls from a Gemini response."""
        content = response.candidates[0].content
        text = None
        tool_calls = []
        for part in content.parts:
            if part.function_call:
                tool_calls.append({
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args),
                })
            elif part.text:
                text = part.text
        return text, tool_calls, content

    @staticmethod
    def _json_schema_to_gemini(schema: dict) -> types.Schema:
        """Convert a JSON Schema dict to Gemini types.Schema."""
        type_map = {
            "string": "STRING",
            "number": "NUMBER",
            "integer": "INTEGER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
            "object": "OBJECT",
        }

        kwargs = {"type": type_map[schema["type"]]}

        if "description" in schema:
            kwargs["description"] = schema["description"]

        if "enum" in schema:
            kwargs["enum"] = schema["enum"]

        if "properties" in schema:
            kwargs["properties"] = {
                k: GeminiGateway._json_schema_to_gemini(v)
                for k, v in schema["properties"].items()
            }

        if "required" in schema:
            kwargs["required"] = schema["required"]

        if "items" in schema:
            kwargs["items"] = GeminiGateway._json_schema_to_gemini(schema["items"])

        return types.Schema(**kwargs)

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Extract JSON object from LLM response (handles markdown fences)."""
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        def _try_loads(s: str) -> dict:
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                cleaned = s.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n").replace("\t", "\\t")
                return json.loads(cleaned)

        if raw.startswith("{"):
            return _try_loads(raw)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return _try_loads(raw[start:end])
        return {"raw_parsed": raw}
