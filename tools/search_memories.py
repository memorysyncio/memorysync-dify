"""search_memories — scored JSON results with tolerant parsing."""

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.api_client import (
    MemorySyncAPIError,
    MemorySyncClient,
    error_payload,
    match_numeric_id,
    match_score,
    match_text,
    resolve_user_id,
)


class SearchMemoriesTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        query = str(tool_parameters.get("query") or "").strip()
        if not query:
            yield self.create_json_message(
                {"status": "error", "reason": "query is required"}
            )
            yield self.create_text_message("MemorySync: query is required.")
            return

        limit = tool_parameters.get("limit")
        try:
            limit = max(1, min(int(limit), 25)) if limit is not None else 5
        except (TypeError, ValueError):
            limit = 5

        user_id = resolve_user_id(self, tool_parameters)
        client = MemorySyncClient(
            api_key=self.runtime.credentials.get("api_key", ""),
            base_url=self.runtime.credentials.get("base_url"),
        )
        try:
            matches = client.query(user_id=user_id, prompt=query, k=limit)
        except MemorySyncAPIError as exc:
            yield self.create_json_message(error_payload(exc))
            yield self.create_text_message(f"MemorySync search unavailable: {exc}")
            return
        finally:
            client.close()

        memories = []
        for match in matches[:limit]:
            text = match_text(match)
            if text is None:
                continue  # tolerant: never KeyError on schema drift
            memories.append(
                {
                    "id": match_numeric_id(match),
                    "memory": text,
                    "score": match_score(match),
                    "created_at": match.get("created_at"),
                }
            )

        yield self.create_json_message(
            {
                "status": "ok",
                "user_id": user_id,
                "count": len(memories),
                "memories": memories,
            }
        )
        summary = "\n".join(f"- {m['memory']}" for m in memories) or "No memories found."
        yield self.create_text_message(summary)
