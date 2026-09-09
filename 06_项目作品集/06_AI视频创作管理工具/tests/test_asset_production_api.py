from __future__ import annotations

from fastapi.testclient import TestClient

from ai_video_manager.api.app import create_app


def test_asset_production_crud_and_style_versioning(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "资产项目", "category": "active"}).json()
        project_id = project["id"]
        profile = app.state.services.asset_production_repository.upsert_profile(
            project_id,
            {"canonical_name": "林舟", "type": "character", "importance": "S", "setting": "黑发青年"},
        )

        profiles = client.get(f"/api/v3/projects/{project_id}/entity-profiles")
        assert profiles.status_code == 200
        assert profiles.json()["profiles"][0]["canonical_name"] == "林舟"

        updated = client.patch(
            f"/api/v3/projects/{project_id}/entity-profiles/{profile['id']}",
            json={"importance": "A", "role": "protagonist"},
        )
        assert updated.status_code == 200
        assert updated.json()["importance"] == "A"

        style = client.post(
            f"/api/v3/projects/{project_id}/visual-styles",
            json={"name": "国风", "prompt": "水墨", "negative_prompt": "现代建筑", "is_active": True},
        )
        assert style.status_code == 200
        revised = client.patch(
            f"/api/v3/projects/{project_id}/visual-styles/{style.json()['id']}",
            json={"name": "国风", "prompt": "工笔重彩", "negative_prompt": "现代建筑", "is_active": True},
        )
        assert revised.status_code == 200
        assert revised.json()["version"] == 2
        styles = client.get(f"/api/v3/projects/{project_id}/visual-styles").json()["styles"]
        assert len(styles) == 2
        assert sum(bool(item["is_active"]) for item in styles) == 1

        preset = client.put(
            f"/api/v3/projects/{project_id}/asset-presets/character",
            json={"provider": "newapi", "model": "image-x", "size": "1024x1536", "aspect_ratio": "2:3", "output_count": 2, "view_types": ["全身"]},
        )
        assert preset.status_code == 200
        assert preset.json()["model"] == "image-x"

        card = client.post(
            f"/api/v3/projects/{project_id}/entity-profiles/{profile['id']}/entity-card",
            json={},
        )
        assert card.status_code == 200
        assert card.json()["entity_name"] == "林舟"
