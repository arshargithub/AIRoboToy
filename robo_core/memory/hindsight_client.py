"""
HTTP client for the Vectorize Hindsight memory API.

Wraps Retain (store conversations) and Recall (retrieve memories)
against a Hindsight instance running behind an ALB on AWS.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds


class HindsightClient:
    """Thin wrapper around Hindsight REST API for Retain and Recall."""

    def __init__(self, base_url: str, bank_id: str = "johnny-robot"):
        self.base_url = base_url.rstrip("/")
        self.bank_id = bank_id
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Retain -- store a conversation turn
    # ------------------------------------------------------------------

    def retain(
        self,
        content: str,
        context: str = "robot conversation",
        tags: Optional[List[str]] = None,
        timestamp: Optional[str] = None,
        document_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Ingest content into Hindsight for fact extraction.

        Args:
            content: The conversation text to retain.
            context: Short label (e.g. "robot conversation").
            tags: Visibility-scoping tags (e.g. ["user:alice"]).
            timestamp: ISO 8601 timestamp.  Defaults to now.
            document_id: Idempotency key.  Omit for unique per-call.
            metadata: Arbitrary key-value pairs stored with each memory.

        Returns:
            Hindsight API response dict.
        """
        url = f"{self.base_url}/v1/default/banks/{self.bank_id}/memories"
        payload: Dict[str, Any] = {"content": content, "context": context}

        if tags:
            payload["tags"] = tags
        if timestamp:
            payload["timestamp"] = timestamp
        else:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        if document_id:
            payload["document_id"] = document_id
        if metadata:
            payload["metadata"] = metadata

        try:
            resp = self._session.post(url, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "Hindsight retain OK (bank=%s, tags=%s)", self.bank_id, tags
            )
            return data
        except requests.RequestException:
            logger.exception("Hindsight retain failed")
            return {"success": False, "error": "request_failed"}

    # ------------------------------------------------------------------
    # Recall -- retrieve relevant memories
    # ------------------------------------------------------------------

    def recall(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Retrieve memories matching a query.

        Args:
            query: Natural-language search query.
            tags: Filter memories by tags (e.g. ["user:alice"]).
            limit: Maximum memories to return.

        Returns:
            List of memory dicts, or empty list on failure.
        """
        url = f"{self.base_url}/v1/default/banks/{self.bank_id}/recall"
        payload: Dict[str, Any] = {"q": query, "limit": limit}
        if tags:
            payload["tags"] = tags

        try:
            resp = self._session.post(url, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            memories = data.get("memories", data.get("results", []))
            logger.info(
                "Hindsight recall OK: %d memories (bank=%s, tags=%s)",
                len(memories),
                self.bank_id,
                tags,
            )
            return memories
        except requests.RequestException:
            logger.exception("Hindsight recall failed")
            return []

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Check if the Hindsight API is reachable."""
        try:
            resp = self._session.get(
                f"{self.base_url}/health", timeout=5
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False
