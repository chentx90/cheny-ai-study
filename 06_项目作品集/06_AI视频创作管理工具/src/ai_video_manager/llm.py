from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from .openai_gateway import normalize_openai_base_url


LLM_USE_CASES: dict[str, str] = {
    "split_planning": "AI 切分建议 / 剧情时长切分",
    "script_convert": "剧本转换",
    "entity_extract": "实体提取",
    "entity_consolidate": "实体跨集聚合",
    "entity_setting": "实体设定生成",
    "character_asset_prompt": "人物资产提示词",
    "scene_asset_prompt": "场景资产提示词",
    "prop_asset_prompt": "物品资产提示词",
    "subject_match": "主体匹配",
    "prompt_split": "提示词剧情切分",
    "video_generate": "视频生成提示词",
    "prompt_rerun": "提示词单卡重跑",
    "video_agent": "视频生成助手 Agent",
    "workflow_agent": "项目工作流 Agent",
}

JSON_MODE_USE_CASES = {
    "prompt_split", "video_generate", "prompt_rerun", "entity_extract", "entity_consolidate",
    "entity_setting", "character_asset_prompt", "scene_asset_prompt", "prop_asset_prompt", "subject_match",
    "workflow_agent",
}
LONG_PROMPT_USE_CASES = {"prompt_split", "video_generate", "prompt_rerun"}


def default_llm_use_cases(default_model: str = "") -> dict[str, dict[str, object]]:
    result = {
        use_case: {
            "model": default_model,
            "temperature": 0.2
            if use_case not in LONG_PROMPT_USE_CASES | {"subject_match"}
            else (0.1 if use_case == "subject_match" else (0.3 if use_case == "prompt_split" else 0.6)),
            "maxTokens": 100000,
            "timeoutSeconds": 180 if use_case in LONG_PROMPT_USE_CASES else 120,
        }
        for use_case in LLM_USE_CASES
    }
    result["workflow_agent"].update(
        {
            "contextWindowTokens": 128000,
            "reservedOutputTokens": 12000,
            "compressionThreshold": 0.8,
            "compressionTarget": 0.2,
            "recentMessagesToKeep": 8,
        }
    )
    return result


def normalize_llm_use_cases(config: dict[str, object]) -> dict[str, dict[str, object]]:
    default_model = str(config.get("llmDefaultModel") or "")
    incoming = config.get("llmUseCases") if isinstance(config.get("llmUseCases"), dict) else {}
    normalized = default_llm_use_cases(default_model)
    for use_case in LLM_USE_CASES:
        raw = incoming.get(use_case) if isinstance(incoming, dict) and isinstance(incoming.get(use_case), dict) else {}
        inherited_model = ""
        if use_case == "workflow_agent" and isinstance(incoming, dict):
            script_config = incoming.get("script_convert")
            if isinstance(script_config, dict):
                inherited_model = str(script_config.get("model") or "")
        normalized_use_case = {
            "model": str(raw.get("model") or normalized[use_case]["model"] or default_model or inherited_model),
            "temperature": _bounded_float(raw.get("temperature"), 0, 2, float(normalized[use_case]["temperature"])),
            "maxTokens": _bounded_int(raw.get("maxTokens"), 1, 200000, int(normalized[use_case]["maxTokens"])),
            "timeoutSeconds": _bounded_int(raw.get("timeoutSeconds"), 5, 600, int(normalized[use_case]["timeoutSeconds"])),
        }
        if use_case == "workflow_agent":
            defaults = normalized[use_case]
            context_window_tokens = _bounded_int(
                raw.get("contextWindowTokens"), 16000, 2000000,
                int(defaults["contextWindowTokens"]),
            )
            max_reserved_output = min(200000, context_window_tokens // 2)
            normalized_use_case.update(
                {
                    "contextWindowTokens": context_window_tokens,
                    "reservedOutputTokens": _bounded_int(
                        raw.get("reservedOutputTokens"), 1000, max_reserved_output,
                        min(int(defaults["reservedOutputTokens"]), max_reserved_output),
                    ),
                    "compressionThreshold": _bounded_float(
                        raw.get("compressionThreshold"), 0.5, 0.98,
                        float(defaults["compressionThreshold"]),
                    ),
                    "compressionTarget": _bounded_float(
                        raw.get("compressionTarget"), 0.05, 0.5,
                        float(defaults["compressionTarget"]),
                    ),
                    "recentMessagesToKeep": _bounded_int(
                        raw.get("recentMessagesToKeep"), 2, 30,
                        int(defaults["recentMessagesToKeep"]),
                    ),
                }
            )
        normalized[use_case] = normalized_use_case
    return normalized


def llm_use_case_config(config: dict[str, object], use_case: str) -> dict[str, object]:
    use_cases = normalize_llm_use_cases(config)
    return use_cases.get(use_case) or use_cases["script_convert"]


def build_llm_client(config: dict[str, object], use_case: str) -> LLMClient:
    use_config = llm_use_case_config(config, use_case)
    provider = str(config.get("llmProvider") or "newapi")
    return LangGraphLLMClient(
        provider=provider,
        base_url=str(config.get("llmBaseUrl") or ""),
        api_key=str(config.get("llmApiKey") or ""),
        model=str(use_config.get("model") or config.get("llmDefaultModel") or ""),
        timeout_seconds=int(use_config.get("timeoutSeconds") or 120),
        default_max_tokens=int(use_config.get("maxTokens") or 100000),
        json_mode=use_case in JSON_MODE_USE_CASES,
    )


class LLMClient(Protocol):
    provider: str
    model: str

    def test_connection(self) -> dict[str, object]:
        ...

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 100000,
        system_prompt: str = "",
        json_mode: bool | None = None,
    ) -> str:
        ...


