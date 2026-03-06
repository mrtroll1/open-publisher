"""Gemini API gateway — thin JSON-returning LLM wrapper."""

from __future__ import annotations

import json
import logging
import time
from google.genai import types
from google import genai
from google.genai.errors import ClientError, ServerError


from common.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


class GeminiGateway:
    """Wraps Google Gemini API calls. Returns parsed JSON."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self._model = model
        self.safety_settings = [
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="OFF"
            ),
        ]

    def call(self, prompt: str, model: str | None = None) -> dict:
        """Send a prompt and return parsed JSON from the response."""

        model_used = model or self._model
        client = genai.Client(api_key=GEMINI_API_KEY)

        config_kwargs = {
            "safety_settings": self.safety_settings,
        }

        if "gemini-3-flash" in model_used:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            )
        config = types.GenerateContentConfig(**config_kwargs)

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_used,
                    contents=prompt,
                    config=config
                )
                raw = response.text.strip()
                return self._extract_json(raw)
            except (ServerError, ClientError) as e:
                if attempt == 2:
                    raise
                wait = (attempt + 1) * 5
                logger.warning("Gemini error (%s), retrying in %ds (attempt %d/3)",
                               e, wait, attempt + 1)
                time.sleep(wait)

    def call_with_tools(self, system_prompt: str, user_message: str,
                        tool_declarations: list[dict],
                        model: str | None = None) -> tuple[str | None, list[dict], types.Content]:
        """Single-turn call with function calling support.

        Returns:
            (text, tool_calls, response_content) where:
            - text is the model's text response (None if it made tool calls instead)
            - tool_calls is a list of {"name": str, "args": dict} (empty if text response)
            - response_content is the raw Content object for history building
        """
        model_used = model or self._model
        client = genai.Client(api_key=GEMINI_API_KEY)

        tool = types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=d["name"],
                description=d["description"],
                parameters=self._json_schema_to_gemini(d["parameters"]),
            )
            for d in tool_declarations
        ])

        config_kwargs = {
            "tools": [tool],
            "safety_settings": self.safety_settings,
            "system_instruction": system_prompt,
        }
        if "gemini-3-flash" in model_used:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            )
        config = types.GenerateContentConfig(**config_kwargs)

        contents = [types.Content(role="user", parts=[types.Part.from_text(user_message)])]

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_used, contents=contents, config=config,
                )
                return self._parse_tool_response(response)
            except (ServerError, ClientError) as e:
                if attempt == 2:
                    raise
                wait = (attempt + 1) * 5
                logger.warning("Gemini error (%s), retrying in %ds (attempt %d/3)",
                               e, wait, attempt + 1)
                time.sleep(wait)

    def continue_with_tool_results(self, history: list, tool_results: list[dict],
                                   tool_declarations: list[dict],
                                   model: str | None = None) -> tuple[str | None, list[dict], types.Content]:
        """Continue a conversation after tool execution.

        Args:
            history: list of google.genai Content objects (previous turns)
            tool_results: list of {"name": str, "result": dict} for each tool call
            tool_declarations: same tool declarations as before
            model: Model to use

        Returns:
            Same as call_with_tools: (text, tool_calls, response_content)
        """
        model_used = model or self._model
        client = genai.Client(api_key=GEMINI_API_KEY)

        tool = types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=d["name"],
                description=d["description"],
                parameters=self._json_schema_to_gemini(d["parameters"]),
            )
            for d in tool_declarations
        ])

        config_kwargs = {
            "tools": [tool],
            "safety_settings": self.safety_settings,
        }
        if "gemini-3-flash" in model_used:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            )
        config = types.GenerateContentConfig(**config_kwargs)

        tool_response_content = types.Content(parts=[
            types.Part.from_function_response(name=r["name"], response=r["result"])
            for r in tool_results
        ])
        contents = history + [tool_response_content]

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_used, contents=contents, config=config,
                )
                return self._parse_tool_response(response)
            except (ServerError, ClientError) as e:
                if attempt == 2:
                    raise
                wait = (attempt + 1) * 5
                logger.warning("Gemini error (%s), retrying in %ds (attempt %d/3)",
                               e, wait, attempt + 1)
                time.sleep(wait)

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
