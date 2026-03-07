"""Use case: generate monthly payments sheet from contractors + content API data."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.config import EUR_RUB_CELL
from backend.infrastructure.gateways.exchange_rate_gateway import fetch_eur_rub_rate
from backend.infrastructure.gateways.redefine_gateway import RedefineGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.infrastructure.repositories.sheets.budget_repo import (
    create_sheet,
    populate_sheet,
    sheet_url,
    write_pnl_section,
)
from backend.infrastructure.repositories.sheets.contractor_repo import (
    find_contractor,
    find_contractor_by_id,
    load_all_contractors,
)
from backend.infrastructure.repositories.sheets.rules_repo import (
    load_article_rate_rules,
    load_flat_rate_rules,
    load_redirect_rules,
)
from backend.models import Contractor, Currency, RoleCode

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

    flat only       -> flat
    flat + rate     -> flat + rate * articles
    rate only       -> rate * articles
    neither         -> default_rate * articles
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

    January (01) payments -> budget for March.
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


def _pick_by_currency(eur_rub: tuple[int, int] | None, currency: Currency) -> int | None:
    """Pick EUR or RUB from a tuple, treating 0 as absent."""
    if not eur_rub:
        return None
    val = eur_rub[0] if currency == Currency.EUR else eur_rub[1]
    return val or None


BLANK = PaymentEntry()


class ComputeBudget:
    """Build the monthly payments Google Sheet."""

    def __init__(self, republic_gw: RepublicGateway | None = None, redefine_gw: RedefineGateway | None = None):
        self._content = republic_gw or RepublicGateway()
        self._redefine = redefine_gw or RedefineGateway()

    def execute(self, month: str) -> str:
        """Generate the payments sheet for the given month. Returns the sheet URL."""
        contractors = load_all_contractors()
        published_authors = self._content.fetch_published_authors(month)

        entries = self._build_entries(published_authors, contractors, month)

        eur_rub_rate = fetch_eur_rub_rate()
        pnl_data = self._redefine.get_pnl_stats(month)

        sheet_id = create_sheet(month)
        self._populate_sheet(sheet_id, entries, month)

        # PNL section starts after main entries (row 2 + number of entries)
        pnl_start_row = 2 + len(entries) + 1  # +1 for a blank separator row
        pnl_rows = self._build_pnl_rows(pnl_data, eur_rub_rate)
        write_pnl_section(sheet_id, pnl_start_row, eur_rub_rate, pnl_rows)

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
        _month: str,
    ) -> list[PaymentEntry]:
        lookups = self._load_rule_lookups()
        flat_rate_rules, flat_by_id, label_by_id, rate_by_id = (
            lookups["flat_rate_rules"], lookups["flat_by_id"],
            lookups["label_by_id"], lookups["rate_by_id"],
        )

        matched, unmatched, redirect_bonuses = self._match_authors(
            published_authors, contractors,
            lookups["excludes"], lookups["redirect_targets"],
        )

        author_counts: dict[str, int] = {
            row["author"].lower().strip(): int(row["post_count"])
            for row in published_authors
        }

        groups = self._classify_entries(
            matched, flat_rate_rules, contractors,
            flat_by_id=flat_by_id, label_by_id=label_by_id, rate_by_id=rate_by_id,
            author_counts=author_counts, redirect_bonuses=redirect_bonuses,
        )

        unmatched_entries = [
            PaymentEntry(name=name, eur=DEFAULT_RATE_EUR * count)
            for name, count in unmatched
        ]

        service_entries = groups["services"]
        for fr in flat_rate_rules:
            if not fr.contractor_id:
                service_entries.append(
                    PaymentEntry(name=fr.name, label=fr.label, eur=fr.eur, rub=fr.rub)
                )

        return self._assemble_grouped_result(groups, unmatched_entries)

    @staticmethod
    def _load_rule_lookups() -> dict:
        redirect_rules = load_redirect_rules()
        flat_rate_rules = load_flat_rate_rules()
        article_rate_rules = load_article_rate_rules()

        excludes: set[str] = {r.source_name for r in redirect_rules if not r.target_id}
        redirects: dict[str, tuple[str, bool]] = {
            r.source_name: (r.target_id, r.add_to_total)
            for r in redirect_rules if r.target_id
        }

        flat_by_id: dict[str, tuple[int, int]] = {}
        label_by_id: dict[str, str] = {}
        for fr in flat_rate_rules:
            if fr.contractor_id:
                flat_by_id[fr.contractor_id] = (fr.eur, fr.rub)
                if fr.label:
                    label_by_id[fr.contractor_id] = fr.label
        rate_by_id: dict[str, tuple[int, int]] = {
            ar.contractor_id: (ar.eur, ar.rub) for ar in article_rate_rules
        }

        return {
            "flat_rate_rules": flat_rate_rules,
            "excludes": excludes,
            "redirect_targets": redirects,
            "flat_by_id": flat_by_id,
            "label_by_id": label_by_id,
            "rate_by_id": rate_by_id,
        }

    @staticmethod
    def _match_authors(
        published_authors: list[dict[str, str | int]],
        contractors: list[Contractor],
        excludes: set[str],
        redirects: dict[str, tuple[str, bool]],
    ) -> tuple[
        dict[str, tuple[Contractor, int]],
        list[tuple[str, int]],
        dict[str, list[tuple[str, int, bool]]],
    ]:
        # Resolve redirect target IDs -> contractors
        redirect_targets: dict[str, tuple[Contractor, bool]] = {}
        for source_name, (target_id, add_to_total) in redirects.items():
            tc = find_contractor_by_id(target_id, contractors)
            if tc:
                redirect_targets[source_name] = (tc, add_to_total)
            else:
                logger.warning("Redirect target not found: %s -> %s", source_name, target_id)

        redirect_bonuses: dict[str, list[tuple[str, int, bool]]] = {}
        matched: dict[str, tuple[Contractor, int]] = {}
        unmatched: list[tuple[str, int]] = []

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

        return matched, unmatched, redirect_bonuses

    def _classify_entries(  # noqa: PLR0913
        self,
        matched: dict[str, tuple[Contractor, int]],
        flat_rate_rules: list,
        contractors: list[Contractor],
        *,
        flat_by_id: dict[str, tuple[int, int]],
        label_by_id: dict[str, str],
        rate_by_id: dict[str, tuple[int, int]],
        author_counts: dict[str, int],
        redirect_bonuses: dict[str, list[tuple[str, int, bool]]],
    ) -> dict[str, list[PaymentEntry]]:
        groups: dict[str, list[PaymentEntry]] = {
            "authors": [], "staff": [], "editors": [], "services": [], "chief": [],
        }
        seen_ids: set[str] = set()

        self._process_matched_entries(
            matched,
            flat_by_id=flat_by_id, rate_by_id=rate_by_id, label_by_id=label_by_id,
            redirect_bonuses=redirect_bonuses, groups=groups, seen_ids=seen_ids,
        )
        self._process_flat_entries(
            flat_rate_rules, contractors,
            flat_by_id=flat_by_id, rate_by_id=rate_by_id,
            author_counts=author_counts, redirect_bonuses=redirect_bonuses,
            label_by_id=label_by_id, groups=groups, seen_ids=seen_ids,
        )
        return groups

    def _process_matched_entries(  # noqa: PLR0913
        self,
        matched: dict[str, tuple[Contractor, int]], *,
        flat_by_id: dict[str, tuple[int, int]],
        rate_by_id: dict[str, tuple[int, int]],
        label_by_id: dict[str, str],
        redirect_bonuses: dict[str, list[tuple[str, int, bool]]],
        groups: dict[str, list[PaymentEntry]],
        seen_ids: set[str],
    ) -> None:
        for cid, (c, article_count) in matched.items():
            flat = _pick_by_currency(flat_by_id.get(cid), c.currency)
            rate = _pick_by_currency(rate_by_id.get(cid), c.currency)
            amount = _compute_budget_amount(flat, rate, article_count, c.currency)
            if amount <= 0:
                continue
            seen_ids.add(cid)
            entry_label = label_by_id.get(cid, "") or _role_label(c)
            entry = self._make_noted_entry(c, amount, entry_label, redirect_bonuses)
            self._route_entry(c, entry_label, entry, flat_by_id,
                              authors=groups["authors"], staff=groups["staff"],
                              editors=groups["editors"], services=groups["services"],
                              chief=groups["chief"])

    def _process_flat_entries(  # noqa: PLR0913
        self,
        flat_rate_rules: list,
        contractors: list[Contractor], *,
        flat_by_id: dict[str, tuple[int, int]],
        rate_by_id: dict[str, tuple[int, int]],
        author_counts: dict[str, int],
        redirect_bonuses: dict[str, list[tuple[str, int, bool]]],
        _label_by_id: dict[str, str],
        groups: dict[str, list[PaymentEntry]],
        seen_ids: set[str],
    ) -> None:
        for fr in flat_rate_rules:
            if not fr.contractor_id or fr.contractor_id in seen_ids:
                continue
            c = find_contractor_by_id(fr.contractor_id, contractors)
            if c is None:
                logger.warning("Flat-rate contractor not found: %s", fr.contractor_id)
                continue
            flat = _pick_by_currency((fr.eur, fr.rub), c.currency)
            rate = _pick_by_currency(rate_by_id.get(fr.contractor_id), c.currency)
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
            entry = self._make_noted_entry(c, amount, entry_label, redirect_bonuses)
            self._route_entry(c, entry_label, entry, flat_by_id,
                              authors=groups["authors"], staff=groups["staff"],
                              editors=groups["editors"], services=groups["services"],
                              chief=groups["chief"])

    @staticmethod
    def _make_noted_entry(
        c: Contractor,
        amount: int,
        label: str,
        redirect_bonuses: dict[str, list[tuple[str, int, bool]]],
    ) -> PaymentEntry:
        """Build entry, adding redirect bonus notes to column E."""
        bonuses = redirect_bonuses.get(c.id, [])
        note = ", ".join(f"{name} ({amt})" for name, amt, _ in bonuses)
        bonus_total = sum(amt for _, amt, add in bonuses if add)
        if c.currency == Currency.EUR:
            return PaymentEntry(name=c.display_name, label=label,
                                eur=amount + bonus_total, note=note)
        return PaymentEntry(name=c.display_name, label=label,
                            rub=amount + bonus_total, note=note)

    @staticmethod
    def _assemble_grouped_result(
        groups: dict[str, list[PaymentEntry]],
        unmatched_entries: list[PaymentEntry],
    ) -> list[PaymentEntry]:
        result: list[PaymentEntry] = []

        if groups["authors"]:
            result.extend(groups["authors"])
            result.extend([BLANK, BLANK])

        if groups["staff"]:
            result.extend(groups["staff"])
            result.append(BLANK)

        if groups["editors"]:
            result.extend(groups["editors"])
            result.append(BLANK)

        result.extend(groups["services"])
        result.append(BLANK)

        if groups["chief"]:
            result.extend(groups["chief"])
            result.append(BLANK)

        if unmatched_entries:
            result.extend(unmatched_entries)

        return result

    @staticmethod
    def _route_entry(  # noqa: PLR0913
        contractor: Contractor,
        label: str,
        entry: PaymentEntry,
        flat_ids: dict[str, tuple[int, int]], *,
        authors: list[PaymentEntry],
        staff: list[PaymentEntry],
        editors: list[PaymentEntry],
        services: list[PaymentEntry],
        chief: list[PaymentEntry],
    ) -> None:
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

    @staticmethod
    def _build_pnl_rows(pnl_data: dict, eur_rub_rate: float) -> list[list[str]]:
        # EUR column uses a Sheets formula dividing RUB by the rate in EUR_RUB_CELL
        if not pnl_data or not eur_rub_rate:
            return []
        col = "".join(c for c in EUR_RUB_CELL if c.isalpha())
        row_num = "".join(c for c in EUR_RUB_CELL if c.isdigit())
        abs_ref = f"${col}${row_num}"
        units = ", ".join(pnl_data.get("units", []))
        rows: list[list[str]] = []
        for label, key in [("Revenue", "revenue"), ("Expenses", "expenses")]:
            amount = pnl_data.get(key, 0)
            if not amount:
                continue
            eur_formula = f"=ROUND({amount}/{abs_ref}, 0)"
            rows.append([label, f"PNL ({units})", eur_formula, str(amount), ""])
        return rows
