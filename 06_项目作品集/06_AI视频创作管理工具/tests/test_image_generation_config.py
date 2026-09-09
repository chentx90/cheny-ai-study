from __future__ import annotations

import httpx

from ai_video_manager.image_generation import (
    ImageGenerationError,
    OpenAIImageClient,
    image_gateway_ready,
    resolve_image_gateway_config,
)
import pytest


def test_image_gateway_can_reuse_complete_llm_credentials() -> None:
    config = {
        "imageProvider": "openai",
        "imageUseLlmCredentials": True,
        "imageBaseUrl": "",
        "imageApiKey": "",
        "llmBaseUrl": "https://gateway.example/v1",
        "llmApiKey": "shared-key",
    }

    resolved = resolve_image_gateway_config(config)

    assert image_gateway_ready(config) is True
    assert resolved["imageBaseUrl"] == "https://gateway.example/v1"
    assert resolved["imageApiKey"] == "shared-key"
    assert resolved["imageCredentialSource"] == "llm"


def test_image_gateway_does_not_mix_partial_explicit_config_with_llm_credentials() -> None:
    config = {
        "imageUseLlmCredentials": True,
        "imageBaseUrl": "https://images.example/v1",
        "imageApiKey": "",
        "llmBaseUrl": "https://gateway.example/v1",
        "llmApiKey": "shared-key",
    }

    resolved = resolve_image_gateway_config(config)

    assert image_gateway_ready(config) is False
    assert resolved["imageBaseUrl"] == "https://images.example/v1"
    assert resolved["imageApiKey"] == ""
    assert resolved["imageCredentialSource"] == "image"


def test_image_connection_rejects_html_management_page(monkeypatch) -> None:
    def fake_get(self, url, headers):
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>console</html>")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = OpenAIImageClient(
        {"imageBaseUrl": "https://example.com/keys", "imageApiKey": "key", "imageModel": "image2"}
    )

    result = client.test_connection()

    assert result["ok"] is False
    assert "不是 JSON API" in str(result["detail"])


def test_image_generation_reports_gateway_address_on_connection_error(monkeypatch) -> None:
    def fake_post(self, url, json, headers):
        raise httpx.ConnectError("socket denied")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client = OpenAIImageClient(
        {
            "imageProvider": "openai",
            "imageBaseUrl": "https://images.example/v1",
            "imageApiKey": "key",
            "imageModel": "image-model",
        }
    )

    with pytest.raises(ImageGenerationError, match="https://images.example/v1"):
        client.generate("scene prompt")
