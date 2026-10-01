"""remember — send a message to MemorySync's fact extraction.

A user message goes to LLM fact extraction: only the durable facts in it
(preferences, personal details, decisions) become memories, each with its
own id, and the text itself is not stored. Assistant messages are not
stored as memories. The deterministic speaker seed lets the server
recognise a re-run or retried node, so the same message is processed once.
"""

from collections.abc import Generator
from typing import Any, Dict, Tuple

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

#: ``processing_status`` values meaning the message went to fact extraction
#: (``distilling`` = queued, ``completed`` = extracted before the response).
_EXTRACTING = ("distilling", "completed")

#: Why nothing was extracted, per ``processing_status``.
_SKIPPED = {
    "skipped_non_user_turn": "Assistant messages are not stored as memories — nothing was saved.",
    "skipped_low_value": "Nothing worth remembering in this message — nothing was saved.",
    "skipped": "MemorySync monthly quota reached — memory is paused, nothing was saved.",
}


def describe_outcome(result: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """The tool's JSON fields and sentence for one add_turn response.

    Facts are extracted asynchronously and get their own ids, so the
    response never carries the id of a stored memory; this reports what
    happened to the message instead.
    """
    processing = result.get("processing_status")
    processing = processing if isinstance(processing, str) and processing else None
    already = bool(result.get("already_exists")) or processing == "skipped_replay"
    fields: Dict[str, Any] = {
        "processing_status": processing,
        "already_exists": already,
        "request_id": result.get("request_id"),
    }
    skipped = {"status": "skipped", "accepted": False, "stored_as": None}
    if already:
        return {**skipped, **fields}, "Already sent to MemorySync — not processed again."
    if processing in _SKIPPED:
        return {**skipped, **fields}, _SKIPPED[processing]
    if processing == "failed":
        reason = (
            "MemorySync could not extract facts from this message right now — "
            "nothing was saved. Run the node again to retry."
        )
        return (
            {
                "status": "error",
                "http_status": None,
                "reason": reason,
                "accepted": False,
                "stored_as": None,
                **fields,
            },
            reason,
        )
    if processing in _EXTRACTING:
        return (
            {"status": "accepted", "accepted": True, "stored_as": "facts", **fields},
            "Sent to MemorySync for fact extraction — any durable facts in it will be remembered.",
        )
    # A status this plugin does not know: the request was accepted, and
    # nothing more can be said about what was stored.
    return (
        {"status": "accepted", "accepted": True, "stored_as": None, **fields},
        "Sent to MemorySync.",
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
                # The role goes explicitly: user messages are sent to fact
                # extraction, assistant messages are acknowledged and not
                # stored as memories.
                role=role,
                # Deterministic seed: re-running the same node in the same
                # conversation is recognised server-side and processed once
                # (the Mem0 plugin re-extracts duplicates).
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

        fields, sentence = describe_outcome(result)
        yield self.create_json_message(
            {
                **fields,
                "user_id": user_id,
                "role": role,
                "preview": text[:120],
            }
        )
        yield self.create_text_message(sentence)
