"""Google Docs API: template copy, text replacement, table insertion, PDF export."""

from __future__ import annotations

import io
import logging
from datetime import date

from googleapiclient.http import MediaIoBaseDownload

from backend.infrastructure.gateways.google_auth import build_google_service
from common.models import ArticleEntry

logger = logging.getLogger(__name__)


class DocsGateway:
    """Wraps Google Docs v1 and Drive v3 APIs for document generation."""

    def _docs_service(self):
        return build_google_service("docs", "v1")

    def _drive_service(self):
        return build_google_service("drive", "v3")

    def copy_template(self, template_id: str, title: str, folder_id: str) -> str:
        """Copy a Google Doc template into a specific folder. Returns the new document ID."""
        drive = self._drive_service()
        copy = drive.files().copy(
            fileId=template_id, body={"name": title, "parents": [folder_id]}, supportsAllDrives=True
        ).execute()
        doc_id = copy["id"]
        logger.info("Copied template %s → %s (%s) in folder %s", template_id, doc_id, title, folder_id)
        return doc_id

    def replace_text(self, doc_id: str, replacements: dict[str, str]) -> None:
        """Batch find-and-replace placeholders in a Google Doc."""
        docs = self._docs_service()
        requests = []
        for placeholder, value in replacements.items():
            requests.append({
                "replaceAllText": {
                    "containsText": {"text": placeholder, "matchCase": True},
                    "replaceText": value,
                }
            })
        if requests:
            docs.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests}
            ).execute()

    def insert_articles_table(
        self, doc_id: str, placeholder: str, articles: list[ArticleEntry],
        column_headers: list[str], third_col_values: str | list[str],
    ) -> None:
        """Replace placeholder with a table containing article data."""
        docs = self._docs_service()

        para_start = self._delete_placeholder_paragraph(docs, doc_id, placeholder)
        if para_start is None:
            return

        num_rows = len(articles) + 1  # +1 for header
        self._insert_empty_table(docs, doc_id, para_start, num_rows)

        doc = docs.documents().get(documentId=doc_id).execute()
        cell_idx = self._collect_cell_indices(doc, para_start)
        if cell_idx is None:
            return

        data = self._build_table_data(column_headers, articles, third_col_values)
        text_requests = self._build_fill_requests(data, cell_idx)

        docs.documents().batchUpdate(
            documentId=doc_id, body={"requests": text_requests}
        ).execute()
        logger.info("Inserted articles table with %d rows into doc %s", len(articles), doc_id)

    def _delete_placeholder_paragraph(self, docs, doc_id: str, placeholder: str) -> int | None:
        """Find and delete the paragraph containing placeholder. Returns para startIndex."""
        doc = docs.documents().get(documentId=doc_id).execute()
        para_start = self._find_placeholder_index(doc, placeholder)
        if para_start is None:
            logger.warning("Placeholder '%s' not found, skipping table insertion", placeholder)
            return None

        for element in doc["body"]["content"]:
            if element.get("startIndex") == para_start:
                para_end = element["endIndex"]
                break
        else:
            logger.warning("Could not determine paragraph end for placeholder")
            return None

        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"deleteContentRange": {"range": {"startIndex": para_start, "endIndex": para_end}}}
        ]}).execute()
        return para_start

    @staticmethod
    def _insert_empty_table(docs, doc_id: str, index: int, num_rows: int) -> None:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"insertTable": {"rows": num_rows, "columns": 3, "location": {"index": index}}}
        ]}).execute()

    @staticmethod
    def _collect_cell_indices(doc: dict, min_start: int) -> list[list[int]] | None:
        """Find the first table at/after min_start and return cell start indices."""
        table_element = None
        for element in doc["body"]["content"]:
            if "table" in element and element["startIndex"] >= min_start:
                table_element = element
                break
        if table_element is None:
            logger.error("Inserted table not found in document")
            return None

        cell_idx: list[list[int]] = []
        for row in table_element["table"]["tableRows"]:
            cell_idx.append([cell["content"][0]["startIndex"] for cell in row["tableCells"]])
        return cell_idx

    @staticmethod
    def _build_table_data(
        column_headers: list[str], articles: list[ArticleEntry],
        third_col_values: str | list[str],
    ) -> list[list[str]]:
        data: list[list[str]] = [column_headers]
        if isinstance(third_col_values, str):
            third_col_values = [third_col_values] * len(articles)
        for i, (article, third_val) in enumerate(zip(articles, third_col_values), 1):
            article_code = f"{article.article_id} - {article.role_code.value}"
            data.append([str(i), article_code, third_val])
        return data

    @staticmethod
    def _build_fill_requests(data: list[list[str]], cell_idx: list[list[int]]) -> list[dict]:
        # Bottom-right to top-left so indices stay valid
        requests = []
        for row in range(len(data) - 1, -1, -1):
            for col in range(2, -1, -1):
                requests.append({
                    "insertText": {
                        "text": data[row][col],
                        "location": {"index": cell_idx[row][col]},
                    }
                })
        return requests

    def export_pdf(self, doc_id: str) -> bytes:
        """Export a Google Doc as PDF bytes."""
        drive = self._drive_service()
        request = drive.files().export_media(fileId=doc_id, mimeType="application/pdf")
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    @staticmethod
    def _find_placeholder_index(doc: dict, placeholder: str) -> int | None:
        """Find the startIndex of the paragraph containing the placeholder text."""
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" not in element:
                continue
            for run in element["paragraph"].get("elements", []):
                if placeholder in run.get("textRun", {}).get("content", ""):
                    return element["startIndex"]
        return None

    @staticmethod
    def format_date_ru(d: date) -> str:
        """Format date as '«15» января 2026 г.'"""
        months_ru = [
            "", "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря",
        ]
        return f"«{d.day:02d}» {months_ru[d.month]} {d.year} г."

    @staticmethod
    def format_date_en(d: date) -> str:
        """Format date as 'DD.MM.YYYY'."""
        return d.strftime("%d.%m.%Y")
