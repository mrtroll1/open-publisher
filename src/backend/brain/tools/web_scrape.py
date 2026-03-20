"""Web scrape tool — fetch URL and extract content."""

from __future__ import annotations

import logging

import httpx
import trafilatura

from backend.brain.tool import Tool, ToolContext

logger = logging.getLogger(__name__)

_MAX_TEXT_LENGTH = 5000
_TIMEOUT = 15


def make_web_scrape_tool() -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        url = args.get("url", "")
        if not url:
            return {"error": "Нужен url"}
        try:
            resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; RepublicBot/1.0)"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return {"error": f"Не удалось загрузить: {e}"}
        extracted = trafilatura.extract(resp.text, include_links=True, include_tables=True)
        if not extracted:
            return {"error": "Не удалось извлечь текст", "url": url}
        metadata = trafilatura.extract_metadata(resp.text)
        title_text = metadata.title if metadata and metadata.title else url
        text = extracted[:_MAX_TEXT_LENGTH]
        if len(extracted) > _MAX_TEXT_LENGTH:
            text += f"\n\n[обрезано, полный текст {len(extracted)} символов]"
        return {"title": title_text, "text": text, "url": url}

    return Tool(
        name="web_scrape",
        description="Загрузить веб-страницу и извлечь текст. Используй после web_search для получения полного содержания.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL страницы для загрузки"},
            },
            "required": ["url"],
        },
        fn=fn,
        permissions={},
        nl_routable=False,
        conversational=True,
    )
