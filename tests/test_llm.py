from __future__ import annotations

from tech_desk.llm import LLMClient, _resolve_provider


def test_resolve_provider_prefers_explicit():
    assert _resolve_provider("anthropic", "gpt-4o") == "anthropic"


def test_resolve_provider_infers_from_model():
    assert _resolve_provider(None, "claude-sonnet-4-20250514") == "anthropic"
    assert _resolve_provider(None, "gemini-2.5-pro") == "google"


def test_resolve_provider_falls_back_to_default():
    # Unknown provider + unknown model -> configured default (openai in tests)
    assert _resolve_provider("not-a-provider", "not-a-model") == "openai"


def test_client_selects_openai_sdk_for_openai_model():
    client = LLMClient(api_key="sk-test", model="gpt-4o")
    try:
        assert client.provider == "openai"
        assert client.sdk == "openai"
        assert client.usage == {"input": 0, "output": 0, "calls": 0}
    finally:
        client.close()


def test_client_selects_anthropic_sdk_for_claude_model():
    client = LLMClient(api_key="sk-ant-test", model="claude-3-5-haiku-latest")
    try:
        assert client.provider == "anthropic"
        assert client.sdk == "anthropic"
    finally:
        client.close()


def test_validate_api_key_rejects_empty_key_without_network():
    # Construct with a placeholder key (the SDK rejects an empty key at
    # construction), then clear it to exercise the empty-key guard.
    client = LLMClient(api_key="sk-placeholder", model="gpt-4o")
    client.api_key = ""
    try:
        result = client.validate_api_key()
        assert result.ok is False
        assert "empty" in result.message.lower()
    finally:
        client.close()


def test_close_is_idempotent():
    client = LLMClient(api_key="sk-test", model="gpt-4o")
    client.close()
    client.close()  # must not raise


def test_record_usage_accumulates():
    client = LLMClient(api_key="sk-test", model="gpt-4o")
    try:
        class Usage:
            prompt_tokens = 120
            completion_tokens = 30

        client._record_usage(Usage(), "prompt_tokens", "completion_tokens")
        client._record_usage(Usage(), "prompt_tokens", "completion_tokens")
        assert client.usage == {"input": 240, "output": 60, "calls": 2}
    finally:
        client.close()


def test_record_usage_is_thread_safe_under_concurrency():
    """analyze_result() calls now run concurrently across worker threads
    sharing one LLMClient — usage counters must not lose updates to races."""
    from concurrent.futures import ThreadPoolExecutor

    client = LLMClient(api_key="sk-test", model="gpt-4o")
    try:
        class Usage:
            prompt_tokens = 10
            completion_tokens = 5

        call_count = 200

        def _record(_i):
            client._record_usage(Usage(), "prompt_tokens", "completion_tokens")

        with ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(_record, range(call_count)))

        assert client.usage == {"input": 10 * call_count, "output": 5 * call_count, "calls": call_count}
    finally:
        client.close()
