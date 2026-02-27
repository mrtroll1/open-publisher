"""Airtable API gateway — upload expense records."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from pyairtable import Api

from common.config import AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME, AIRTABLE_TOKEN
from common.models import AirtableExpense

logger = logging.getLogger(__name__)


class AirtableGateway:
    """Wraps the Airtable API for expense record uploads."""

    def upload_expenses(self, expenses: list[AirtableExpense]) -> int:
        """Upload expense records to Airtable. Returns number of records uploaded."""
        if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
            logger.error("Airtable credentials not configured")
            return 0

        api = Api(AIRTABLE_TOKEN)
        table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

        today = datetime.now().strftime("%Y-%m-%d")

        records = []
        for exp in expenses:
            contractor = f'"{exp.contractor}"' if "," in exp.contractor else exp.contractor
            unit = f'"{exp.unit}"' if "," in exp.unit else exp.unit
            entity = f'"{exp.entity}"' if "," in exp.entity else exp.entity
            group = f'"{exp.group}"' if "," in exp.group else exp.group

            fields = {
                "payed": exp.payed,
                "amount rub": float(exp.amount_rub),
                "contractor": contractor,
                "unit": unit,
                "entity": entity,
                "description": exp.description,
                "group": group,
                "crated": today,
            }
            if exp.splited:
                fields["splited"] = exp.splited
            if exp.comment:
                fields["comment"] = exp.comment
            records.append({"fields": fields})

        created = 0
        for i in range(0, len(records), 10):
            batch = records[i : i + 10]
            try:
                table.batch_create([r["fields"] for r in batch], typecast=True)
                created += len(batch)
                time.sleep(0.2)
            except Exception as e:
                logger.error("Airtable batch upload failed at %d: %s", i, e)

        logger.info("Uploaded %d/%d records to Airtable", created, len(records))
        return created
