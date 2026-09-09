"""MemorySync tool provider: credential validation."""

from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from utils.api_client import MemorySyncAPIError, MemorySyncClient


class MemorySyncProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        api_key = str(credentials.get("api_key") or "").strip()
        if not api_key:
            raise ToolProviderCredentialValidationError(
                "MemorySync API key is required (get one at app.memorysync.io)."
            )
        client = MemorySyncClient(
            api_key=api_key, base_url=credentials.get("base_url")
        )
        try:
            # 200 = full key, 403 = scoped/evaluation key (both valid);
            # 401 = invalid key; anything else (network, 5xx) also fails
            # validation so the user retries instead of saving a broken setup.
            client.validate_key()
        except MemorySyncAPIError as exc:
            if exc.status_code == 401:
                raise ToolProviderCredentialValidationError(
                    "Invalid MemorySync API key."
                ) from exc
            raise ToolProviderCredentialValidationError(
                f"Could not verify the MemorySync API key: {exc}"
            ) from exc
        finally:
            client.close()
