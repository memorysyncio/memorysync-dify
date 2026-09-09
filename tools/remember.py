"""remember — persist a turn/fact with idempotent seeds."""

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.api_client import (
    MAX_TURN_CHARS,
    MemorySyncAPIError,
    MemorySyncClient,
    conversation_scope,
    error_payload,
    fnv1a64,
    resolve_user_id,
)


class RememberTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        content = str(tool_parameters.get("content") or "").strip()
        if not content:
            yield self.create_json_message(
                {"status": "error", "reason": "content is required"}
            )
            yield self.create_text_message("MemorySync: content is required.")
            return

        role = str(tool_parameters.get("role") or "user").strip().lower()
        if role not in ("user", "assistant"):
            role = "user"

        user_id = resolve_user_id(self, tool_parameters)
        conversation = conversation_scope(self) or "default"
        session_scope = f"dify::{conversation}"
        text = content[:MAX_TURN_CHARS]

        client = MemorySyncClient(
            api_key=self.runtime.credentials.get("api_key", ""),
            base_url=self.runtime.credentials.get("base_url"),
        )
        try:
            result = client.add_turn(
                user_id=user_id,
                text=text,
                # Deterministic seed: retrying the same node run converges
                # on ONE stored row (the Mem0 plugin re-extracts duplicates).
                speaker=f"{role}@{session_scope}#h{fnv1a64(text)}",
                metadata={
                    "surface": "dify",
                    "session_id": conversation,
                    "role": role,
                },
            )
        except MemorySyncAPIError as exc:
            yield self.create_json_message(error_payload(exc))
            yield self.create_text_message(f"MemorySync could not store this: {exc}")
            return
        finally:
            client.close()

        already = bool(result.get("already_exists"))
        yield self.create_json_message(
            {
                "status": "stored",
                "user_id": user_id,
                "already_exists": already,
                "preview": text[:120],
            }
        )
        yield self.create_text_message(
            "Already remembered." if already else "Remembered."
        )
