from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from ai_video_manager.api.video_assets import prepare_video_assets_for_api, resolve_video_asset_reference
from ai_video_manager.gateway_media import extract_gateway_file_id, extract_gateway_file_url, infer_gateway_asset_type
from ai_video_manager.models import Project
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.video_refs import collect_typed_references


@pytest.fixture
def isolated_store() -> SQLiteStore:
    tmp = Path(tempfile.mkdtemp(prefix="avm_media_"))
    db_path = tmp / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path, workspace_root=tmp)
    store.init_schema()
    yield store
    shutil.rmtree(tmp, ignore_errors=True)


def test_extract_gateway_file_url_variants():
    assert extract_gateway_file_url({"url": "https://cdn.example/a.png"}) == "https://cdn.example/a.png"
    assert extract_gateway_file_url({"data": {"publicUrl": "https://cdn.example/b.png"}}) == "https://cdn.example/b.png"
    assert extract_gateway_file_url({"file": {"download_url": "asset://asset-1"}}) == "asset://asset-1"
    assert extract_gateway_file_url({"id": "file-1"}) == ""


def test_extract_gateway_file_id_nested():
    assert extract_gateway_file_id({"id": "file-abc"}) == "file-abc"
    assert extract_gateway_file_id({"data": {"AssetId": "asset-xyz"}}) == "asset-xyz"


def test_collect_typed_references_accepts_asset_uri():
    typed = collect_typed_references(
        {
            "reference_mode": "omni",
            "reference_images": ["asset://asset-123", "https://cdn.example/x.png"],
        },
        reference_mode="omni",
    )
    assert [item["url"] for item in typed["images"]] == [
        "asset://asset-123",
        "https://cdn.example/x.png",
    ]


def test_prepare_video_assets_uses_uploader(isolated_store: SQLiteStore):
    project = isolated_store.save_project(Project(name="cloud-upload"))
    project_id = project.id
    image_path = isolated_store.save_asset(project_id, "image", "ref.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    uploaded: list[tuple[str, str]] = []

    def fake_uploader(path: Path, asset_type: str) -> str:
        uploaded.append((path.name, asset_type))
        assert path.exists()
        assert asset_type == "Image"
        return "https://cdn.example/uploaded-ref.png"

    prepared = prepare_video_assets_for_api(
        isolated_store,
        project_id,
        {
            "reference_mode": "omni",
            "reference_images": [image_path],
        },
        uploader=fake_uploader,
    )
    assert prepared["reference_images"] == ["https://cdn.example/uploaded-ref.png"]
    assert uploaded and uploaded[0][0] == Path(image_path).name


def test_resolve_keeps_existing_remote_refs(isolated_store: SQLiteStore):
    project = isolated_store.save_project(Project(name="remote-ref"))
    assert (
        resolve_video_asset_reference(isolated_store, project.id, "asset://asset-keep")
        == "asset://asset-keep"
    )
    assert (
        resolve_video_asset_reference(isolated_store, project.id, "https://cdn.example/keep.png")
        == "https://cdn.example/keep.png"
    )


def test_infer_gateway_asset_type():
    assert infer_gateway_asset_type("a.mp4") == "Video"
    assert infer_gateway_asset_type("a.wav") == "Audio"
    assert infer_gateway_asset_type("a.png") == "Image"


def test_resolve_upload_api_base_maps_vjimeng():
    from ai_video_manager.gateway_media import resolve_upload_api_base

    assert (
        resolve_upload_api_base(provider="newapi", video_base_url="https://www.vjimeng.vip/v1")
        == "https://oss.vjimeng.vip"
    )
    assert (
        resolve_upload_api_base(
            provider="newapi",
            video_base_url="https://www.vjimeng.vip/v1",
            upload_api_base="https://custom-oss.example",
        )
        == "https://custom-oss.example"
    )
    assert resolve_upload_api_base(provider="newapi", video_base_url="https://api.openai.com/v1") == ""


def test_direct_oss_upload_flow(monkeypatch, tmp_path: Path):
    from ai_video_manager.gateway_media import GatewayMediaClient

    sample = tmp_path / "ref.png"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    calls: list[tuple[str, str]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict | str):
            self.status_code = status_code
            self._payload = payload
            self.reason_phrase = "ok"

        @property
        def text(self) -> str:
            if isinstance(self._payload, dict):
                import json

                return json.dumps(self._payload)
            return str(self._payload)

        def json(self):
            if isinstance(self._payload, dict):
                return self._payload
            raise ValueError("not json")

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None, data=None, files=None):
            calls.append(("POST", url))
            if url.endswith("/api/direct-upload/sign"):
                assert json["filename"] == "ref.png"
                assert json["type"] == "image"
                assert json["size"] == sample.stat().st_size
                return FakeResponse(
                    200,
                    {
                        "method": "PUT",
                        "upload_url": "https://bucket.example/upload?sig=1",
                        "public_url": "https://files.example/users/1/images/ref.png",
                        "key": "users/1/images/ref.png",
                        "headers": {"Content-Type": "image/png"},
                    },
                )
            if url.endswith("/api/direct-upload/complete"):
                assert json["key"] == "users/1/images/ref.png"
                return FakeResponse(
                    200,
                    {
                        "recorded": True,
                        "url": "https://files.example/users/1/images/ref.png",
                        "key": "users/1/images/ref.png",
                    },
                )
            raise AssertionError(f"unexpected POST {url}")

        def request(self, method, url, headers=None, content=None):
            calls.append((method, url))
            assert method == "PUT"
            assert url.startswith("https://bucket.example/upload")
            assert headers.get("Content-Type") == "image/png"
            assert content
            return FakeResponse(200, "ok")

    monkeypatch.setattr("ai_video_manager.gateway_media.build_http_client", lambda **kwargs: FakeClient())

    client = GatewayMediaClient(
        provider="newapi",
        base_url="https://www.vjimeng.vip/v1",
        api_key="sk-test",
    )
    assert client.upload_api_base == "https://oss.vjimeng.vip"
    url = client.upload_reference(sample, asset_type="Image")
    assert url == "https://files.example/users/1/images/ref.png"
    assert [c[0] for c in calls] == ["POST", "PUT", "POST"]
    assert "/api/direct-upload/sign" in calls[0][1]
    assert "/api/direct-upload/complete" in calls[2][1]


