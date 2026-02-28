"""Republic API gateway — content API + support user lookup."""

from __future__ import annotations

import logging
import time

import requests

from common.config import CONTENT_API_URL, REPUBLIC_API_URL, REPUBLIC_SUPPORT_API_KEY
from common.models import ArticleEntry, Contractor

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class RepublicGateway:
    """Wraps Republic API: content endpoints and support endpoints."""

    # ------------------------------------------------------------------
    #  Content API (articles)
    # ------------------------------------------------------------------

    @staticmethod
    def _api_get(url: str, params: dict, label: str) -> list[int]:
        """Make a GET request to the content API and return post IDs.

        Retries up to MAX_RETRIES times on transient errors (5xx, timeouts).
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(
                    url, params=params, timeout=15,
                    headers={"Accept": "application/json"},
                )
                logger.info("Content API %s params=%s → HTTP %s (%d bytes)",
                             url, params, resp.status_code, len(resp.content))
                if resp.status_code >= 500:
                    logger.warning("Content API %s for %s (attempt %d/%d)",
                                   resp.status_code, label, attempt, MAX_RETRIES)
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY)
                        continue
                    logger.error("Content API HTTP %s for %s after %d attempts (body=%s)",
                                 resp.status_code, label, MAX_RETRIES, resp.text[:500])
                    return []
                resp.raise_for_status()
                body = resp.json()
                post_ids = body.get("$data") or body.get("data") or []
                if not post_ids:
                    logger.warning("Content API returned empty data for %s: %s", label, body)
                return post_ids
            except requests.HTTPError:
                logger.error("Content API HTTP %s for %s (body=%s)",
                             resp.status_code, label, resp.text[:500])
                return []
            except (requests.ConnectionError, requests.Timeout) as e:
                logger.warning("Content API %s for %s (attempt %d/%d): %s",
                               type(e).__name__, label, attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                logger.error("Content API error for %s after %d attempts: %s",
                             label, MAX_RETRIES, e)
                return []
            except Exception as e:
                logger.error("Content API error for %s: %s", label, e)
                return []
        return []

    def fetch_articles(self, contractor: Contractor, month: str) -> list[ArticleEntry]:
        """Fetch article IDs for a contractor from the content API."""
        mag_aliases = [a.strip() for a in contractor.mags.split(",") if a.strip()]

        if mag_aliases:
            url = f"{CONTENT_API_URL}/posts/by-magazine"
            params = {"magazines": ",".join(mag_aliases), "month": month}
            label = f"{contractor.display_name} (mags: {mag_aliases})"
            post_ids = self._api_get(url, params, label)
        else:
            names = list(contractor.aliases)
            if contractor.display_name and contractor.display_name not in names:
                names.append(contractor.display_name)
            if not names:
                logger.warning("Contractor %s has no aliases or mag aliases for API lookup", contractor.id)
                return []
            seen = set()
            post_ids = []
            url = f"{CONTENT_API_URL}/posts/by-author"
            for name in names:
                params = {"author": name, "month": month}
                label = f"{contractor.display_name} (author: {name})"
                ids = self._api_get(url, params, label)
                for pid in ids:
                    if pid not in seen:
                        seen.add(pid)
                        post_ids.append(pid)

        return [
            ArticleEntry(article_id=str(pid), role_code=contractor.role_code)
            for pid in post_ids
        ]

    def fetch_articles_by_name(self, author: str, month: str) -> list[int]:
        """Check if an author name has any articles for the given month."""
        url = f"{CONTENT_API_URL}/posts/by-author"
        return self._api_get(url, {"author": author, "month": month}, author)

    def fetch_published_authors(self, month: str) -> list[dict[str, str | int]]:
        """Fetch all authors who published in the given month.

        Returns list of {"author": "Name", "post_count": N} dicts,
        ordered by post_count descending.
        """
        url = f"{CONTENT_API_URL}/posts/authors"
        try:
            resp = requests.get(
                url, params={"month": month}, timeout=15,
                headers={"Accept": "application/json"},
            )
            logger.info("Content API %s month=%s → HTTP %s", url, month, resp.status_code)
            resp.raise_for_status()
            body = resp.json()
            rows = body.get("$data") or body.get("data") or []
            return [
                {"author": str(r["author"]), "post_count": int(r["post_count"])}
                for r in rows
                if isinstance(r, dict) and "author" in r
            ]
        except Exception as e:
            logger.error("Content API error for /posts/authors: %s", e)
            return []

    # ------------------------------------------------------------------
    #  Support API (user lookup)
    # ------------------------------------------------------------------

    def get_user_by_email(self, email: str) -> dict | None:
        """Look up a Republic user by email. Returns user dict or None."""
        try:
            resp = requests.get(
                f"{REPUBLIC_API_URL}/support/user-by-email",
                params={"email": email},
                headers={"X-Api-Key": REPUBLIC_SUPPORT_API_KEY},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("user")
        except Exception as e:
            logger.error("Republic user lookup failed for %s: %s", email, e)
            return None
