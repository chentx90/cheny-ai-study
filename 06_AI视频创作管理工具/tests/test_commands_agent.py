from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ai_video_manager.api.app import create_app
from ai_video_manager.commands import build_command_registry
from ai_video_manager.llm import normalize_llm_use_cases


class FakeWorkflowLLM:
    provider = "test-provider"
    model = "test-model"

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def complete(self, prompt: str, **_kwargs) -> str:
        return json.dumps(
            {
                "message": "读取当前项目状态",
                "commands": [
                    {
                        "command": "project.show",
                        "arguments": {"project_id": self.project_id},
                        "reason": "确认当前项目工作区",
                    }
                ],
            },
            ensure_ascii=False,
        )


class FakeWriteWorkflowLLM(FakeWorkflowLLM):
    def complete(self, prompt: str, **_kwargs) -> str:
        return json.dumps(
            {
                "message": "准备修改项目名称",
                "commands": [
                    {
                        "command": "project.update",
                        "arguments": {"project_id": self.project_id, "name": "审批后名称"},
                        "reason": "按用户要求修改项目名称",
                    }
                ],
            },
            ensure_ascii=False,
        )


class FakeReactWorkflowLLM:
    provider = "test-provider"
    model = "test-model"

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.calls = 0

    def complete(self, prompt: str, **_kwargs) -> str:
        self.calls += 1
        if self.calls == 1:
            payload = {
                "message": "先读取当前项目剧本",
                "done": False,
                "action": {
                    "command": "script.show",
                    "arguments": {"project_id": self.project_id},
                    "reason": "根据剧本内容归纳项目风格",
                },
            }
        elif self.calls == 2:
            payload = {
                "message": "已读取剧本，准备写入项目提示词",
                "done": False,
                "action": {
                    "command": "project.settings.update",
                    "arguments": {"project_id": self.project_id, "project_style_prompt": "现代都市悬疑，冷峻电影光影，统一写实人物与场景质感"},
                    "reason": "将剧本归纳出的统一风格保存到项目设置",
                },
            }
        else:
            payload = {"message": "项目提示词已保存", "done": True, "action": None}
        return json.dumps(payload, ensure_ascii=False)


class FakeExistingProfileWorkflowLLM:
    provider = "test-provider"
    model = "test-model"

    def __init__(self, project_id: str, profile_id: str) -> None:
        self.project_id = project_id
        self.profile_id = profile_id
        self.prompt = ""

    def complete(self, prompt: str, **_kwargs) -> str:
        self.prompt = prompt
        return json.dumps(
            {
                "message": "已找到春潮香铺实体档案，直接补充视觉设定",
                "done": False,
                "action": {
                    "command": "entity.generate-setting",
                    "arguments": {"project_id": self.project_id, "profile_id": self.profile_id},
                    "reason": "实体档案已经存在，不重复提取剧本",
                },
            },
            ensure_ascii=False,
        )


def test_every_mutation_command_declares_frontend_effects() -> None:
    missing = [
        spec.id
        for spec in build_command_registry().values()
        if spec.mutation and not spec.effects
    ]

    assert missing == []


def test_command_catalog_and_agent_read_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Agent 测试", "category": "active"}).json()
        project_id = project["id"]

        catalog = client.get("/api/commands/catalog")
        assert catalog.status_code == 200
        assert any(item["id"] == "project.show" for item in catalog.json()["commands"])
        style_spec = next(
            item for item in catalog.json()["commands"] if item["id"] == "visual-style.save"
        )
        assert style_spec["effects"] == ["asset-production", "projects"]

        monkeypatch.setattr(
            "ai_video_manager.agent.service.build_llm_client",
            lambda *_args, **_kwargs: FakeWorkflowLLM(project_id),
        )
        thread = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        result = client.post(
            f"/api/agent/threads/{thread['id']}/messages",
            json={"content": "查看当前项目状态", "ui_context": {"current_view": "projects"}},
        )
        assert result.status_code == 200
        run = result.json()["run"]
        assert run["status"] == "completed"
        assert result.json()["tool_calls"][0]["command_id"] == "project.show"

        events = client.get(f"/api/agent/runs/{run['id']}/events")
        assert events.status_code == 200
        assert "run_completed" in events.text

        restored = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        assert restored["id"] == thread["id"]
        detail = client.get(f"/api/agent/threads/{restored['id']}").json()
        assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]


