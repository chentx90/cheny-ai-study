from __future__ import annotations

import pytest

from ai_video_manager.openai_gateway import is_vjimeng_gateway
from ai_video_manager.video_client import LangChainVideoClient, extract_video_url, map_generation_status
from ai_video_manager.video_generation import LangChainVideoAPIAdapter, _build_vjimeng_demo_payload


def test_is_vjimeng_gateway():
    assert is_vjimeng_gateway(provider="newapi", base_url="https://www.vjimeng.vip/v1")
    assert not is_vjimeng_gateway(provider="newapi", base_url="https://api.openai.com/v1")


def test_vjimeng_demo_payload_image2video():
    typed = {
        "images": [
            {"url": "https://files.vjimeng.vip/a.jpg", "role": "reference_image", "label": "参考图"},
            {"url": "https://files.vjimeng.vip/b.jpg", "role": "reference_image", "label": "参考图"},
        ],
        "videos": [],
        "audios": [{"url": "https://files.vjimeng.vip/a.mp3", "role": "reference_audio", "label": "参考音频"}],
    }
    body = _build_vjimeng_demo_payload(
        "宫女站在龙案前",
        typed,
        assets={"reference_mode": "omni"},
        reference_mode="omni",
        duration=5,
        settings={"model": "sd2-720p-mini", "aspect_ratio": "9:16"},
        generate_audio=True,
    )
    assert body["model"] == "sd2-720p-mini"
    assert body["duration"] == 5
    assert body["metadata"]["modeType"] == "image2video"
    assert body["metadata"]["ratio"] == "9:16"
    assert body["metadata"]["enableSound"] == "on"
    assert body["images"] == [
        "https://files.vjimeng.vip/a.jpg",
        "https://files.vjimeng.vip/b.jpg",
    ]
    assert body["audios"] == ["https://files.vjimeng.vip/a.mp3"]
    assert "content" not in body
    assert "input_reference" not in body
    assert "图片1" in body["prompt"]
    assert "音频1" in body["prompt"]


def test_vjimeng_demo_payload_frames2video():
    typed = {
        "images": [
            {"url": "https://files.vjimeng.vip/first.jpg", "role": "first_frame", "label": "首帧"},
            {"url": "https://files.vjimeng.vip/last.jpg", "role": "last_frame", "label": "尾帧"},
        ],
        "videos": [],
        "audios": [],
    }
    body = _build_vjimeng_demo_payload(
        "转场",
        typed,
        assets={
            "first_frame": "https://files.vjimeng.vip/first.jpg",
            "last_frame": "https://files.vjimeng.vip/last.jpg",
        },
        reference_mode="first_last",
        duration=4,
        settings={"model": "sd2-720p"},
        generate_audio=False,
    )
    assert body["metadata"]["modeType"] == "frames2video"
    assert body["metadata"]["enableSound"] == "off"
    assert body["images"] == [
        "https://files.vjimeng.vip/first.jpg",
        "https://files.vjimeng.vip/last.jpg",
    ]


def test_vjimeng_client_endpoints(monkeypatch):
    client = LangChainVideoClient(
        provider="newapi",
        base_url="https://www.vjimeng.vip/v1",
        api_key="sk-test",
    )
    assert client.uses_vjimeng_native_api
    assert client.site_root == "https://www.vjimeng.vip"

    posted: list[tuple[str, dict]] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"task_id": "task_demo_1", "status": "PENDING"}

        @property
        def text(self):
            return "{}"

        reason_phrase = "ok"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            posted.append((url, json or {}))
            return FakeResponse()

        async def get(self, url, headers=None):
            assert "/v1/video/fetch/task_demo_1" in url
            return FakeResponse()

    monkeypatch.setattr("ai_video_manager.video_client.httpx.AsyncClient", FakeAsyncClient)

    import asyncio

    async def run():
        task_id, data = await client.create_generation(
            {
                "model": "sd2-720p-mini",
                "prompt": "图片1 测试",
                "duration": 5,
                "images": ["https://files.vjimeng.vip/a.jpg"],
                "metadata": {"modeType": "image2video", "ratio": "16:9", "enableSound": "on"},
            }
        )
        assert task_id == "task_demo_1"
        assert posted[0][0] == "https://www.vjimeng.vip/v1/video/submit/generate"
        assert "images" in posted[0][1]
        fetched = await client.get_generation(task_id)
        assert fetched.get("task_id") == "task_demo_1" or fetched.get("status")

    asyncio.run(run())


def test_adapter_builds_vjimeng_body(monkeypatch):
    client = LangChainVideoClient(
        provider="newapi",
        base_url="https://www.vjimeng.vip",
        api_key="sk-test",
    )
    adapter = LangChainVideoAPIAdapter(client=client, provider="newapi")
    import ai_video_manager.gateway_media as gm

    monkeypatch.setattr(gm, "verify_http_refs_reachable", lambda urls, **kwargs: [{"url": u, "ok": True} for u in urls])

    payload = adapter._build_payload(
        "测试角色一致性",
        {
            "reference_mode": "omni",
            "reference_images": ["https://files.vjimeng.vip/a.jpg"],
            "settings": {"model": "sd2-720p-mini", "duration": 5, "aspect_ratio": "9:16"},
        },
        duration=5,
        settings=None,
    )
    assert payload["images"] == ["https://files.vjimeng.vip/a.jpg"]
    assert payload["metadata"]["modeType"] == "image2video"
    assert "content" not in payload


def test_adapter_rejects_non_vjimeng_base():
    client = LangChainVideoClient(
        provider="newapi",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    adapter = LangChainVideoAPIAdapter(client=client, provider="newapi")
    with pytest.raises(ValueError, match="仅支持星链云"):
        adapter._build_payload(
            "x",
            {"reference_mode": "none", "settings": {"model": "m"}},
            duration=5,
            settings=None,
        )


def test_map_status_and_result_url():
    assert map_generation_status({"status": "SUCCESS", "result_url": "http://x/a.mp4"}) == "completed"
    assert map_generation_status({"status": "FAILURE"}) == "failed"
    assert extract_video_url({"result_url": "http://x/a.mp4"}) == "http://x/a.mp4"
