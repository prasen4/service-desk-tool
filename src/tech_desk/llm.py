from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI

from tech_desk.config import get_settings
from tech_desk.pricing import PROVIDERS, provider_for_model

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _build_http_client() -> httpx.Client:
    """Direct connection — ignore system proxy env vars that break httpx."""
    return httpx.Client(
        timeout=httpx.Timeout(60.0, connect=15.0),
        trust_env=False,
        follow_redirects=True,
    )


def _resolve_provider(provider: str | None, model: str | None) -> str:
    """Determine provider: explicit > inferred from model > configured default."""
    if provider and provider in PROVIDERS:
        return provider
    inferred = provider_for_model(model or "")
    if inferred:
        return inferred
    settings = get_settings()
    return settings.llm_provider if settings.llm_provider in PROVIDERS else "openai"


@dataclass
class ValidationResult:
    ok: bool
    message: str = ""


class LLMClient:
    """Multi-provider LLM client (OpenAI-compatible + Anthropic) for research and reporting."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        api_version: str | None = None,
    ):
        settings = get_settings()
        self.model = model or settings.openai_model
        self.provider = _resolve_provider(provider, self.model)
        self.sdk = PROVIDERS[self.provider]["sdk"]
        key = (api_key or settings.openai_api_key or "").strip()
        self.api_key = key
        self.usage = {"input": 0, "output": 0, "calls": 0}
        # analyze_result() calls run concurrently across worker threads during
        # research runs, and this client instance is shared across them.
        self._usage_lock = threading.Lock()
        # Newer models (e.g. GPT-5 family, o-series reasoning models) reject the
        # legacy `max_tokens` param and require `max_completion_tokens` instead.
        # Detected lazily on first 400 and cached so we don't eat an extra
        # round-trip on every subsequent call.
        self._needs_max_completion_tokens = False
        self._http_client = _build_http_client()

        default_base = PROVIDERS[self.provider]["base_url"] or settings.openai_base_url
        resolved_base = (base_url or settings.openai_base_url or default_base).strip()

        if self.sdk == "anthropic":
            from anthropic import Anthropic

            self._client = Anthropic(
                api_key=key,
                timeout=60.0,
                max_retries=2,
                http_client=self._http_client,
            )
        elif self.sdk == "azure_openai":
            from openai import AzureOpenAI

            self.api_version = (api_version or settings.azure_openai_api_version or "2024-10-21").strip()
            self._client = AzureOpenAI(
                api_key=key,
                azure_endpoint=resolved_base.rstrip("/"),
                api_version=self.api_version,
                timeout=60.0,
                max_retries=2,
                http_client=self._http_client,
            )
        else:
            self._client = OpenAI(
                api_key=key,
                base_url=(resolved_base or default_base).rstrip("/"),
                timeout=60.0,
                max_retries=2,
                http_client=self._http_client,
            )

    def close(self) -> None:
        try:
            self._http_client.close()
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        if self.sdk == "anthropic":
            return self._chat_anthropic(
                system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
            )
        return self._chat_openai(
            system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
        )

    def _chat_openai(
        self, system_prompt: str, user_prompt: str, *, temperature: float, max_tokens: int, json_mode: bool
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        # Read once up front: this is what THIS call actually sends, and is what
        # the retry decision below must key off. Do not re-check the shared
        # self._needs_max_completion_tokens flag inside the except block — other
        # concurrent calls on this same instance may flip it between when this
        # call started and when its own request fails, which would incorrectly
        # skip this call's own retry (a real race observed in production with
        # concurrent analysis workers).
        token_param = "max_completion_tokens" if self._needs_max_completion_tokens else "max_tokens"
        kwargs[token_param] = max_tokens

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if (
                token_param == "max_tokens"
                and "max_tokens" in str(exc)
                and "max_completion_tokens" in str(exc)
            ):
                self._needs_max_completion_tokens = True
                kwargs.pop("max_tokens", None)
                kwargs["max_completion_tokens"] = max_tokens
                response = self._client.chat.completions.create(**kwargs)
            else:
                raise

        self._record_usage(getattr(response, "usage", None), "prompt_tokens", "completion_tokens")
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned empty response")
        return content

    def _chat_anthropic(
        self, system_prompt: str, user_prompt: str, *, temperature: float, max_tokens: int, json_mode: bool
    ) -> str:
        system = system_prompt
        if json_mode:
            system = (
                system_prompt
                + "\n\nRespond with a single valid JSON object only. "
                "Do not include markdown code fences or any explanatory text."
            )
        message = self._client.messages.create(
            model=self.model,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record_usage(getattr(message, "usage", None), "input_tokens", "output_tokens")
        parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
        content = "".join(parts).strip()
        if not content:
            raise RuntimeError("LLM returned empty response")
        if json_mode:
            content = _JSON_FENCE.sub("", content).strip()
        return content

    def _record_usage(self, usage: Any, in_attr: str, out_attr: str) -> None:
        if usage is None:
            return
        try:
            in_tokens = int(getattr(usage, in_attr, 0) or 0)
            out_tokens = int(getattr(usage, out_attr, 0) or 0)
            with self._usage_lock:
                self.usage["input"] += in_tokens
                self.usage["output"] += out_tokens
                self.usage["calls"] += 1
        except Exception:
            pass

    def chat_json(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> dict[str, Any]:
        raw = self.chat(system_prompt, user_prompt, json_mode=True, **kwargs)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse LLM JSON: %s", raw[:500])
            raise RuntimeError("LLM returned invalid JSON") from exc

    def validate_api_key(self) -> ValidationResult:
        """Validate credentials with a minimal completion (matches real usage)."""
        if not (self.api_key or "").strip():
            return ValidationResult(False, "API key is empty.")

        if self.sdk == "anthropic":
            return self._validate_anthropic()
        return self._validate_openai()

    def _validate_openai(self) -> ValidationResult:
        try:
            token_param = "max_completion_tokens" if self._needs_max_completion_tokens else "max_tokens"
            try:
                self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "Reply with OK"}],
                    **{token_param: 2},
                )
            except Exception as exc:
                if (
                    token_param == "max_tokens"
                    and "max_tokens" in str(exc)
                    and "max_completion_tokens" in str(exc)
                ):
                    self._needs_max_completion_tokens = True
                    self._client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": "Reply with OK"}],
                        max_completion_tokens=2,
                    )
                else:
                    raise
            return ValidationResult(True)
        except AuthenticationError as exc:
            logger.warning("API key authentication failed: %s", exc)
            return ValidationResult(False, "Invalid API key. Double-check the key for this provider.")
        except APIConnectionError as exc:
            logger.warning("API connection failed during validation: %s", exc)
            return ValidationResult(
                False,
                "Cannot reach the LLM API. Check your internet connection, VPN, or firewall. "
                f"If you're on a corporate network, the provider may be blocked. ({exc})",
            )
        except APIStatusError as exc:
            logger.warning("API status error during validation: %s", exc)
            status = exc.status_code
            if status == 403:
                return ValidationResult(False, f"Access denied for model '{self.model}'. Check your plan/model access.")
            if status == 404:
                return ValidationResult(False, f"Model '{self.model}' not found. Check the model name or base URL.")
            if status == 429:
                return ValidationResult(False, "Rate limited by the provider. Wait a moment and try again.")
            return ValidationResult(False, f"Provider API error ({status}): {exc.message}")
        except Exception as exc:
            logger.warning("API key validation failed: %s", exc)
            return ValidationResult(False, f"Validation failed: {exc}")

    def _validate_anthropic(self) -> ValidationResult:
        try:
            self._client.messages.create(
                model=self.model,
                max_tokens=2,
                messages=[{"role": "user", "content": "Reply with OK"}],
            )
            return ValidationResult(True)
        except Exception as exc:  # anthropic raises its own error hierarchy
            name = type(exc).__name__.lower()
            msg = str(exc)
            if "authentication" in name or "401" in msg or "invalid x-api-key" in msg.lower():
                return ValidationResult(False, "Invalid Anthropic API key. Check console.anthropic.com/settings/keys.")
            if "notfound" in name or "404" in msg:
                return ValidationResult(False, f"Model '{self.model}' not found. Check the model name.")
            if "connection" in name:
                return ValidationResult(False, f"Cannot reach the Anthropic API. Check connectivity/firewall. ({exc})")
            if "ratelimit" in name or "429" in msg:
                return ValidationResult(False, "Rate limited by Anthropic. Wait a moment and try again.")
            logger.warning("Anthropic validation failed: %s", exc)
            return ValidationResult(False, f"Validation failed: {exc}")