def test_agent_write_waits_for_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "审批前名称", "category": "active"}).json()
        project_id = project["id"]
        monkeypatch.setattr(
            "ai_video_manager.agent.service.build_llm_client",
            lambda *_args, **_kwargs: FakeWriteWorkflowLLM(project_id),
        )
        thread = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        planned = client.post(
            f"/api/agent/threads/{thread['id']}/messages",
            json={"content": "修改项目名称", "ui_context": {"current_view": "projects"}},
        ).json()

        assert planned["run"]["status"] == "waiting_approval"
        assert client.get(f"/api/projects/{project_id}").json()["name"] == "审批前名称"

        approved = client.post(f"/api/agent/runs/{planned['run']['id']}/approve").json()
        assert approved["run"]["status"] == "completed"
        assert approved["run"]["state"]["results"][0]["effects"] == ["projects"]
        assert client.get(f"/api/projects/{project_id}").json()["name"] == "审批后名称"


def test_agent_approval_preset_auto_executes_non_destructive_commands(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects", json={"name": "自动审批前", "category": "active"}
        ).json()["id"]
        monkeypatch.setattr(
            "ai_video_manager.agent.service.build_llm_client",
            lambda *_args, **_kwargs: FakeWriteWorkflowLLM(project_id),
        )
        thread = client.post(
            "/api/agent/threads", json={"project_id": project_id}
        ).json()["thread"]
        result = client.post(
            f"/api/agent/threads/{thread['id']}/messages",
            json={"content": "修改项目名称", "approval_mode": "trusted"},
        ).json()

        assert result["run"]["status"] == "completed"
        assert result["run"]["state"]["approval_mode"] == "trusted"
        assert result["run"]["state"]["results"][0]["effects"] == ["projects"]
        assert client.get(f"/api/projects/{project_id}").json()["name"] == "审批后名称"


def test_agent_approval_presets_never_auto_approve_deletion() -> None:
    from ai_video_manager.agent.service import WorkflowAgentService

    assert WorkflowAgentService._requires_confirmation("write", "manual") is True
    assert WorkflowAgentService._requires_confirmation("llm", "project") is False
    assert WorkflowAgentService._requires_confirmation("external", "project") is True
    assert WorkflowAgentService._requires_confirmation("external", "trusted") is False
    assert WorkflowAgentService._requires_confirmation("destructive", "trusted") is True
    assert WorkflowAgentService._normalize_approval_mode("unknown") == "manual"


def test_agent_react_reads_script_then_updates_project_prompt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "ReAct 测试", "category": "active"}).json()
        project_id = project["id"]
        segments = client.put(
            f"/api/projects/{project_id}/segments",
            json={"segments": [{"id": "seg_1", "order": 1, "title": "第一集", "content": "城市雨夜，侦探在旧车站追查失踪案。"}]},
        )
        assert segments.status_code == 200
        saved_script = client.put(
            f"/api/projects/{project_id}/segments/seg_1/script",
            json={"content": "场景：旧车站，雨夜。\n人物：侦探。\n侦探：他一定还在这里。"},
        )
        assert saved_script.status_code == 200

        fake = FakeReactWorkflowLLM(project_id)
        monkeypatch.setattr("ai_video_manager.agent.service.build_llm_client", lambda *_args, **_kwargs: fake)
        thread = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        planned = client.post(
            f"/api/agent/threads/{thread['id']}/messages",
            json={"content": "现在读剧本，然后生成项目提示词", "ui_context": {"current_view": "projects"}},
        ).json()

        assert planned["run"]["status"] == "waiting_approval"
        assert [call["command_id"] for call in planned["tool_calls"]] == ["script.show", "project.settings.update"]
        waiting_message = planned["messages"][-1]
        assert [item["command"] for item in waiting_message["metadata"]["commands"]] == ["script.show", "project.settings.update"]
        assert len(waiting_message["metadata"]["results"]) == 1
        assert client.get(f"/api/projects/{project_id}/session").json()["data"]["projectStylePrompt"] == ""
        restored_waiting = client.get(f"/api/agent/threads/{thread['id']}").json()
        assert restored_waiting["run"]["status"] == "waiting_approval"
        assert restored_waiting["tool_calls"][-1]["command_id"] == "project.settings.update"

        approved = client.post(f"/api/agent/runs/{planned['run']['id']}/approve").json()
        assert approved["run"]["status"] == "completed"
        assert fake.calls >= 3
        assert client.get(f"/api/projects/{project_id}/session").json()["data"]["projectStylePrompt"].startswith("现代都市悬疑")


