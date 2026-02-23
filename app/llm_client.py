from __future__ import annotations

import os
from typing import Optional

from openai import OpenAI
from openai import BadRequestError


class LLMClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5")
        self.client: Optional[OpenAI] = OpenAI(api_key=self.api_key) if self.api_key else None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def complete(self, system_prompt: str, user_prompt: str, api_key_override: str | None = None) -> str:
        active_client = OpenAI(api_key=api_key_override) if api_key_override else self.client
        if not active_client:
            raise RuntimeError("OPENAI_API_KEY is not set and no request-time API key was provided.")

        request_payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            response = active_client.responses.create(**request_payload)
        except BadRequestError as exc:
            # Keep a defensive fallback in case future optional params are rejected.
            message = str(exc)
            if "Unsupported parameter" in message:
                response = active_client.responses.create(
                    model=self.model,
                    input=request_payload["input"],
                )
            else:
                raise

        return response.output_text.strip()
