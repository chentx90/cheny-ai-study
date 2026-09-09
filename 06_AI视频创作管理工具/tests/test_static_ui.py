from __future__ import annotations

from fastapi.testclient import TestClient

from ai_video_manager.api.app import create_app


def test_static_ui_falls_back_only_for_frontend_routes(tmp_path, monkeypatch) -> None:
    static_dir = tmp_path / "frontend" / "dist"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text('<main id="root">app</main>', encoding="utf-8")

    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    monkeypatch.setenv("AVM_SERVE_UI", "1")
    monkeypatch.setenv("AVM_STATIC_DIR", str(static_dir))
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        route = client.get("/projects/project-1/preprocess")
        assert route.status_code == 200
        assert 'id="root"' in route.text

        assert client.get("/api/does-not-exist").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404