def test_project_file_tools_are_project_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "文件工具", "category": "active"}).json()["id"]
        write = client.post(
            "/api/commands/execute",
            json={
                "command": "file.write",
                "arguments": {"project_id": project_id, "path": "notes/style.md", "content": "统一电影光影"},
                "confirmed": True,
            },
        )
        assert write.status_code == 200
        assert write.json()["data"]["path"] == "notes/style.md"

        read = client.post(
            "/api/commands/execute",
            json={"command": "file.read", "arguments": {"project_id": project_id, "path": "notes/style.md"}},
        )
        assert read.status_code == 200
        assert read.json()["data"]["content"] == "统一电影光影"

        listed = client.post(
            "/api/commands/execute",
            json={"command": "file.list", "arguments": {"project_id": project_id, "path": "notes"}},
        )
        assert [item["path"] for item in listed.json()["data"]["files"]] == ["notes/style.md"]

        escaped = client.post(
            "/api/commands/execute",
            json={"command": "file.read", "arguments": {"project_id": project_id, "path": "../outside.txt"}},
        )
        assert escaped.status_code == 400
        assert "路径越出当前项目数据目录" in escaped.json()["detail"]


def test_agent_cancel_updates_tool_and_message_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "取消状态", "category": "active"}).json()["id"]
        monkeypatch.setattr(
            "ai_video_manager.agent.service.build_llm_client",
            lambda *_args, **_kwargs: FakeWriteWorkflowLLM(project_id),
        )
        thread = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        planned = client.post(
            f"/api/agent/threads/{thread['id']}/messages",
            json={"content": "修改项目名称"},
        ).json()
        cancelled = client.post(f"/api/agent/runs/{planned['run']['id']}/cancel").json()

        assert cancelled["run"]["status"] == "cancelled"
        assert cancelled["tool_calls"][0]["status"] == "cancelled"
        assert cancelled["messages"][-1]["metadata"]["status"] == "cancelled"


def test_agent_uses_existing_entity_profile_without_reextracting(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "已有实体", "category": "active"}).json()["id"]
        profile = app.state.services.asset_production_repository.upsert_profile(
            project_id,
            {
                "canonical_name": "春潮香铺",
                "type": "scene",
                "aliases": ["INTERNAL_ALIAS_SHOULD_BE_LOADED_ON_DEMAND"],
                "importance": "S",
                "mention_count": 20,
                "scene_count": 10,
                "setting": "INTERNAL_SETTING_DETAIL_SHOULD_BE_LOADED_ON_DEMAND",
            },
        )
        fake = FakeExistingProfileWorkflowLLM(project_id, profile["id"])
        monkeypatch.setattr("ai_video_manager.agent.service.build_llm_client", lambda *_args, **_kwargs: fake)
        thread = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        result = client.post(
            f"/api/agent/threads/{thread['id']}/messages",
            json={"content": "生成春潮香铺的设定图", "ui_context": {"current_view": "resources"}},
        ).json()

        assert result["run"]["status"] == "waiting_approval"
        assert [call["command_id"] for call in result["tool_calls"]] == ["entity.generate-setting"]
        assert "春潮香铺" in fake.prompt
        assert profile["id"] in fake.prompt
        assert "\"profile_count\": 1" in fake.prompt
        assert "INTERNAL_SETTING_DETAIL_SHOULD_BE_LOADED_ON_DEMAND" not in fake.prompt
        assert "INTERNAL_ALIAS_SHOULD_BE_LOADED_ON_DEMAND" not in fake.prompt


def test_entity_extract_command_passes_episode_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))
    captured = {}

    def fake_analyze(project_id, user_id, episode_ids=None):
        captured.update({"project_id": project_id, "user_id": user_id, "episode_ids": episode_ids})
        return {"profiles": []}

    app.state.services.entity_asset_service.analyze = fake_analyze
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "提取参数", "category": "active"}).json()["id"]
        result = client.post(
            "/api/commands/execute",
            json={
                "command": "entity.extract",
                "arguments": {"project_id": project_id, "segment_ids": ["ep_1", "ep_2"]},
                "confirmed": True,
            },
        )
        assert result.status_code == 200
        assert captured["episode_ids"] == ["ep_1", "ep_2"]


def test_agent_context_stays_uncompressed_until_budget_threshold(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "上下文预算", "category": "active"}).json()["id"]
        thread = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        repository = app.state.services.workflow_agent.repository
        for index in range(12):
            repository.add_message(
                thread["id"],
                "user" if index % 2 == 0 else "assistant",
                f"第 {index + 1} 条历史消息：保持人物与场景连续性。",
                {},
            )

        context = app.state.services.workflow_agent._prepare_conversation_context(thread["id"])
        unchanged_thread = repository.get_thread(thread["id"])
        assert context["summary"] == ""
        assert len(context["recent_messages"]) == 12
        assert unchanged_thread["summary_message_id"] is None

        attachment_message = repository.add_message(
            thread["id"],
            "user",
            "参考这张素材",
            {
                "ui_context": {
                    "active_context": {
                        "attachments": [
                            {
                                "path": "assets/image/reference.png",
                                "filename": "reference.png",
                                "asset_type": "image",
                                "unexpected_binary": "not-forwarded",
                            }
                        ]
                    }
                }
            },
        )
        compact = app.state.services.workflow_agent._compact_conversation_message(
            attachment_message
        )
        assert compact["attachments"] == [
            {
                "path": "assets/image/reference.png",
                "filename": "reference.png",
                "asset_type": "image",
            }
        ]


