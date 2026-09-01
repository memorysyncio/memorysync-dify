"""forget_memory — delete ONE memory, loudly.

There is deliberately NO delete-everything tool: a model-reachable
account wipe is a data-loss foot-gun (the community Mem0 fork exposes
delete_all_memories to the LLM).
"""

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.api_client import (
    MemorySyncAPIError,
    MemorySyncClient,
    error_payload,
    resolve_user_id,
)


class ForgetMemoryTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        raw_id = str(tool_parameters.get("memory_id") or "").strip()
        if not raw_id or not raw_id.lstrip("-").isdigit():
            yield self.create_json_message(
                {
                    "status": "error",
                    "reason": "memory_id must be the numeric id of one memory "
                    "(find it with search_memories)",
                }
            )
            yield self.create_text_message(
                "MemorySync: memory_id must be a numeric id from Search Memories."
            )
            return

        user_id = resolve_user_id(self, tool_parameters)
        client = MemorySyncClient(
            api_key=self.runtime.credentials.get("api_key", ""),
            base_url=self.runtime.credentials.get("base_url"),
        )
        try:
            client.forget(user_id=user_id, memory_id=int(raw_id))
        except MemorySyncAPIError as exc:
            # Loud: a delete that did not happen must never look deleted.
            yield self.create_json_message(error_payload(exc))
            yield self.create_text_message(f"MemorySync could NOT delete: {exc}")
            return
        finally:
            client.close()

        yield self.create_json_message(
            {"status": "deleted", "memory_id": int(raw_id), "user_id": user_id}
        )
        yield self.create_text_message(f"Memory {raw_id} deleted.")
