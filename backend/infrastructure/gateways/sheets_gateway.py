"""Low-level Google Sheets API v4 wrapper."""

from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build

from common.config import get_google_creds


class SheetsGateway:
    """Thin wrapper around the Google Sheets API v4."""

    def _service(self):
        return build("sheets", "v4", credentials=get_google_creds(), cache_discovery=False)

    def read(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        """Read a range. Returns list of rows (each row a list of strings)."""
        result = (
            self._service()
            .spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_name)
            .execute()
        )
        return result.get("values", [])

    def write(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Write values to a range."""
        body = {"values": values}
        return (
            self._service()
            .spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute()
        )

    def append(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Append rows to the end of a range."""
        body = {"values": values}
        return (
            self._service()
            .spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute()
        )

    def clear(self, spreadsheet_id: str, range_name: str) -> dict:
        """Clear cell contents in a range (preserves formatting)."""
        return (
            self._service()
            .spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheet_id, range=range_name, body={})
            .execute()
        )

    def read_as_dicts(
        self, spreadsheet_id: str, range_name: str
    ) -> list[dict[str, str]]:
        """Read a range and return list of dicts using first row as headers."""
        rows = self.read(spreadsheet_id, range_name)
        if len(rows) < 2:
            return []
        headers = [h.strip().lower() for h in rows[0]]
        result = []
        for row in rows[1:]:
            padded = row + [""] * (len(headers) - len(row))
            result.append({h: padded[i] for i, h in enumerate(headers)})
        return result