def test_agent_context_compresses_to_target_and_branch_keeps_recent_messages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "分支测试", "category": "active"}).json()["id"]
        thread = client.post("/api/agent/threads", json={"project_id": project_id}).json()["thread"]
        service = app.state.services.workflow_agent
        repository = service.repository
        for index in range(12):
            repository.add_message(
                thread["id"],
                "user" if index % 2 == 0 else "assistant",
                f"第 {index + 1} 条历史消息：" + ("保持人物与场景连续性。" * 500),
                {},
            )
        context = service._prepare_conversation_context(thread["id"])
        run = repository.create_run(thread["id"], "继续处理")

        monkeypatch.setattr(
            service,
            "_render_agent_prompt",
            lambda state, _template, _catalog: json.dumps(
                state.get("conversation_context") or {}, ensure_ascii=False
            ),
        )
        compressed = service._apply_context_budget(
            {
                "run_id": run["id"],
                "thread_id": thread["id"],
                "conversation_context": context,
            },
            None,
            {
                "contextWindowTokens": 128000,
                "reservedOutputTokens": 12000,
                "compressionThreshold": 0.5,
                "compressionTarget": 0.2,
                "recentMessagesToKeep": 2,
            },
            [],
        )
        budget = compressed["context_budget"]
        compressed_thread = repository.get_thread(thread["id"])
        assert budget["compressed"] is True
        assert budget["estimated_input_tokens_after"] <= budget["compression_target_tokens"]
        assert len(compressed["conversation_context"]["recent_messages"]) >= 2
        assert compressed_thread["summary_message_id"]

        branch_response = client.post(f"/api/agent/threads/{thread['id']}/branches", json={})
        assert branch_response.status_code == 200
        branch = branch_response.json()["thread"]
        assert branch["parent_thread_id"] == thread["id"]
        assert branch["branch_depth"] == 1
        assert branch["summary"] == compressed_thread["summary"]
        assert len(branch_response.json()["messages"]) == len(
            compressed["conversation_context"]["recent_messages"]
        )

        listed = client.get(f"/api/agent/threads?project_id={project_id}").json()["threads"]
        assert {item["id"] for item in listed} == {thread["id"], branch["id"]}


def test_workflow_agent_budget_config_defaults_and_bounds() -> None:
    defaults = normalize_llm_use_cases({})["workflow_agent"]
    assert defaults["contextWindowTokens"] == 128000
    assert defaults["reservedOutputTokens"] == 12000
    assert defaults["compressionThreshold"] == 0.8
    assert defaults["compressionTarget"] == 0.2
    assert defaults["recentMessagesToKeep"] == 8

    normalized = normalize_llm_use_cases(
        {
            "llmUseCases": {
                "workflow_agent": {
                    "contextWindowTokens": 100,
                    "reservedOutputTokens": 999999,
                    "compressionThreshold": 0.1,
                    "compressionTarget": 0.9,
                    "recentMessagesToKeep": 100,
                }
            }
        }
    )["workflow_agent"]
    assert normalized["contextWindowTokens"] == 16000
    assert normalized["reservedOutputTokens"] == 8000
    assert normalized["compressionThreshold"] == 0.5
    assert normalized["compressionTarget"] == 0.5
    assert normalized["recentMessagesToKeep"] == 30


def test_workflow_agent_budget_config_persists_through_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        saved = client.put(
            "/api/config/apis",
            json={
                "data": {
                    "llmUseCases": {
                        "workflow_agent": {
                            "model": "agent-model",
                            "temperature": 0.15,
                            "maxTokens": 24000,
                            "timeoutSeconds": 90,
                            "contextWindowTokens": 64000,
                            "reservedOutputTokens": 6000,
                            "compressionThreshold": 0.75,
                            "compressionTarget": 0.2,
                            "recentMessagesToKeep": 6,
                        }
                    }
                }
            },
        )
        assert saved.status_code == 200
        reloaded = client.get("/api/config/apis")
        assert reloaded.status_code == 200
        config = reloaded.json()["data"]["llmUseCases"]["workflow_agent"]
        assert config == {
            "model": "agent-model",
            "temperature": 0.15,
            "maxTokens": 24000,
            "timeoutSeconds": 90,
            "contextWindowTokens": 64000,
            "reservedOutputTokens": 6000,
            "compressionThreshold": 0.75,
            "compressionTarget": 0.2,
            "recentMessagesToKeep": 6,
        }


