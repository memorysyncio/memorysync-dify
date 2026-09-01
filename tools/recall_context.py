"""recall_context — a prompt-ready memory block for the LLM node."""

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.api_client import (
    MemorySyncAPIError,
    MemorySyncClient,
    error_payload,
    match_text,
    resolve_user_id,
)


class RecallContextTool(Tool):
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

        top_k = tool_parameters.get("top_k")
        try:
            top_k = max(1, min(int(top_k), 25)) if top_k is not None else 5
        except (TypeError, ValueError):
            top_k = 5

        user_id = resolve_user_id(self, tool_parameters)
        client = MemorySyncClient(
            api_key=self.runtime.credentials.get("api_key", ""),
            base_url=self.runtime.credentials.get("base_url"),
        )
        try:
            raw = client.recall(user_id=user_id, prompt=query, k=top_k)
            context = None
            for key in ("context", "context_block", "text"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    context = value.strip()
                    break
            if context is None:
                # Fall back to a formatted block from plain search results.
                matches = client.query(user_id=user_id, prompt=query, k=top_k)
                lines = []
                for match in matches[:top_k]:
                    text = match_text(match)
                    if text:
                        lines.append(f"- {text}")
                context = (
                    "Relevant long-term memories about this user:\n" + "\n".join(lines)
                    if lines
                    else ""
                )
        except MemorySyncAPIError as exc:
            yield self.create_json_message(error_payload(exc))
            yield self.create_text_message(f"MemorySync recall unavailable: {exc}")
            return
        finally:
            client.close()

        yield self.create_variable_message("context", context)
        yield self.create_json_message(
            {"status": "ok", "user_id": user_id, "context": context}
        )
        yield self.create_text_message(context if context else "No relevant memories yet.")
