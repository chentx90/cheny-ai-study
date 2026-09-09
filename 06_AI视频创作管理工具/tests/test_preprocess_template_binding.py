from __future__ import annotations

from fastapi.testclient import TestClient

from ai_video_manager.api.app import create_app


class CapturingLLM:
    def __init__(self, prompts: list[str]) -> None:
        self.prompts = prompts
        self.provider = "test-provider"
        self.model = "test-model"

    def complete(self, prompt: str, **_kwargs) -> str:
        self.prompts.append(prompt)
        return "场景：演播室\n动作：主持人开始介绍。"


def test_preprocess_template_binding_persists_and_drives_conversion(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    captured_prompts: list[str] = []
    monkeypatch.setattr(
        "ai_video_manager.api.routes.document_routes.build_llm_client",
        lambda *_args, **_kwargs: CapturingLLM(captured_prompts),
    )
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project = client.post(
            "/api/projects", json={"name": "模板绑定测试", "category": "active"}
        ).json()
        project_id = project["id"]

        initial = client.get(f"/api/projects/{project_id}/session").json()["data"]
        assert initial["contentType"] == "分集原文"
        assert initial["scriptConvertTemplateId"] == ""
        assert initial["projectStylePrompt"] == ""

        template = client.post(
            "/api/prompts/templates",
            json={
                "name": "口播转剧本",
                "category": "script_convert",
                "template": "项目风格=$project_style_prompt\n输入类型=$content_type\n正文=$content",
                "is_default": False,
            },
        ).json()

        saved = client.put(
            f"/api/projects/{project_id}/document",
            json={
                "content_type": "口播稿",
                "script_convert_template_id": template["id"],
                "revision": initial["revision"],
            },
        )
        assert saved.status_code == 200

        settings = client.put(
            f"/api/projects/{project_id}/settings",
            json={
                "project_style_prompt": "高端3D国漫，低饱和电影光影",
                "revision": saved.json()["data"]["revision"],
            },
        )
        assert settings.status_code == 200

        segments = client.put(
            f"/api/projects/{project_id}/segments",
            json={
                "segments": [
                    {
                        "id": "seg_template_test",
                        "order": 1,
                        "title": "第一集",
                        "content": "欢迎收看今天的节目。",
                    }
                ],
                "revision": settings.json()["data"]["revision"],
            },
        )
        assert segments.status_code == 200

        restored = client.get(f"/api/projects/{project_id}/session").json()["data"]
        assert restored["contentType"] == "口播稿"
        assert restored["scriptConvertTemplateId"] == template["id"]
        assert restored["projectStylePrompt"] == "高端3D国漫，低饱和电影光影"

        converted = client.post(
            "/api/segments/convert",
            json={
                "segment_id": "seg_template_test",
                "order": 1,
                "content": "欢迎收看今天的节目。",
                "source_format": "source_text",
                "content_type": restored["contentType"],
                "template_id": restored["scriptConvertTemplateId"],
            },
        )
        assert converted.status_code == 200
        assert converted.json()["template_id"] == template["id"]
        assert captured_prompts == [
            "项目风格=高端3D国漫，低饱和电影光影\n"
            "输入类型=口播稿\n正文=欢迎收看今天的节目。"
        ]
