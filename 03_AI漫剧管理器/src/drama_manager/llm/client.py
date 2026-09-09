"""
LangChain LLM 客户端封装。

职责:
  统一通过 NewAPI 中转调用大模型。
  NewAPI 提供 OpenAI 兼容接口，底层路由到 GPT/Claude/Qwen 等不同模型。

NewAPI 接口规范:
  - base_url: https://api.newapi.com/v1 (或自建实例地址)
  - api_key:  NewAPI 分配的密钥
  - 模型名:   NewAPI 后台配置的模型名称 (如 gpt-4o, deepseek-chat, qwen-plus)
  - 请求格式: 完全兼容 OpenAI Chat Completions API

JSON 输出:
  默认每次请求都带 response_format={"type": "json_object"}。
  不支持的厂商收到此参数后会直接忽略，不影响正常返回。
  如需关闭（如纯文本生成场景），传 json_mode=False。
"""
from langchain_openai import ChatOpenAI
from drama_manager.config import get_llm_config


def get_llm(
    model: str | None = None,
    temperature: float = 0.7,
    json_mode: bool = True,
):
    """
    返回通过 NewAPI 中转的 LLM 客户端。

    默认开启 json_mode，每次请求都带 response_format={"type": "json_object"}。
    不支持的厂商会忽略此参数，不影响返回结果。

    调用方式:
        llm = get_llm()                                    # 默认模型 + JSON 模式
        llm = get_llm(json_mode=False)                     # 关闭 JSON 模式
        llm = get_llm(model="deepseek-chat")               # 临时切换模型

    Args:
        model:       模型名称，None 则用 config.toml 默认值
        temperature: 生成温度 0.0-1.0
        json_mode:   是否默认开启 JSON 输出 (默认 True)

    Returns:
        ChatOpenAI 实例
    """
    cfg = get_llm_config()

    kwargs = {
        "model": model or cfg["model"],
        "api_key": cfg["api_key"],
        "base_url": cfg["base_url"],
        "temperature": temperature,
        # 网络抖动/限速时自动重试 (底层 openai SDK 指数退避)
        "max_retries": 3,
        # 单次请求超时 (秒)，长上下文模型处理长文较慢，给足时间
        "timeout": 300,
    }

    # 默认注入 response_format，不支持的厂商会忽略
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    return ChatOpenAI(**kwargs)
