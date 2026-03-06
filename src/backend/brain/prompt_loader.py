"""Load LLM prompt templates from disk."""

from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES = _ROOT / "templates"
_CET = timezone(timedelta(hours=1))


def load_template(name: str, replacements: dict[str, str] | None = None) -> str:
    text = (_TEMPLATES / name).read_text(encoding="utf-8")
    now = datetime.now(_CET)
    text = f"Текущая дата и время: {now.strftime('%Y-%m-%d %H:%M')} (CET)\n\n" + text
    for key, val in (replacements or {}).items():
        text = text.replace(f"{{{{{key}}}}}", val)
    return text
