from __future__ import annotations

import os
from typing import Optional

from openai import BadRequestError
from openai import OpenAI


class LLMClient:
    def __init__(self) -> None:
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")

        self.default_provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.default_model = os.getenv("OPENAI_MODEL", "gpt-5")
        self.default_gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        self.client: Optional[OpenAI] = OpenAI(api_key=self.openai_api_key) if self.openai_api_key else None

    @property
    def enabled(self) -> bool:
        return self.openai_api_key is not None or self.gemini_api_key is not None

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        api_key_override: str | None = None,
        provider_override: str | None = None,
        model_override: str | None = None,
    ) -> str:
        provider = (provider_override or self.default_provider or "openai").lower()
        if provider == "gemini":
            return self._complete_gemini(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key_override=api_key_override,
                model_override=model_override,
            )
        return self._complete_openai(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key_override=api_key_override,
            model_override=model_override,
        )

    def _complete_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        api_key_override: str | None = None,
        model_override: str | None = None,
    ) -> str:
        active_key = api_key_override or self.openai_api_key
        if not active_key:
            raise RuntimeError("No OpenAI API key available for OpenAI provider.")
        active_client = OpenAI(api_key=active_key)
        model = model_override or self.default_model

        request_payload = {
            "model": model,
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
                    model=model,
                    input=request_payload["input"],
                )
            else:
                raise

        return response.output_text.strip()

    def _complete_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        api_key_override: str | None = None,
        model_override: str | None = None,
    ) -> str:
        active_key = api_key_override or self.gemini_api_key
        if not active_key:
            raise RuntimeError("No Gemini API key available for Gemini provider.")

        model = model_override or self.default_gemini_model
        gemini_client = OpenAI(
            api_key=active_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

        response = gemini_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content if response.choices else ""
        return (content or "").strip()
