"""Synchronous MemorySync v1 client for the Dify plugin.

Tools are user-facing workflow nodes, so every call runs under a tight
budget (default 10 s — the Mem0 community plugin hangs a node for 30 s)
and errors surface as structured results, never unhandled exceptions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

PLUGIN_VERSION = "1.0.0"
DEFAULT_BASE_URL = "https://api.memorysync.io"
_USER_AGENT = f"dify-memorysync/{PLUGIN_VERSION}"

#: Namespace used when the key cannot list projects.
FALLBACK_TENANT = "default"

#: One turn beyond this length is truncated before storage.
MAX_TURN_CHARS = 16000

#: Hard per-request budget for tool calls.
TOOL_TIMEOUT_SECONDS = 10.0


class MemorySyncAPIError(Exception):
    """A MemorySync call failed. Carries the status code and server detail."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def resolve_base_url(base_url: Optional[str]) -> str:
    url = (base_url or "").strip() or DEFAULT_BASE_URL
    return url.rstrip("/")


def fnv1a64(value: str) -> str:
    """FNV-1a 64-bit over UTF-16 code units — matches every other
    MemorySync adapter, so identical turns converge on one stored row."""
    prime = 0x100000001B3
    mask = 0xFFFFFFFFFFFFFFFF
    h = 0xCBF29CE484222325
    data = value.encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = data[i] | (data[i + 1] << 8)
        h ^= unit
        h = (h * prime) & mask
    return format(h, "016x")


class MemorySyncClient:
    """Minimal sync client: add_turn, query, recall, forget."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = TOOL_TIMEOUT_SECONDS,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        if not api_key or not str(api_key).strip():
            raise MemorySyncAPIError("A MemorySync API key is required.")
        self._api_key = str(api_key).strip()
        self._base_url = resolve_base_url(base_url)
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._tenant_id: Optional[str] = None

    def close(self) -> None:
        self._http.close()

    def _headers(self, *, end_user_id: Optional[str] = None) -> Dict[str, str]:
        h = {
            "X-API-Key": self._api_key,
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if end_user_id:
            h["X-End-User-ID"] = end_user_id
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        end_user_id: Optional[str] = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            response = self._http.request(
                method,
                url,
                headers=self._headers(end_user_id=end_user_id),
                json=json,
                params=params,
            )
        except httpx.TimeoutException as e:
            raise MemorySyncAPIError(f"Request timed out: {e}", status_code=None) from e
        except httpx.HTTPError as e:
            raise MemorySyncAPIError(f"Network error: {e}", status_code=None) from e

        if response.status_code == 204:
            return None
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text or None
        if response.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else body
            raise MemorySyncAPIError(
                f"{method} {path} failed with HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        return body

    def resolve_tenant_id(self) -> str:
        if self._tenant_id:
            return self._tenant_id
        try:
            projects = self._request("GET", "/org/projects")
        except MemorySyncAPIError as exc:
            if exc.status_code in (401, 403):
                self._tenant_id = FALLBACK_TENANT
                return self._tenant_id
            raise
        first = projects[0] if isinstance(projects, list) and projects else None
        tenant = first.get("tenant_id") if isinstance(first, dict) else None
        if not tenant:
            raise MemorySyncAPIError("Could not determine the tenant for this API key.")
        self._tenant_id = str(tenant)
        return self._tenant_id

    def validate_key(self) -> None:
        """Raise MemorySyncAPIError(401) for an invalid key; pass otherwise.

        200 = full key; 403 = scoped/evaluation key (valid); 401 = invalid.
        """
        try:
            self._request("GET", "/org/projects")
        except MemorySyncAPIError as exc:
            if exc.status_code == 403:
                return
            raise

    def add_turn(
        self,
        *,
        user_id: str,
        text: str,
        speaker: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "tenant_id": self.resolve_tenant_id(),
            "user_id": user_id,
            "source": "dify",
            "text": text,
            "speaker": speaker,
            "sync_embed": False,
        }
        if metadata is not None:
            body["metadata"] = metadata
        return self._request("POST", "/v1/memory/add_turn", json=body) or {}

    def query(self, *, user_id: str, prompt: str, k: int) -> List[Dict[str, Any]]:
        raw = (
            self._request(
                "POST",
                "/v1/memory/query",
                json={
                    "tenant_id": self.resolve_tenant_id(),
                    "user_id": user_id,
                    "prompt": prompt,
                    "k": k,
                },
            )
            or {}
        )
        for key in ("matches", "results", "memories", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                return [v for v in value if isinstance(v, dict)]
        return []

    def recall(self, *, user_id: str, prompt: str, k: int) -> Dict[str, Any]:
        return (
            self._request(
                "POST",
                "/v1/memory/recall",
                json={
                    "tenant_id": self.resolve_tenant_id(),
                    "user_id": user_id,
                    "prompt": prompt,
                    "k": k,
                },
            )
            or {}
        )

    def forget(self, *, user_id: str, memory_id: int) -> Dict[str, Any]:
        return (
            self._request(
                "DELETE",
                "/memory/forget",
                json={"memory_ids": [memory_id]},
                end_user_id=user_id,
            )
            or {}
        )


# ── shared tool helpers ──────────────────────────────────────────────


def match_text(match: Dict[str, Any]) -> Optional[str]:
    # Production /query rows carry content as ``raw_text`` (V1MemoryItem).
    for key in ("value", "text", "raw_text", "memory", "content"):
        value = match.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def match_numeric_id(match: Dict[str, Any]) -> Optional[int]:
    """The row's numeric id. Production sends a string ``memory_id``
    ("m_<n>"); the older numeric ``id`` shape is accepted too."""
    value = match.get("id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    mid = match.get("memory_id")
    if isinstance(mid, int):
        return mid
    if isinstance(mid, str):
        stripped = mid[2:] if mid.startswith("m_") else mid
        if stripped.isdigit():
            return int(stripped)
    return None


def match_score(match: Dict[str, Any]) -> Optional[float]:
    for key in ("score", "similarity", "relevance"):
        value = match.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 4)
    return None


def resolve_user_id(tool: Any, tool_parameters: Dict[str, Any]) -> str:
    """user_id ladder: explicit parameter → Dify runtime user → 'default'.

    The Mem0 community plugin takes user_id ONLY as a free-form parameter
    — forget to wire it and every end user shares one memory partition.
    Dify hands the platform user to the plugin runtime; we use it.
    """
    param = tool_parameters.get("user_id")
    if isinstance(param, str) and param.strip():
        return param.strip()
    runtime_user = getattr(getattr(tool, "runtime", None), "user_id", None)
    if isinstance(runtime_user, str) and runtime_user.strip():
        return runtime_user.strip()
    return "default"


def conversation_scope(tool: Any) -> Optional[str]:
    conversation = getattr(getattr(tool, "session", None), "conversation_id", None)
    if isinstance(conversation, str) and conversation.strip():
        return conversation.strip()
    return None


def error_payload(exc: Exception) -> Dict[str, Any]:
    status = getattr(exc, "status_code", None)
    reason = str(exc)
    if status == 429:
        reason = "MemorySync monthly quota exceeded — memory is paused, the app keeps working."
    return {"status": "error", "http_status": status, "reason": reason}