def test_direct_oss_retries_on_disconnect(monkeypatch, tmp_path: Path):
    import httpx
    from ai_video_manager.gateway_media import GatewayMediaClient

    sample = tmp_path / "ref.png"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    put_attempts = {"n": 0}

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict | str):
            self.status_code = status_code
            self._payload = payload
            self.reason_phrase = "ok"

        @property
        def text(self) -> str:
            return str(self._payload)

        def json(self):
            if isinstance(self._payload, dict):
                return self._payload
            raise ValueError("not json")

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None, data=None, files=None):
            if url.endswith("/api/direct-upload/sign"):
                return FakeResponse(
                    200,
                    {
                        "method": "PUT",
                        "upload_url": "https://bucket.example/upload?sig=1",
                        "public_url": "https://files.example/users/1/images/ref.png",
                        "key": "users/1/images/ref.png",
                        "headers": {"Content-Type": "image/png"},
                    },
                )
            if url.endswith("/api/direct-upload/complete"):
                return FakeResponse(200, {"url": "https://files.example/users/1/images/ref.png"})
            raise AssertionError(url)

        def request(self, method, url, headers=None, content=None):
            put_attempts["n"] += 1
            if put_attempts["n"] == 1:
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            return FakeResponse(200, "ok")

    monkeypatch.setattr("ai_video_manager.gateway_media.build_http_client", lambda **kwargs: FakeClient())
    monkeypatch.setattr("ai_video_manager.gateway_media.time.sleep", lambda *_: None)

    client = GatewayMediaClient(
        provider="newapi",
        base_url="https://www.vjimeng.vip/v1",
        api_key="sk-test",
    )
    url = client.upload_reference(sample, asset_type="Image")
    assert url.endswith("ref.png")
    assert put_attempts["n"] == 2


def test_stabilize_oss_public_url_strips_signature():
    from ai_video_manager.gateway_media import stabilize_oss_public_url

    signed = (
        "https://files.vjimeng.vip/users/1/images/a.jpg"
        "?x-oss-signature-version=OSS4-HMAC-SHA256&x-oss-date=20260713T174443Z&x-oss-signature=abc"
    )
    assert stabilize_oss_public_url(signed) == "https://files.vjimeng.vip/users/1/images/a.jpg"
    assert stabilize_oss_public_url("https://cdn.example/a.png") == "https://cdn.example/a.png"


def test_verify_http_refs_reachable_ok(monkeypatch):
    from ai_video_manager import gateway_media

    class FakeResponse:
        status_code = 200
        content = b"x" * 128
        headers = {"content-type": "image/jpeg"}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            assert url.startswith("https://")
            return FakeResponse()

    monkeypatch.setattr(gateway_media, "build_http_client", lambda **kwargs: FakeClient())
    report = gateway_media.verify_http_refs_reachable(["https://files.example/a.jpg"])
    assert report and report[0]["ok"] is True


def test_verify_http_refs_reachable_fails_on_404(monkeypatch):
    from ai_video_manager import gateway_media

    class FakeResponse:
        status_code = 404
        content = b"missing"
        headers = {"content-type": "text/plain"}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(gateway_media, "build_http_client", lambda **kwargs: FakeClient())
    with pytest.raises(ValueError, match="出站前校验失败"):
        gateway_media.verify_http_refs_reachable(["https://files.example/missing.jpg"])


def test_collect_typed_references_rejects_local_paths():
    from ai_video_manager.video_refs import collect_typed_references

    with pytest.raises(ValueError, match="内部错误|本地"):
        collect_typed_references(
            {"reference_mode": "omni", "reference_images": ["assets/images/a.png"]},
            reference_mode="omni",
        )


def test_vjimeng_requires_oss_base_no_files_fallback():
    from ai_video_manager.gateway_media import GatewayMediaClient

    client = GatewayMediaClient(
        provider="newapi",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    assert client.upload_api_base == ""
    with pytest.raises(ValueError, match="OSS 直传"):
        client.upload_reference(__file__, asset_type="Image")
