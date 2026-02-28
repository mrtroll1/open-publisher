"""Use case: generate monthly payments sheet from contractors + content API data."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.models import Contractor, Currency, RoleCode
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.infrastructure.repositories.budget_repo import (
    create_sheet,
    populate_sheet,
    sheet_url,
)
from backend.infrastructure.repositories.contractor_repo import (
    find_contractor,
    find_contractor_by_id,
    load_all_contractors,
)
from backend.infrastructure.repositories.rules_repo import (
    load_redirect_rules,
    load_flat_rate_rules,
    load_article_rate_rules,
)

logger = logging.getLogger(__name__)

RUSSIAN_MONTHS = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]

DEFAULT_RATE_EUR = 100
DEFAULT_RATE_RUB = 10_000


@dataclass
class PaymentEntry:
    """A single row in the payments sheet."""
    name: str = ""
    label: str = ""
    eur: int = 0
    rub: int = 0
    note: str = ""

    @property
    def is_blank(self) -> bool:
        return not self.name


def _compute_budget_amount(
    flat: int | None,
    rate: int | None,
    num_articles: int,
    currency: Currency,
) -> int:
    """Compute the budget amount for a contractor.

    flat only       → flat
    flat + rate     → flat + rate * articles
    rate only       → rate * articles
    neither         → default_rate * articles
    """
    if flat is not None:
        bonus = rate * num_articles if rate is not None and num_articles else 0
        return flat + bonus
    if rate is not None:
        return rate * num_articles
    default = DEFAULT_RATE_RUB if currency == Currency.RUB else DEFAULT_RATE_EUR
    return default * num_articles


def _target_month_name(month: str) -> str:
    """Return Russian month name for payment_month + 2.

    January (01) payments → budget for March (март).
    """
    _, m = month.split("-")
    target = (int(m) + 2 - 1) % 12
    return RUSSIAN_MONTHS[target]


def _role_label(contractor: Contractor) -> str:
    """Derive a column-B label from role_code."""
    if contractor.role_code == RoleCode.REDAKTOR:
        return "Редактор"
    if contractor.role_code == RoleCode.KORREKTOR:
        return "Корректор"
    return ""


BLANK = PaymentEntry()


class ComputeBudget:
    """Build the monthly payments Google Sheet."""

    def __init__(self):
        self._content = RepublicGateway()

    def execute(self, month: str) -> str:
        """Generate the payments sheet for the given month. Returns the sheet URL."""
        contractors = load_all_contractors()
        published_authors = self._content.fetch_published_authors(month)

        entries = self._build_entries(published_authors, contractors, month)

        sheet_id = create_sheet(month)
        self._populate_sheet(sheet_id, entries, month)

        url = sheet_url(sheet_id)
        logger.info("Budget sheet created: %s", url)
        return url

    # ------------------------------------------------------------------
    #  Entry building
    # ------------------------------------------------------------------

    def _build_entries(
        self,
        published_authors: list[dict[str, str | int]],
        contractors: list[Contractor],
        month: str,
    ) -> list[PaymentEntry]:
        """Match authors to contractors, add flat contractors, group everything."""

        # Load rules from the special rules sheet
        redirect_rules = load_redirect_rules()
        flat_rate_rules = load_flat_rate_rules()
        article_rate_rules = load_article_rate_rules()

        # Build lookups
        excludes: set[str] = {r.source_name for r in redirect_rules if not r.target_id}
        redirects: dict[str, tuple[str, bool]] = {
            r.source_name: (r.target_id, r.add_to_total)
            for r in redirect_rules if r.target_id
        }
        flat_by_id: dict[str, int] = {}      # contractor_id → flat amount
        label_by_id: dict[str, str] = {}      # contractor_id → label
        for fr in flat_rate_rules:
            if fr.contractor_id:
                flat_by_id[fr.contractor_id] = fr.eur or fr.rub
                if fr.label:
                    label_by_id[fr.contractor_id] = fr.label
        rate_by_id: dict[str, tuple[int, int]] = {
            ar.contractor_id: (ar.eur, ar.rub) for ar in article_rate_rules
        }

        # 1. Pre-process redirects: resolve target IDs → contractors
        redirect_bonuses: dict[str, list[tuple[str, int, bool]]] = {}
        redirect_targets: dict[str, tuple[Contractor, bool]] = {}
        for source_name, (target_id, add_to_total) in redirects.items():
            tc = find_contractor_by_id(target_id, contractors)
            if tc:
                redirect_targets[source_name] = (tc, add_to_total)
            else:
                logger.warning("Redirect target not found: %s → %s", source_name, target_id)

        # 2. Match published authors to contractors
        matched: dict[str, tuple[Contractor, int]] = {}  # contractor.id → (contractor, article_count)
        unmatched: list[tuple[str, int]] = []  # (author_name, post_count)

        for row in published_authors:
            author_name = row["author"]
            post_count = int(row["post_count"])

            if author_name in excludes:
                continue

            if author_name in redirect_targets:
                target_c, add_to_total = redirect_targets[author_name]
                rate = DEFAULT_RATE_RUB if target_c.currency == Currency.RUB else DEFAULT_RATE_EUR
                amount = rate * post_count
                redirect_bonuses.setdefault(target_c.id, []).append((author_name, amount, add_to_total))
                continue

            c = find_contractor(author_name, contractors)
            if c is None:
                unmatched.append((author_name, post_count))
                continue
            if c.id in matched:
                existing_c, existing_count = matched[c.id]
                matched[c.id] = (existing_c, existing_count + post_count)
            else:
                matched[c.id] = (c, post_count)

        if unmatched:
            logger.warning("Unmatched authors: %s", [name for name, _ in unmatched])

        # 3. Classify all contractors into groups
        author_entries: list[PaymentEntry] = []
        staff_entries: list[PaymentEntry] = []
        editor_entries: list[PaymentEntry] = []
        service_entries: list[PaymentEntry] = []
        chief_entries: list[PaymentEntry] = []

        seen_ids: set[str] = set()

        # Build a lookup of author→post_count for flat+rate contractors
        author_counts: dict[str, int] = {
            row["author"].lower().strip(): int(row["post_count"])
            for row in published_authors
        }

        def _make_noted_entry(c: Contractor, amount: int, label: str) -> PaymentEntry:
            """Build entry, adding redirect bonus notes to column E."""
            bonuses = redirect_bonuses.get(c.id, [])
            note = ", ".join(f"{name} ({amt})" for name, amt, _ in bonuses)
            bonus_total = sum(amt for _, amt, add in bonuses if add)
            if c.currency == Currency.EUR:
                return PaymentEntry(name=c.display_name, label=label,
                                    eur=amount + bonus_total, note=note)
            return PaymentEntry(name=c.display_name, label=label,
                                rub=amount + bonus_total, note=note)

        # Process published authors first (order preserved from API)
        for cid, (c, article_count) in matched.items():
            flat = flat_by_id.get(cid)
            rate_tuple = rate_by_id.get(cid)
            rate = (rate_tuple[0] or rate_tuple[1]) if rate_tuple else None
            amount = _compute_budget_amount(flat, rate, article_count, c.currency)
            if amount <= 0:
                continue
            seen_ids.add(cid)
            entry_label = label_by_id.get(cid, "") or _role_label(c)
            entry = _make_noted_entry(c, amount, entry_label)
            self._route_entry(c, entry_label, entry, flat_by_id, author_entries,
                              staff_entries, editor_entries, service_entries, chief_entries)

        # Add flat-rate contractors not already included
        for fr in flat_rate_rules:
            if not fr.contractor_id or fr.contractor_id in seen_ids:
                continue
            c = find_contractor_by_id(fr.contractor_id, contractors)
            if c is None:
                logger.warning("Flat-rate contractor not found: %s", fr.contractor_id)
                continue
            flat = fr.eur or fr.rub
            rate_tuple = rate_by_id.get(fr.contractor_id)
            rate = (rate_tuple[0] or rate_tuple[1]) if rate_tuple else None
            # Check if they also have articles
            article_count = 0
            if rate is not None:
                for name in c.all_names:
                    count = author_counts.get(name.lower().strip(), 0)
                    if count:
                        article_count = count
                        break
            amount = _compute_budget_amount(flat, rate, article_count, c.currency)
            if amount <= 0:
                continue
            seen_ids.add(fr.contractor_id)
            entry_label = fr.label or _role_label(c)
            entry = _make_noted_entry(c, amount, entry_label)
            self._route_entry(c, entry_label, entry, flat_by_id, author_entries,
                              staff_entries, editor_entries, service_entries, chief_entries)

        # Unmatched authors — added with default 100€ per article
        unmatched_entries: list[PaymentEntry] = []
        for author_name, post_count in unmatched:
            amount = DEFAULT_RATE_EUR * post_count
            unmatched_entries.append(
                PaymentEntry(name=author_name, eur=amount)
            )

        # Non-contractor flat entries (AFP, ElevenLabs, etc.)
        for fr in flat_rate_rules:
            if fr.contractor_id:
                continue
            entry = PaymentEntry(name=fr.name, label=fr.label, eur=fr.eur, rub=fr.rub)
            service_entries.append(entry)

        # Assemble final list with grouping and blank separators
        result: list[PaymentEntry] = []

        if author_entries:
            result.extend(author_entries)
            result.extend([BLANK, BLANK])

        if staff_entries:
            result.extend(staff_entries)
            result.append(BLANK)

        if editor_entries:
            result.extend(editor_entries)
            result.append(BLANK)

        result.extend(service_entries)
        result.append(BLANK)

        if chief_entries:
            result.extend(chief_entries)
            result.append(BLANK)

        if unmatched_entries:
            result.extend(unmatched_entries)

        return result

    @staticmethod
    def _route_entry(
        contractor: Contractor,
        label: str,
        entry: PaymentEntry,
        flat_ids: dict[str, int],
        authors: list[PaymentEntry],
        staff: list[PaymentEntry],
        editors: list[PaymentEntry],
        services: list[PaymentEntry],
        chief: list[PaymentEntry],
    ) -> None:
        """Route an entry to the appropriate group based on label and role."""
        label_lower = label.lower()
        if label_lower in ("фото", "аудио"):
            services.append(entry)
        elif label_lower == "главный редактор":
            chief.append(entry)
        elif contractor.role_code == RoleCode.REDAKTOR:
            editors.append(entry)
        elif label or contractor.role_code == RoleCode.KORREKTOR:
            staff.append(entry)
        else:
            if contractor.id in flat_ids:
                staff.append(entry)
            else:
                authors.append(entry)

    # ------------------------------------------------------------------
    #  Sheet population
    # ------------------------------------------------------------------

    def _populate_sheet(self, sheet_id: str, entries: list[PaymentEntry], month: str) -> None:
        """Write payment entries into the copied template sheet."""
        rows: list[list[str]] = []
        for e in entries:
            if e.is_blank:
                rows.append(["", "", "", "", ""])
            else:
                eur_str = str(e.eur) if e.eur else ""
                rub_str = str(e.rub) if e.rub else ""
                rows.append([e.name, e.label, eur_str, rub_str, e.note])

        target = _target_month_name(month)
        header = f"Editorial Expenses (бюджет на {target})"
        populate_sheet(sheet_id, rows, header)
