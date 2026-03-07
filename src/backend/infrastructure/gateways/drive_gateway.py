"""Google Drive API: folder management, file upload, sharing."""

from __future__ import annotations

import logging

from googleapiclient.http import MediaInMemoryUpload

from backend.commands.invoice.service import get_invoice_folder_path
from backend.infrastructure.gateways.google_auth import build_google_service

logger = logging.getLogger(__name__)


class DriveGateway:
    """Wraps Google Drive v3 API for folder and file operations."""

    def _service(self):
        return build_google_service("drive", "v3")

    def find_subfolder(self, parent_id: str, name: str) -> str | None:
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

    def get_contractor_folder(self, parent_folder_id: str, month_folder: str, contractor_folder: str) -> str:
        """Get or create nested folder structure: parent/month/contractor. Returns folder ID."""
        month_id = self.ensure_folder(parent_folder_id, month_folder)
        return self.ensure_folder(month_id, contractor_folder)

    def find_file_by_name(self, name: str, parent_id: str) -> str | None:
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

    def upload_invoice_pdf(self, contractor, month: str, filename: str, pdf_bytes: bytes) -> str:
        """Upload an invoice PDF to the appropriate folder structure. Returns a shareable link."""
        parent, month_folder, name_folder = get_invoice_folder_path(contractor, month)
        folder_id = self.get_contractor_folder(parent, month_folder, name_folder)
        file_id = self.upload_file(folder_id, filename, pdf_bytes)
        return self.make_shareable(file_id)