def test_entity_profile_search_and_large_result_reference_are_project_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_a = client.post("/api/projects", json={"name": "引用项目 A", "category": "active"}).json()["id"]
        project_b = client.post("/api/projects", json={"name": "引用项目 B", "category": "active"}).json()["id"]
        profile = app.state.services.asset_production_repository.upsert_profile(
            project_a,
            {
                "canonical_name": "春潮香铺",
                "type": "scene",
                "aliases": ["老香铺"],
                "setting": "完整设定仅按需返回",
            },
        )
        search = client.post(
            "/api/commands/execute",
            json={
                "command": "entity-profile.search",
                "arguments": {"project_id": project_a, "query": "老香"},
            },
        )
        assert search.status_code == 200
        assert search.json()["data"]["matches"][0]["id"] == profile["id"]

        service = app.state.services.workflow_agent
        repository = service.repository
        thread = repository.create_thread(project_a, None)
        run = repository.create_run(thread["id"], "读取完整剧本")
        call = repository.add_tool_call(run["id"], "script.show", {"project_id": project_a}, "none")
        result = {
            "ok": True,
            "command": "script.show",
            "data": {"scripts": [{"segment_id": "seg_1", "content": "剧本正文" * 5000}]},
        }
        repository.update_tool_call(call["id"], status="succeeded", result=result)
        observation = service._tool_observation(
            run["id"],
            {"command": "script.show", "arguments": {"project_id": project_a}, "tool_call_id": call["id"]},
            result,
        )
        assert observation["result_ref"] == f"agent-result://{run['id']}/{call['id']}"
        assert "result" not in observation

        read = client.post(
            "/api/commands/execute",
            json={
                "command": "agent-result.read",
                "arguments": {
                    "project_id": project_a,
                    "result_ref": observation["result_ref"],
                    "offset": 0,
                    "max_chars": 12000,
                },
            },
        )
        assert read.status_code == 200
        assert len(read.json()["data"]["content"]) == 12000
        read_observation = service._tool_observation(
            run["id"],
            {"command": "agent-result.read", "arguments": {}, "tool_call_id": "read_call"},
            read.json(),
        )
        assert "result" in read_observation
        assert "result_ref" not in read_observation

        denied = client.post(
            "/api/commands/execute",
            json={
                "command": "agent-result.read",
                "arguments": {"project_id": project_b, "result_ref": observation["result_ref"]},
            },
        )
        assert denied.status_code == 400
        assert "不得跨项目" in denied.json()["detail"]


def test_visual_style_commands_create_and_version_asset_generation_style(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AVM_AUTH_DISABLED", "1")
    app = create_app(str(tmp_path / "database" / "app.db"))

    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects", json={"name": "资产风格工具", "category": "active"}
        ).json()["id"]
        created = client.post(
            "/api/commands/execute",
            json={
                "command": "visual-style.save",
                "arguments": {
                    "project_id": project_id,
                    "name": "现代国漫",
                    "prompt": "现代都市，精致国漫电影质感",
                    "negative_prompt": "低清晰度",
                    "is_active": True,
                },
                "confirmed": True,
            },
        )
        assert created.status_code == 200
        assert created.json()["effects"] == ["asset-production", "projects"]
        first = created.json()["data"]["style"]
        assert first["version"] == 1
        assert first["is_active"] is True

        updated = client.post(
            "/api/commands/execute",
            json={
                "command": "visual-style.save",
                "arguments": {
                    "project_id": project_id,
                    "style_id": first["id"],
                    "name": "现代国漫",
                    "prompt": "现代都市，更明亮、干净、克制",
                    "negative_prompt": "低清晰度，脏乱背景",
                    "is_active": True,
                },
                "confirmed": True,
            },
        )
        assert updated.status_code == 200
        second = updated.json()["data"]["style"]
        assert second["id"] != first["id"]
        assert second["version"] == 2

        listed = client.post(
            "/api/commands/execute",
            json={
                "command": "visual-style.list",
                "arguments": {"project_id": project_id},
            },
        )
        styles = listed.json()["data"]["styles"]
        assert styles[0]["id"] == second["id"]
        assert styles[0]["prompt"] == "现代都市，更明亮、干净、克制"
        assert len(styles) == 2
