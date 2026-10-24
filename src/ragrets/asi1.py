"""ASI:One client using the existing RAGrets tool and validation workflow."""

from typing import Any

import requests

from .groq import (
    GROQ_JSON_SCHEMA_MODELS,
    INVESTIGATION_JSON_SCHEMA,
    GroqAPIError,
    GroqClient,
)

ASI_ONE_CHAT_COMPLETIONS_URL = "https://api.asi1.ai/v1/chat/completions"
ASI_ONE_JSON_SCHEMA_MODELS = {"asi1", "asi1-mini", "asi1-ultra"}


class ASI1Client(GroqClient):
    """OpenAI-compatible ASI:One client preserving RAGrets' read-only tools."""

    def _request_message(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        tools: list[dict] | None = None,
    ) -> dict:
        if not self.configured:
            raise GroqAPIError(
                "ASI:One is not configured. Set ASI_ONE_API_KEY (or RAGRETS_LLM_API_KEY)."
            )

        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if json_mode:
            if self.model in ASI_ONE_JSON_SCHEMA_MODELS:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": INVESTIGATION_JSON_SCHEMA,
                }
            else:
                payload["response_format"] = {"type": "json_object"}
        if tools is not None:
            payload["tools"] = tools

        try:
            response = requests.post(
                ASI_ONE_CHAT_COMPLETIONS_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise GroqAPIError("ASI:One request timed out. Please try again.") from exc
        except requests.RequestException as exc:
            raise GroqAPIError(
                "Could not reach ASI:One. Check the network connection and try again."
            ) from exc

        if response.status_code == 401:
            raise GroqAPIError("ASI:One rejected the configured API key. Check ASI_ONE_API_KEY.")
        if response.status_code == 402:
            raise GroqAPIError("ASI:One reports insufficient API credits or billing setup.")
        if response.status_code == 429:
            raise GroqAPIError("ASI:One rate limit reached. Wait briefly and try again.")
        if response.status_code >= 500:
            raise GroqAPIError("ASI:One is temporarily unavailable. Please try again later.")
        if not response.ok:
            detail = ""
            try:
                error_body = response.json()
                error = error_body.get("error", {})
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")
            except (ValueError, AttributeError):
                pass
            suffix = f" Details: {detail[:300]}" if detail else ""
            raise GroqAPIError(f"ASI:One request failed with HTTP {response.status_code}.{suffix}")

        try:
            body = response.json()
            message = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GroqAPIError("ASI:One returned an invalid response.") from exc
        if not isinstance(message, dict):
            raise GroqAPIError("ASI:One returned an invalid response.")
        return message
