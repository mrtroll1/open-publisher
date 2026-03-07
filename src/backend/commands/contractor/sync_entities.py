"""Sync contractors from Google Sheets into the entities system."""

from __future__ import annotations

from backend.models import Contractor, RoleCode

_ROLE_LABELS = {
    RoleCode.AUTHOR: "автор",
    RoleCode.REDAKTOR: "редактор",
    RoleCode.KORREKTOR: "корректор",
}


def _build_summary(c: Contractor) -> str:
    parts = [c.display_name]
    parts.append(f"тип: {c.type.value}")
    parts.append(f"роль: {_ROLE_LABELS.get(c.role_code, c.role_code.value)}")
    if c.mags:
        parts.append(f"издания: {c.mags}")
    parts.append("telegram: да" if c.telegram else "telegram: нет")
    return ", ".join(parts)


def execute(contractors: list[Contractor], db, embed) -> tuple[int, int]:
    """For each contractor, create/update a matching entity. Returns (created, updated)."""
    created = 0
    updated = 0
    for c in contractors:
        existing = db.find_entity_by_external_id("contractor_name", c.display_name)
        summary = _build_summary(c)
        if existing:
            db.update_entity(existing["id"], summary=summary)
            updated += 1
        else:
            external_ids = {
                "contractor_name": c.display_name,
                "contractor_type": c.type.value,
            }
            if c.telegram:
                external_ids["telegram_id"] = c.telegram
            db.save_entity(
                kind="person",
                name=c.display_name,
                external_ids=external_ids,
                summary=summary,
                embedding=embed.embed_one(f"{c.display_name} {c.type.value}"),
            )
            created += 1
    return created, updated
