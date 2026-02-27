"""Google Drive API: folder management, file upload, sharing."""

from __future__ import annotations

import logging
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from common.config import DRIVE_FOLDER_GLOBAL, DRIVE_FOLDER_RU, get_google_creds
from common.models import Contractor, GlobalContractor

logger = logging.getLogger(__name__)


class DriveGateway:
    """Wraps Google Drive v3 API for folder and file operations."""

    def _service(self):
        return build("drive", "v3", credentials=get_google_creds(), cache_discovery=False)

    def find_subfolder(self, parent_id: str, name: str) -> Optional[str]:
        """Find a subfolder by name inside a parent folder. Returns folder ID or None."""
        drive = self._service()
        escaped_name = name.replace("'", "\\'")
        query = (
            f"'{parent_id}' in parents "
            f"and name = '{escaped_name}' "
            f"and mimeType = 'application/vnd.google-apps.folder' "
            f"and trashed = false"
        )
        result = drive.files().list(
            q=query, fields="files(id, name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        files = result.get("files", [])
        if files:
            logger.debug("Found folder '%s' → %s", name, files[0]["id"])
            return files[0]["id"]
        return None

    def create_folder(self, parent_id: str, name: str) -> str:
        """Create a subfolder inside a parent folder. Returns the new folder ID."""
        drive = self._service()
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        folder = drive.files().create(body=metadata, fields="id", supportsAllDrives=True).execute()
        folder_id = folder["id"]
        logger.info("Created folder '%s' in %s → %s", name, parent_id, folder_id)
        return folder_id

    def ensure_folder(self, parent_id: str, name: str) -> str:
        """Find or create a subfolder. Returns folder ID. Handles race conditions."""
        existing = self.find_subfolder(parent_id, name)
        if existing:
            logger.info("Folder '%s' already exists → %s", name, existing)
            return existing

        logger.info("Folder '%s' not found, creating...", name)
        try:
            return self.create_folder(parent_id, name)
        except Exception as e:
            logger.warning("Creation failed (may already exist): %s. Retrying search...", e)
            existing = self.find_subfolder(parent_id, name)
            if existing:
                logger.info("Folder '%s' now exists (created by another request) → %s", name, existing)
                return existing
            raise

    def upload_file(self, folder_id: str, filename: str, content: bytes, mime_type: str = "application/pdf") -> str:
        """Upload a file to a Drive folder. Returns the file ID."""
        drive = self._service()
        metadata = {
            "name": filename,
            "parents": [folder_id],
        }
        media = MediaInMemoryUpload(content, mimetype=mime_type)
        file = drive.files().create(
            body=metadata, media_body=media, fields="id, webViewLink", supportsAllDrives=True
        ).execute()
        file_id = file["id"]
        logger.info("Uploaded %s to folder %s → %s", filename, folder_id, file_id)
        return file_id

    def make_shareable(self, file_id: str) -> str:
        """Make a file viewable by anyone with the link and return the link."""
        drive = self._service()
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
        file = drive.files().get(fileId=file_id, fields="webViewLink", supportsAllDrives=True).execute()
        return file["webViewLink"]

    def get_contractor_folder(self, contractor: Contractor, month: str) -> str:
        """Get or create the contractor's folder for a given month.

        Folder structure:
          RU:     Invoices-RU/{MM-YYYY}/{ИмяФамилия}/
          Global: Invoices-Global/{YYYY-MM}/{NameSurname}/
        """
        if isinstance(contractor, GlobalContractor):
            root = DRIVE_FOLDER_GLOBAL
            month_folder_name = month  # "2026-01"
            name_folder = contractor.name_en.replace(" ", "")
        else:
            root = DRIVE_FOLDER_RU
            parts = month.split("-")
            month_folder_name = f"{parts[1]}-{parts[0]}" if len(parts) == 2 else month
            name_folder = contractor.display_name.replace(" ", "")

        month_id = self.ensure_folder(root, month_folder_name)
        contractor_id = self.ensure_folder(month_id, name_folder)
        return contractor_id

    def find_file_by_name(self, name: str, parent_id: str) -> Optional[str]:
        """Find a file by exact name in a folder. Returns file ID or None."""
        drive = self._service()
        escaped_name = name.replace("'", "\\'")
        query = (
            f"'{parent_id}' in parents "
            f"and name = '{escaped_name}' "
            f"and trashed = false"
        )
        result = drive.files().list(
            q=query, fields="files(id)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def copy_file(self, file_id: str, name: str, parent_id: str) -> str:
        """Copy a Drive file into a folder with a new name. Returns the new file ID."""
        drive = self._service()
        copy = drive.files().copy(
            fileId=file_id,
            body={"name": name, "parents": [parent_id]},
            supportsAllDrives=True,
        ).execute()
        new_id = copy["id"]
        logger.info("Copied file %s → %s (%s) in folder %s", file_id, new_id, name, parent_id)
        return new_id

    def upload_invoice_pdf(self, contractor: Contractor, month: str, filename: str, pdf_bytes: bytes) -> str:
        """Upload an invoice PDF to the appropriate folder structure. Returns a shareable link."""
        folder_id = self.get_contractor_folder(contractor, month)
        file_id = self.upload_file(folder_id, filename, pdf_bytes)
        return self.make_shareable(file_id)