class _ChatState(TypedDict, total=False):
    messages: list[BaseMessage]
    response: BaseMessage


@dataclass
class LangGraphLLMClient:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 120
    default_max_tokens: int = 100000
    json_mode: bool = False

    def test_connection(self) -> dict[str, object]:
        if not self.base_url.strip() or not self.api_key.strip() or not self.model.strip():
            return {"ok": False, "detail": "需要 Base URL、API Key 和模型名"}
        try:
            # 连通性探测用小上限，避免把使用点的 maxTokens（可到 10 万）带进探测请求
            content = self.complete(
                "Reply with exactly: OK",
                temperature=0,
                max_tokens=64,
                json_mode=False,
            )
        except RuntimeError as exc:
            return {"ok": False, "detail": f"聊天补全测试失败：{exc}"}
        if not content.strip():
            return {"ok": False, "detail": "聊天补全测试返回为空"}
        return {"ok": True, "detail": "服务可达，聊天补全可用"}

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 100000,
        system_prompt: str = "",
        json_mode: bool | None = None,
    ) -> str:
        if not self.base_url.strip() or not self.api_key.strip() or not self.model.strip():
            raise RuntimeError("LLM 配置不完整：需要 Base URL、API Key 和模型名")
        request_max_tokens = _bounded_int(max_tokens, 1, 200000, self.default_max_tokens)
        use_json_mode = self.json_mode if json_mode is None else json_mode
        messages: list[BaseMessage] = []
        if system_prompt.strip():
            messages.append(SystemMessage(content=system_prompt.strip()))
        messages.append(HumanMessage(content=prompt))
        try:
            response = self._invoke_messages(
                messages,
                temperature=temperature,
                max_tokens=request_max_tokens,
                json_mode=use_json_mode,
            )
        except Exception as exc:
            if use_json_mode and _is_response_format_error(exc):
                try:
                    response = self._invoke_messages(
                        messages,
                        temperature=temperature,
                        max_tokens=request_max_tokens,
                        json_mode=False,
                    )
                except Exception as fallback_exc:
                    raise _wrap_llm_error(fallback_exc, self) from fallback_exc
            else:
                raise _wrap_llm_error(exc, self) from exc
        content = _message_content(response)
        if not content.strip():
            raise RuntimeError(_empty_content_detail(response, self.model))
        return content.strip()

    def _invoke_messages(
        self,
        messages: list[BaseMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> BaseMessage:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "base_url": _normalize_base_url(self.provider, self.base_url),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": self.timeout_seconds,
            "max_retries": 3,
        }
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        chat = ChatOpenAI(**kwargs)

        def call_model(state: _ChatState) -> _ChatState:
            return {"response": chat.invoke(state["messages"])}

        graph = StateGraph(_ChatState)
        graph.add_node("llm", call_model)
        graph.add_edge(START, "llm")
        graph.add_edge("llm", END)
        compiled = graph.compile()
        state = compiled.invoke({"messages": messages})
        return state["response"]


def parse_json_array(text: str) -> list[object]:
    stripped = _strip_markdown_json(text)
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    parsed = json.loads(stripped)
    if not isinstance(parsed, list):
        raise RuntimeError("LLM 返回不是数组")
    return parsed


_JSON_LIST_WRAPPER_KEYS = (
    "matches",
    "results",
    "items",
    "data",
    "entities",
    "entity_cards",
    "subject_matches",
    "cards",
    "list",
)


def parse_json_list_payload(text: str) -> list[object]:
    """Parse LLM output that may be a JSON array or a json_object-mode wrapper."""
    stripped = _strip_markdown_json(text)
    obj_start = stripped.find("{")
    obj_end = stripped.rfind("}")
    if obj_start >= 0 and obj_end >= obj_start:
        try:
            parsed_obj = json.loads(stripped[obj_start : obj_end + 1])
        except json.JSONDecodeError:
            parsed_obj = None
        if isinstance(parsed_obj, dict):
            if "entity_card_id" in parsed_obj or "entityCardId" in parsed_obj:
                return [parsed_obj]
            for key in _JSON_LIST_WRAPPER_KEYS:
                value = parsed_obj.get(key)
                if isinstance(value, list):
                    return value
            raise RuntimeError(
                'LLM 返回格式无效：需要 JSON 数组，或形如 {"matches":[{"entity_card_id":"...","reason":"..."}]} 的对象'
            )
    return parse_json_array(text)


def parse_json_object(text: str) -> dict[str, object]:
    stripped = _strip_markdown_json(text)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        repaired = _try_repair_json(stripped)
        if repaired is None:
            raise ValueError(f"LLM 返回不是合法 JSON：{exc}") from exc
        parsed = repaired
    if not isinstance(parsed, dict):
        raise ValueError("LLM 返回不是 JSON 对象")
    return parsed


def _try_repair_json(text: str) -> dict[str, object] | None:
    try:
        from json_repair import repair_json
    except ImportError:
        return None
    try:
        repaired = repair_json(text, return_objects=True)
    except Exception:
        return None
    return repaired if isinstance(repaired, dict) else None


def _strip_markdown_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.split("\n", 1)[-1].strip()
    return stripped


def _normalize_base_url(provider: str, base_url: str) -> str:
    return normalize_openai_base_url(provider, base_url)


def _wrap_llm_error(exc: BaseException, client: LangGraphLLMClient) -> RuntimeError:
    if _is_timeout_error(exc):
        return RuntimeError(
            f"LLM 调用超时（{client.timeout_seconds} 秒）：Base URL："
            f"{_normalize_base_url(client.provider, client.base_url)}；模型：{client.model}"
        )
    return RuntimeError(
        f"LLM 调用失败：{exc}；Base URL："
        f"{_normalize_base_url(client.provider, client.base_url)}；模型：{client.model}；"
        f"超时：{client.timeout_seconds} 秒"
    )


def _message_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    text = _content_to_text(content)
    if text.strip():
        return text

    return ""


def _content_to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _empty_content_detail(message: BaseMessage, model: str) -> str:
    metadata = getattr(message, "response_metadata", {}) or {}
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    finish_reason = metadata.get("finish_reason") if isinstance(metadata, dict) else None
    token_usage = {}
    if isinstance(metadata, dict):
        token_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    usage_text = ""
    if isinstance(token_usage, dict) and token_usage:
        usage_text = (
            f"；completion_tokens={token_usage.get('completion_tokens')}"
            f"；reasoning_tokens={_reasoning_token_count(token_usage)}"
        )
    refusal = ""
    if isinstance(additional_kwargs, dict) and additional_kwargs.get("refusal") is not None:
        refusal_value = additional_kwargs.get("refusal")
        refusal = f"；refusal={refusal_value!r}" if refusal_value not in ("", None) else "；含 refusal 字段（模型拒绝输出正文）"
    elif isinstance(metadata, dict) and metadata.get("refusal") is not None:
        refusal = f"；refusal={metadata.get('refusal')!r}"
    keys = sorted(additional_kwargs.keys()) if isinstance(additional_kwargs, dict) else []
    hint = ""
    if "refusal" in keys or (isinstance(metadata, dict) and metadata.get("refusal") is not None):
        hint = "。常见原因：网关/模型安全策略拒绝、或该模型把内容放在 reasoning/refusal 而非 content；可换模型或关闭敏感提示后重试"
    return (
        "LLM 返回内容为空："
        f"finish_reason={finish_reason}；additional_kwargs 字段={keys}"
        f"{refusal}{usage_text}；模型：{model}{hint}"
    )


def _reasoning_token_count(token_usage: dict[str, Any]) -> object:
    details = token_usage.get("completion_tokens_details")
    if isinstance(details, dict):
        return details.get("reasoning_tokens")
    return None


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, TimeoutError):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _is_response_format_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "response_format" in text or "json_object" in text


def _bounded_float(value: object, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(number, minimum), maximum)


def _bounded_int(value: object, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(number, minimum), maximum)
