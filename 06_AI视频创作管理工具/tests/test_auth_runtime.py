from __future__ import annotations

from fastapi.testclient import TestClient

from ai_video_manager.api.app import create_app


def test_local_mode_bypasses_login_without_creating_user(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AVM_AUTH_DISABLED", raising=False)
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        setup = client.get("/api/auth/setup-status")
        assert setup.status_code == 200
        assert setup.json() == {"needs_setup": False, "auth_disabled": True}

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["auth_disabled"] is True
        assert me.json()["user"]["role"] == "admin"

        projects = client.get("/api/projects")
        assert projects.status_code == 200
        assert app.state.services.store.count_users() == 0


def test_login_and_setup_routes_are_removed(tmp_path, monkeypatch) -> None:
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        assert client.post("/api/auth/setup", json={}).status_code == 404
        assert client.post("/api/auth/login", json={}).status_code == 404
        assert client.post("/api/auth/logout").status_code == 404
