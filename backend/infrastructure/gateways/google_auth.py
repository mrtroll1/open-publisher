"""Shared Google API service builder."""

from googleapiclient.discovery import build

from common.config import get_google_creds


def build_google_service(api: str, version: str):
    return build(api, version, credentials=get_google_creds(), cache_discovery=False)
