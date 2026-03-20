"""Airtable API gateway — upload expense records."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from pyairtable import Api

from backend.config import AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME, AIRTABLE_TOKEN
from backend.models import AirtableExpense

logger = logging.getLogger(__name__)


class AirtableGateway:
    """Wraps the Airtable API for expense record uploads."""

    def upload_expenses(self, expenses: list[AirtableExpense]) -> int:
        if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
            logger.error("Airtable credentials not configured")
            return 0
        table = Api(AIRTABLE_TOKEN).table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)
        records = [_expense_to_fields(exp) for exp in expenses]
        created = _batch_upload(table, records)
        logger.info("Uploaded %d/%d records to Airtable", created, len(records))
        return created


def _expense_to_fields(exp: AirtableExpense) -> dict:
    fields = {
        "payed": exp.payed,
        "amount rub": float(exp.amount_rub),
        "contractor": exp.contractor,
        "unit": exp.unit, "entity": exp.entity,
        "description": exp.description,
        "group": exp.group,
        "crated": datetime.now().strftime("%Y-%m-%d"),
    }
    if exp.splited:
        fields["splited"] = exp.splited
    if exp.comment:
        fields["comment"] = exp.comment
    return fields


def _batch_upload(table, records: list[dict]) -> int:
    created = 0
    for i in range(0, len(records), 10):
        batch = records[i : i + 10]
        table.batch_create(batch, typecast=True)
        created += len(batch)
        time.sleep(0.2)
    return created
