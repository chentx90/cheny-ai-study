from __future__ import annotations

import json
from typing import Any

from ai_video_manager.agent.graph import build_agent_graph
from ai_video_manager.agent.repository import AgentRepository
from ai_video_manager.api.config import _load_api_config
from ai_video_manager.commands import CommandContext
from ai_video_manager.llm import build_llm_client, llm_use_case_config, parse_json_object
from ai_video_manager.prompt_engine import request_template_for_category


MAX_REACT_STEPS = 12
MAX_CONVERSATION_SUMMARY_CHARS = 14000
DEFAULT_RECENT_MESSAGES_TO_KEEP = 8
ENTITY_PROFILE_INDEX_LIMIT = 100
TOOL_RESULT_INLINE_CHARS = 12000
APPROVAL_MODES = {"manual", "project", "trusted"}
PROJECT_AUTO_APPROVALS = {"none", "write", "llm", "overwrite"}


class WorkflowAgentService:
    def __init__(self, services) -> None:
        self.services = services
        self.store = services.store
        self.bus = services.command_bus
        self.repository = AgentRepository(self.store)
        self.graph = build_agent_graph(self)

    def create_thread(self, project_id: str, user_id: str | None, title: str = "项目助手") -> dict[str, Any]:
        existing = self.repository.list_threads(project_id, user_id)
        return existing[0] if existing else self.repository.create_thread(project_id, user_id, title)

    def thread_detail(self, thread_id: str) -> dict[str, Any]:
        run = self.repository.latest_run_for_thread(thread_id)
        return {
            "thread": self.repository.get_thread(thread_id),
            "messages": self.repository.list_messages(thread_id),
            "run": run,
            "tool_calls": self.repository.list_tool_calls(run["id"]) if run else [],
        }

    def list_threads(self, project_id: str, user_id: str | None) -> list[dict[str, Any]]:
        return self.repository.list_threads(project_id, user_id)

    def create_branch(
        self,
        thread_id: str,
        user_id: str | None,
        *,
        title: str = "",
        from_message_id: str | None = None,
    ) -> dict[str, Any]:
        return self.repository.create_branch(
            thread_id,
            user_id,
            title=title,
            from_message_id=from_message_id,
        )

    def send_message(
        self,
        thread_id: str,
        user_id: str | None,
        content: str,
        ui_context: dict[str, Any] | None = None,
        approval_mode: str = "manual",
    ) -> dict[str, Any]:
        thread = self.repository.get_thread(thread_id)
        message = content.strip()
        if not message:
            raise ValueError("消息不能为空")
        normalized_approval = self._normalize_approval_mode(approval_mode)
        user_message = self.repository.add_message(
            thread_id,
            "user",
            message,
            {"ui_context": ui_context or {}, "approval_mode": normalized_approval},
        )
        conversation_context = self._prepare_conversation_context(thread_id, exclude_message_id=user_message["id"])
        run = self.repository.create_run(thread_id, message)
        self.repository.add_event(run["id"], "run_started", {"run_id": run["id"]})
        initial = {
            "run_id": run["id"],
            "thread_id": thread_id,
            "project_id": thread["project_id"],
            "user_id": user_id,
            "user_request": message,
            "current_view": str((ui_context or {}).get("current_view") or ""),
            "active_context": (ui_context or {}).get("active_context") or {},
            "approval_mode": normalized_approval,
            "conversation_context": conversation_context,
            "command_history": [],
            "observations": [],
            "step": 0,
            "react_mode": True,
            "done": False,
        }
        try:
            state = self.graph.invoke(initial)
        except Exception as exc:
            failed = {**initial, "status": "failed", "message": str(exc), "commands": [], "results": []}
            self.repository.update_run(run["id"], status="failed", state=failed)
            self.repository.add_message(thread_id, "assistant", f"操作失败：{exc}", {"run_id": run["id"], "status": "failed"})
            self.repository.add_event(run["id"], "run_failed", {"detail": str(exc)})
            return self.run_detail(run["id"])
        waiting = bool(state.get("requires_confirmation"))
        status = "waiting_approval" if waiting else state.get("status") or "completed"
        self.repository.update_run(run["id"], status=status, state=state, waiting=waiting)
        if waiting:
            self.repository.add_message(
                thread_id,
                "assistant",
                state.get("message") or "需要确认后执行",
                {
                    "run_id": run["id"],
                    "status": status,
                    "commands": state.get("command_history") or state.get("commands") or [],
                    "results": state.get("results") or [],
                    "observations": state.get("observations") or [],
                },
            )
            self.repository.add_event(run["id"], "approval_required", {"commands": state.get("commands") or []})
        else:
            self._complete_message(thread_id, run["id"], state)
        return self.run_detail(run["id"])

    def approve_run(self, run_id: str, user_id: str | None) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        if run["status"] != "waiting_approval":
            raise ValueError("当前任务不在待确认状态")
        state = run["state"]
        state["user_id"] = user_id
        self.repository.add_event(run_id, "approval_granted", {})
        try:
            executed = self.execute_node(state)
            state = {**state, **executed, "commands": [], "requires_confirmation": False, "done": False}
            if state.get("react_mode"):
                self.repository.add_event(run_id, "react_resumed", {"step": state.get("step", 0)})
                state = self.graph.invoke(state)
            thread_id = run["thread_id"]
            waiting = bool(state.get("requires_confirmation"))
            status = "waiting_approval" if waiting else "completed"
            self.repository.update_run(run_id, status=status, state=state, waiting=waiting)
            if waiting:
                self.repository.add_message(
                    thread_id,
                    "assistant",
                    state.get("message") or "下一步操作需要确认",
                    {
                        "run_id": run_id,
                        "status": status,
                        "commands": state.get("command_history") or state.get("commands") or [],
                        "results": state.get("results") or [],
                        "observations": state.get("observations") or [],
                    },
                )
                self.repository.add_event(run_id, "approval_required", {"commands": state.get("commands") or []})
            else:
                self._complete_message(thread_id, run_id, state)
        except Exception as exc:
            state.update({"status": "failed", "message": str(exc)})
            self.repository.update_run(run_id, status="failed", state=state, waiting=False)
            self.repository.add_message(run["thread_id"], "assistant", f"执行失败：{exc}", {"run_id": run_id, "status": "failed"})
            self.repository.add_event(run_id, "run_failed", {"detail": str(exc)})
        return self.run_detail(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        state = run["state"]
        state["status"] = "cancelled"
        self.repository.update_run(run_id, status="cancelled", state=state, waiting=False)
        self.repository.cancel_pending_tool_calls(run_id)
        self.repository.update_message_status_for_run(run["thread_id"], run_id, "cancelled")
        self.repository.add_event(run_id, "run_cancelled", {})
        return self.run_detail(run_id)

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        return {
            "thread": self.repository.get_thread(run["thread_id"]),
            "messages": self.repository.list_messages(run["thread_id"]),
            "run": run,
            "tool_calls": self.repository.list_tool_calls(run_id),
        }

    def load_context_node(self, state: dict[str, Any]) -> dict[str, Any]:
        project_id = state["project_id"]
        workspace = self.bus.execute(
            "workflow.status",
            {"project_id": project_id},
            CommandContext(self.services, user_id=state.get("user_id"), source="agent"),
        )["data"]
        repository = self.services.asset_production_repository
        profiles = repository.list_profiles(project_id)
        prompts = repository.list_asset_prompts(project_id)
        styles = repository.list_visual_styles(project_id)
        presets = repository.list_presets(project_id)
        image_tasks = repository.list_image_tasks(project_id)
        self.repository.add_event(state["run_id"], "context_loaded", {"project_id": project_id})
        return {
            **state,
            "project_context": self._compact_project_context(
                workspace,
                {
                    "profiles": profiles,
                    "prompts": prompts,
                    "styles": styles,
                    "presets": presets,
                    "image_tasks": image_tasks,
                },
            ),
        }

    def plan_node(self, state: dict[str, Any]) -> dict[str, Any]:
        step = int(state.get("step") or 0) + 1
        if step > MAX_REACT_STEPS:
            message = f"已达到单轮最多 {MAX_REACT_STEPS} 次工具调用，已停止继续执行。请缩小任务范围后重试。"
            self.repository.add_event(state["run_id"], "react_limit_reached", {"step": step})
            return {
                **state,
                "step": step,
                "message": message,
                "commands": [],
                "requires_confirmation": False,
                "done": True,
                "status": "completed",
            }
        config = _load_api_config(self.store, user_id=state.get("user_id"))
        use_config = llm_use_case_config(config, "workflow_agent")
        template = request_template_for_category(self.services.prompt_engine, "workflow_agent", None)
        catalog = self.bus.catalog()
        state = self._apply_context_budget(
            {**state, "step": step}, template, use_config, catalog
        )
        prompt = self._render_agent_prompt(state, template, catalog)
        raw = build_llm_client(config, "workflow_agent").complete(
            prompt,
            temperature=float(use_config.get("temperature") or 0.1),
            max_tokens=int(use_config.get("maxTokens") or 100000),
            json_mode=True,
        )
        plan = parse_json_object(raw)
        react_payload = plan.get("action")
        is_react_response = "action" in plan or "done" in plan
        if is_react_response:
            incoming = [react_payload] if isinstance(react_payload, dict) and react_payload.get("command") else []
            commands = self._validate_commands(incoming, state["project_id"])
            done = bool(plan.get("done")) or not commands
            react_mode = True
        else:
            commands = self._validate_commands(plan.get("commands") or [], state["project_id"])
            done = not commands
            react_mode = False
        for command in commands:
            spec = self.bus.registry[command["command"]]
            call = self.repository.add_tool_call(state["run_id"], command["command"], command["arguments"], spec.confirmation)
            command["tool_call_id"] = call["id"]
            command["confirmation"] = spec.confirmation
            command["cli_preview"] = self._cli_preview(command["command"], command["arguments"], spec.confirmation)
        requires_confirmation = any(
            self._requires_confirmation(
                self.bus.registry[item["command"]].confirmation,
                state.get("approval_mode"),
            )
            for item in commands
        )
        command_history = [*(state.get("command_history") or []), *commands]
        self.repository.add_event(
            state["run_id"],
            "react_step_planned" if react_mode else "plan_created",
            {"step": step, "message": plan.get("message") or "", "commands": commands, "done": done},
        )
        return {
            **state,
            "step": step,
            "message": str(plan.get("message") or ""),
            "commands": commands,
            "command_history": command_history,
            "requires_confirmation": requires_confirmation,
            "react_mode": react_mode,
            "done": done,
            "status": "completed" if done else "running",
        }

    def execute_node(self, state: dict[str, Any]) -> dict[str, Any]:
        results = list(state.get("results") or [])
        observations = list(state.get("observations") or [])
        context = CommandContext(self.services, user_id=state.get("user_id"), source="agent")
        for item in state.get("commands") or []:
            call_id = item.get("tool_call_id")
            self.repository.add_event(state["run_id"], "tool_call_started", {"command": item["command"], "tool_call_id": call_id})
            try:
                result = self.bus.execute(item["command"], item["arguments"], context)
            except Exception as exc:
                if call_id:
                    self.repository.update_tool_call(call_id, status="failed", error=str(exc))
                raise
            if call_id:
                self.repository.update_tool_call(call_id, status="succeeded", result=result)
            results.append(result)
            observations.append(self._tool_observation(state["run_id"], item, result))
            self.repository.add_event(state["run_id"], "tool_call_result", {"command": item["command"], "tool_call_id": call_id, "result": result})
        return {
            **state,
            "commands": [],
            "results": results,
            "observations": observations[-MAX_REACT_STEPS:],
            "status": "running" if state.get("react_mode") else "completed",
            "requires_confirmation": False,
            "done": False,
        }

    @staticmethod
    def _tool_observation(
        run_id: str, command: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        call_id = str(command.get("tool_call_id") or "")
        command_id = str(command.get("command") or "")
        if (
            len(serialized) > TOOL_RESULT_INLINE_CHARS
            and call_id
            and command_id != "agent-result.read"
        ):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            summary = WorkflowAgentService._result_summary(command_id, data)
            return {
                "command": command.get("command", ""),
                "arguments": command.get("arguments") or {},
                "result_ref": f"agent-result://{run_id}/{call_id}",
                "summary": summary,
                "chars": len(serialized),
            }
        return {
            "command": command.get("command", ""),
            "arguments": command.get("arguments") or {},
            "result": serialized,
        }

    @staticmethod
    def _result_summary(command_id: str, data: dict[str, Any]) -> str:
        if command_id == "script.show":
            scripts = data.get("scripts") if isinstance(data.get("scripts"), list) else []
            total_chars = sum(
                len(str(item.get("content") or "")) for item in scripts if isinstance(item, dict)
            )
            return f"读取 {len(scripts)} 集剧本，共 {total_chars} 字"
        if command_id in {"entity-profile.list", "entity-profile.search"}:
            rows = data.get("profiles") or data.get("matches") or []
            return f"返回 {len(rows) if isinstance(rows, list) else 0} 个实体档案"
        if command_id == "file.read":
            return f"读取文件 {data.get('path') or ''}，共 {data.get('bytes') or 0} 字节"
        keys = ", ".join(str(key) for key in list(data.keys())[:12])
        return f"{command_id} 返回字段：{keys or '无'}"

    def _prepare_conversation_context(
        self, thread_id: str, *, exclude_message_id: str | None = None
    ) -> dict[str, Any]:
        thread = self.repository.get_thread(thread_id)
        messages = [
            message for message in self.repository.list_messages(thread_id)
            if message["id"] != exclude_message_id
        ]
        marker = str(thread.get("summary_message_id") or "")
        if marker:
            marker_index = next(
                (index for index, message in enumerate(messages) if message["id"] == marker),
                None,
            )
            unsummarized = messages[marker_index + 1 :] if marker_index is not None else messages
        else:
            unsummarized = messages
        summary = str(thread.get("summary") or "").strip()
        return {
            "thread": {
                "id": thread["id"],
                "title": thread["title"],
                "parent_thread_id": thread.get("parent_thread_id"),
                "branch_depth": int(thread.get("branch_depth") or 0),
            },
            "summary": summary,
            "recent_messages": [self._compact_conversation_message(message) for message in unsummarized],
        }

    def _apply_context_budget(
        self,
        state: dict[str, Any],
        template,
        use_config: dict[str, Any],
        catalog: list[dict[str, Any]],
    ) -> dict[str, Any]:
        context_window = int(use_config.get("contextWindowTokens") or 128000)
        reserved_output = min(
            int(use_config.get("reservedOutputTokens") or 12000),
            max(1000, context_window // 2),
        )
        threshold_tokens = int(
            context_window * float(use_config.get("compressionThreshold") or 0.8)
        )
        target_tokens = int(
            context_window * float(use_config.get("compressionTarget") or 0.2)
        )
        keep_count = int(
            use_config.get("recentMessagesToKeep") or DEFAULT_RECENT_MESSAGES_TO_KEEP
        )
        prompt = self._render_agent_prompt(state, template, catalog)
        before_tokens = self._estimate_tokens(prompt)
        budget = {
            "context_window_tokens": context_window,
            "reserved_output_tokens": reserved_output,
            "compression_threshold_tokens": threshold_tokens,
            "compression_target_tokens": target_tokens,
            "estimated_input_tokens_before": before_tokens,
            "estimated_input_tokens_after": before_tokens,
            "compressed": False,
            "compressed_messages": 0,
        }
        if before_tokens + reserved_output < threshold_tokens:
            return {**state, "context_budget": budget}

        conversation = dict(state.get("conversation_context") or {})
        messages = list(conversation.get("recent_messages") or [])
        if len(messages) <= keep_count:
            budget["compression_limited"] = "recent_message_floor"
            return {**state, "context_budget": budget}

        thread_id = str((conversation.get("thread") or {}).get("id") or state.get("thread_id") or "")
        full_messages = {
            message["id"]: message for message in self.repository.list_messages(thread_id)
        }
        summary = str(conversation.get("summary") or "").strip()
        compressed_ids: list[str] = []
        next_state = state
        while len(messages) > keep_count:
            compact = messages.pop(0)
            message_id = str(compact.get("id") or "")
            full = full_messages.get(message_id)
            if full is not None:
                summary = self._merge_conversation_summary(summary, [full])
                compressed_ids.append(message_id)
            conversation = {**conversation, "summary": summary, "recent_messages": messages}
            next_state = {**state, "conversation_context": conversation}
            after_tokens = self._estimate_tokens(
                self._render_agent_prompt(next_state, template, catalog)
            )
            if after_tokens <= target_tokens:
                break

        after_tokens = self._estimate_tokens(
            self._render_agent_prompt(next_state, template, catalog)
        )
        if compressed_ids:
            self.repository.update_thread_summary(thread_id, summary, compressed_ids[-1])
            self.repository.add_event(
                state["run_id"],
                "context_compressed",
                {
                    "before_tokens": before_tokens,
                    "after_tokens": after_tokens,
                    "target_tokens": target_tokens,
                    "message_count": len(compressed_ids),
                },
            )
        budget.update(
            {
                "estimated_input_tokens_after": after_tokens,
                "compressed": bool(compressed_ids),
                "compressed_messages": len(compressed_ids),
            }
        )
        if after_tokens > target_tokens:
            budget["compression_limited"] = "fixed_context_or_recent_message_floor"
        return {**next_state, "context_budget": budget}

    def _render_agent_prompt(
        self,
        state: dict[str, Any],
        template,
        catalog: list[dict[str, Any]],
    ) -> str:
        return self.services.prompt_engine.render_prompt(
            template,
            {
                "user_request": state["user_request"],
                "project_context": json.dumps(
                    state.get("project_context") or {}, ensure_ascii=False, default=str
                ),
                "current_view": state.get("current_view") or "",
                "active_context": json.dumps(
                    state.get("active_context") or {}, ensure_ascii=False
                ),
                "command_catalog": json.dumps(catalog, ensure_ascii=False),
                "observations": json.dumps(
                    state.get("observations") or [], ensure_ascii=False, default=str
                ),
                "step": state.get("step") or 0,
                "conversation_context": json.dumps(
                    state.get("conversation_context") or {}, ensure_ascii=False, default=str
                ),
            },
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        ascii_chars = sum(1 for char in text if ord(char) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return max(1, (ascii_chars + 3) // 4 + non_ascii_chars)

    @staticmethod
    def _merge_conversation_summary(summary: str, messages: list[dict[str, Any]]) -> str:
        lines = [summary.strip()] if summary.strip() else []
        for message in messages:
            role = "用户" if message.get("role") == "user" else "Agent"
            content = " ".join(str(message.get("content") or "").split())
            if len(content) > 1200:
                content = f"{content[:1200]}..."
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            commands = metadata.get("commands") if isinstance(metadata.get("commands"), list) else []
            command_ids = [str(item.get("command") or "") for item in commands if isinstance(item, dict)]
            suffix = f"；工具：{', '.join(command_ids)}" if command_ids else ""
            lines.append(f"{role}：{content}{suffix}")
        merged = "\n".join(line for line in lines if line).strip()
        if len(merged) > MAX_CONVERSATION_SUMMARY_CHARS:
            merged = f"...较早摘要已裁剪...\n{merged[-MAX_CONVERSATION_SUMMARY_CHARS:]}"
        return merged

    @staticmethod
    def _compact_conversation_message(message: dict[str, Any]) -> dict[str, Any]:
        content = str(message.get("content") or "")
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        commands = metadata.get("commands") if isinstance(metadata.get("commands"), list) else []
        ui_context = metadata.get("ui_context") if isinstance(metadata.get("ui_context"), dict) else {}
        active_context = ui_context.get("active_context") if isinstance(ui_context.get("active_context"), dict) else {}
        attachments = active_context.get("attachments") if isinstance(active_context.get("attachments"), list) else []
        return {
            "id": message.get("id"),
            "role": message.get("role"),
            "content": content,
            "status": metadata.get("status"),
            "attachments": [
                {
                    "path": item.get("path"),
                    "filename": item.get("filename"),
                    "asset_type": item.get("asset_type"),
                }
                for item in attachments[:20]
                if isinstance(item, dict) and item.get("path")
            ],
            "commands": [
                {
                    "command": item.get("command"),
                    "reason": item.get("reason"),
                }
                for item in commands[:12]
                if isinstance(item, dict)
            ],
        }

    def _validate_commands(self, incoming: Any, project_id: str) -> list[dict[str, Any]]:
        if not isinstance(incoming, list):
            raise ValueError("Agent 命令计划必须是数组")
        commands = []
        for item in incoming[:20]:
            if not isinstance(item, dict):
                continue
            command_id = str(item.get("command") or "")
            spec = self.bus.registry.get(command_id)
            if spec is None:
                raise ValueError(f"Agent 请求了未授权命令：{command_id}")
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            if spec.requires_project:
                supplied = str(arguments.get("project_id") or project_id)
                if supplied != project_id:
                    raise ValueError("Agent 不得跨项目执行命令")
                arguments["project_id"] = project_id
            commands.append({"command": command_id, "arguments": arguments, "reason": str(item.get("reason") or "")})
        return commands

    @staticmethod
    def _normalize_approval_mode(value: Any) -> str:
        mode = str(value or "manual").strip().lower()
        return mode if mode in APPROVAL_MODES else "manual"

    @classmethod
    def _requires_confirmation(cls, confirmation: str, approval_mode: Any) -> bool:
        level = str(confirmation or "none")
        mode = cls._normalize_approval_mode(approval_mode)
        if level == "none":
            return False
        if mode == "trusted":
            return level == "destructive"
        if mode == "project":
            return level not in PROJECT_AUTO_APPROVALS
        return True

    def _complete_message(self, thread_id: str, run_id: str, state: dict[str, Any]) -> None:
        message = state.get("message") or ("操作已完成" if state.get("commands") else "已处理")
        self.repository.add_message(
            thread_id,
            "assistant",
            message,
            {
                "run_id": run_id,
                "status": "completed",
                "commands": state.get("command_history") or state.get("commands") or [],
                "results": state.get("results") or [],
                "observations": state.get("observations") or [],
            },
        )
        self.repository.add_event(run_id, "run_completed", {"message": message, "results": state.get("results") or []})

    @staticmethod
    def _cli_preview(command_id: str, arguments: dict[str, Any], confirmation: str) -> str:
        payload = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        suffix = " --yes" if confirmation in {"destructive", "overwrite", "llm", "external"} else ""
        return f"ai-video-manager run {command_id} --payload '{payload}'{suffix}"

    @staticmethod
    def _compact_project_context(
        value: dict[str, Any], asset_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        project = value.get("project") if isinstance(value.get("project"), dict) else {}
        workflow = value.get("workflow") if isinstance(value.get("workflow"), dict) else {}
        workspace = value.get("workspace") if isinstance(value.get("workspace"), dict) else {}
        segments = workspace.get("segments") if isinstance(workspace.get("segments"), list) else []
        scripts = workspace.get("scripts") if isinstance(workspace.get("scripts"), dict) else {}
        asset_context = asset_context or {}
        profiles = asset_context.get("profiles") if isinstance(asset_context.get("profiles"), list) else []
        prompts = asset_context.get("prompts") if isinstance(asset_context.get("prompts"), list) else []
        styles = asset_context.get("styles") if isinstance(asset_context.get("styles"), list) else []
        presets = asset_context.get("presets") if isinstance(asset_context.get("presets"), list) else []
        image_tasks = asset_context.get("image_tasks") if isinstance(asset_context.get("image_tasks"), list) else []
        latest_prompt_by_profile: dict[str, dict[str, Any]] = {}
        for prompt in prompts:
            profile_id = str(prompt.get("profile_id") or "") if isinstance(prompt, dict) else ""
            if profile_id and profile_id not in latest_prompt_by_profile:
                latest_prompt_by_profile[profile_id] = prompt
        latest_task_by_profile: dict[str, dict[str, Any]] = {}
        for task in image_tasks:
            profile_id = str(task.get("profile_id") or "") if isinstance(task, dict) else ""
            if profile_id and profile_id not in latest_task_by_profile:
                latest_task_by_profile[profile_id] = task
        active_style = next((item for item in styles if isinstance(item, dict) and item.get("is_active")), None)
        return {
            "project": project,
            "workflow": workflow,
            "workspace": {
                "revision": workspace.get("revision", 0),
                "active_segment_id": workspace.get("activeSegmentId", ""),
                "segment_count": len(segments),
                "script_count": sum(bool(str(content or "").strip()) for content in scripts.values()),
                "segments": [
                    {"id": item.get("id"), "order": item.get("order"), "title": item.get("title")}
                    for item in segments[:200]
                    if isinstance(item, dict)
                ],
                "content_type": workspace.get("contentType", ""),
                "project_style_prompt": workspace.get("projectStylePrompt", ""),
                "assets_confirmed": bool(workspace.get("assetsConfirmed")),
            },
            "entity_assets": {
                "profile_count": len(profiles),
                "type_counts": {
                    entity_type: sum(
                        1 for item in profiles
                        if isinstance(item, dict) and item.get("type") == entity_type
                    )
                    for entity_type in ("character", "scene", "prop")
                },
                "profile_index": [
                    {
                        "id": item.get("id"),
                        "name": item.get("canonical_name"),
                        "type": item.get("type"),
                        "status": item.get("status"),
                        "has_setting": bool(str(item.get("setting") or "").strip()),
                        "has_asset_prompt": bool(
                            latest_prompt_by_profile.get(str(item.get("id") or ""))
                        ),
                        "image_status": (
                            latest_task_by_profile.get(str(item.get("id") or "")) or {}
                        ).get("status"),
                    }
                    for item in profiles[:ENTITY_PROFILE_INDEX_LIMIT]
                    if isinstance(item, dict)
                ],
                "index_limit": ENTITY_PROFILE_INDEX_LIMIT,
                "index_truncated": len(profiles) > ENTITY_PROFILE_INDEX_LIMIT,
                "active_visual_style": {
                    "id": active_style.get("id"),
                    "name": active_style.get("name"),
                    "version": active_style.get("version"),
                } if active_style else None,
                "presets": [
                    {
                        "entity_type": item.get("entity_type"),
                        "provider": item.get("provider"),
                        "model": item.get("model"),
                        "size": item.get("size"),
                        "aspect_ratio": item.get("aspect_ratio"),
                    }
                    for item in presets
                    if isinstance(item, dict)
                ],
            },
        }
