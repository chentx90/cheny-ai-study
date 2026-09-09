from fastapi.testclient import TestClient

from manga_manager import store
from manga_manager.api import app
from manga_manager.models import Entity, EntityVariant, Episode, RawSpan, Scene


def test_api_lists_and_summarizes_work(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("API 测试")
    store.save_episodes(
        work.id,
        [
            Episode(
                id="ep0000",
                idx=0,
                title="第一集",
                raw_span=RawSpan(start=0, end=20),
                scenes=[
                    Scene(
                        id="s00000_api",
                        episode_idx=0,
                        idx=0,
                        summary="开场",
                        raw_span=RawSpan(start=0, end=10),
                    )
                ],
            )
        ],
    )

    client = TestClient(app)
    works = client.get("/api/works")
    assert works.status_code == 200
    assert works.json()["active_work_id"] == work.id

    overview = client.get(f"/api/works/{work.id}/overview")
    assert overview.status_code == 200
    assert overview.json()["counts"]["episodes"] == 1
    assert overview.json()["counts"]["scenes"] == 1


def test_api_updates_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("提示词测试")
    client = TestClient(app)

    response = client.put(
        f"/api/works/{work.id}/prompts/s00000_api",
        json={"text": "镜头缓慢推进。"},
    )
    assert response.status_code == 200
    assert response.json()["chars"] == len("镜头缓慢推进。")

    prompt = client.get(f"/api/works/{work.id}/prompts/s00000_api")
    assert prompt.status_code == 200
    assert prompt.json()["text"] == "镜头缓慢推进。"


def test_api_updates_prompt_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("配置测试")
    client = TestClient(app)

    response = client.put(
        f"/api/works/{work.id}/prompt-config",
        json={
            "narrative_style": "克制叙事",
            "visual_style": "cinematic anime",
            "palette": "冷暖对比",
            "render_keywords": "soft light",
            "camera_language": "slow dolly",
            "negative_prompt": "no text",
        },
    )
    assert response.status_code == 200
    assert response.json()["style_guide"]["camera_language"] == "slow dolly"

    config = client.get(f"/api/works/{work.id}/prompt-config")
    assert config.status_code == 200
    assert config.json()["style_guide"]["negative_prompt"] == "no text"


def test_api_uploads_and_deletes_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("素材测试")
    store.save_entities(
        work.id,
        [
            Entity(
                id="e1",
                type="character",
                name="妹妹",
                variants=[EntityVariant(label="童年", time_desc="", appearance="")],
            )
        ],
    )
    client = TestClient(app)

    upload = client.post(
        f"/api/works/{work.id}/assets",
        data={"entity_id": "e1", "variant_label": "童年", "kind": "image"},
        files={"file": ("sister.png", b"image-bytes", "image/png")},
    )
    assert upload.status_code == 201

    assets = client.get(f"/api/works/{work.id}/assets").json()["assets"]
    assert len(assets) == 1
    assert assets[0]["exists"]

    detail = client.get(f"/api/works/{work.id}/assets/detail", params={"path": assets[0]["path"]})
    assert detail.status_code == 200
    assert detail.json()["asset"]["entity_id"] == "e1"

    update = client.patch(
        f"/api/works/{work.id}/assets",
        params={"path": assets[0]["path"]},
        json={"entity_id": "e1", "variant_label": "成年", "kind": "image"},
    )
    assert update.status_code == 200
    assert update.json()["asset"]["variant_label"] == "成年"

    assets = client.get(f"/api/works/{work.id}/assets").json()["assets"]
    assert assets[0]["variant_label"] == "成年"

    delete = client.delete(f"/api/works/{work.id}/assets", params={"path": assets[0]["path"]})
    assert delete.status_code == 200
    assert delete.json()["removed_reference"]
    assert client.get(f"/api/works/{work.id}/assets").json()["assets"] == []
