"""
W22_Python_08 · Function Call 入门 demo
作者：cheny
日期：2026-05-26

完整跑通 OpenAI 兼容协议的 Function Call 4 步：
  1. 定义工具（Python 函数 + JSON Schema）
  2. LLM 看到用户问题决策调用工具
  3. 你执行工具拿到结果
  4. 把结果喂回 LLM，拿到最终自然语言回答
"""

import sys
import json
from pathlib import Path

# 让本文件能找到 06_项目作品集/01_日报摘要器 里的 LLMClient
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "06_项目作品集" / "01_日报摘要器"))
sys.path.insert(0, str(ROOT / "01_Python补强"))

from llm_client import LLMClient
from logger import Logger
from weather_api import get_weather_cached


log = Logger(file_path=Path("logs/tools_demo.log"), to_console=True)


# ============ 第 1 步：定义工具（虚拟版）============
# 先用假数据走通协议，之后再接真实 weather_api

def get_weather(city: str) -> dict:
    """虚拟天气查询。返回固定假数据。
    
    后面真正接入 W21 的 weather_api 时，这个函数会被替换。
    现在先用假数据，确保协议层完整跑通。
    """
    log.info(f"[工具执行] get_weather(city='{city}')")
    
    weather = get_weather_cached(city)
    if weather is None:
        return {"error": f"无法获取 {city} 的天气数据，可能网络异常或城市名无效"}

    return {
        "city": weather["city"],
        "temp_c": weather["temp_c"],
        "feels_like_c": weather["feels_like_c"],
        "weather": weather["weather_desc"],
        "humidity": weather["humidity"],
        "wind_kmph": weather["wind_speed_kmph"],
    }

# ============ Tool Schema（OpenAI 协议格式）============
# 这是 LLM "看到"的工具定义。description 极其重要：LLM 靠它判断何时调用

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的实时天气信息，包括温度、湿度、天气描述、风速。"
                          "当用户询问任何城市的当前天气状况时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市中文名，例如 '北京' '上海' '广州'",
                    },
                },
                "required": ["city"],
            },
        },
    },
]


# ============ 工具调度器：根据 name 调用对应的 Python 函数 ============

# 把工具名字映射到 Python 函数对象
TOOL_REGISTRY = {
    "get_weather": get_weather,
}


def execute_tool(tool_call: dict) -> str:
    """执行 LLM 决策的一次工具调用，返回字符串结果（喂回 LLM 用）。
    
    Args:
        tool_call: LLM 返回的 tool_call dict，含 id / function.name / function.arguments
    
    Returns:
        工具执行结果的 JSON 字符串。失败时返回 error 字符串。
    """
    function_name = tool_call["function"]["name"]
    arguments_str = tool_call["function"]["arguments"]   # 注意：是字符串
    log.info(f"[执行工具] {function_name}, args={arguments_str}")
    try:
        arguments  = json.loads(arguments_str)
        if function_name not in TOOL_REGISTRY:
            error_msg = f"未知工具：{function_name}"
            log.error(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
        func = TOOL_REGISTRY[function_name]
        result = func(**arguments)
        result_str = json.dumps(result, ensure_ascii=False)
        log.info(f"[工具结果] {result_str}")
        return result_str
    except json.JSONDecodeError as e:
        # 空 5（部分）: arguments 不是合法 JSON
        error_msg = f"arguments 不是合法 JSON: {e}"
        log.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)

    except TypeError as e:
        # 函数调用参数不匹配（比如 LLM 传错了参数名）
        error_msg = f"参数错误: {e}"
        log.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)

    except Exception as e:
        # 兜底：工具自己崩了
        error_msg = f"工具执行失败: {e}"
        log.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)



# ============ 主循环：处理 LLM 决策 → 执行 → 喂回 ============

def chat_with_tools(client: LLMClient, user_message: str, max_iterations: int = 5) -> str:
    """让 LLM 用工具回答用户问题。完整循环：
    
    用户提问 → LLM 决策 → (如果调工具) 执行 → 喂回 → LLM 给最终回答
    
    Args:
        client: LLMClient 实例
        user_message: 用户问题
        max_iterations: 最大循环次数（防止死循环）
    
    Returns:
        LLM 的最终自然语言回答
    """
    messages = [
        {"role": "system", "content": "你是一个有用的助手，可以使用工具帮用户查询信息。"},
        {"role": "user", "content": user_message},
    ]
    
    log.info(f"[用户提问] {user_message}")
    
    for iteration in range(max_iterations):
        log.info(f"[第 {iteration + 1} 轮 LLM 调用]")
        
        # ← 6. 调 client.chat(messages, tools=TOOLS)
        # 注意：chat 的返回是 {"answer": ..., "usage": ..., "raw": ...}
        # tool_calls 在 raw["choices"][0]["message"]["tool_calls"]
        result = client.chat(messages=messages, tools=TOOLS, temperature=0.3)

        if result is None:
            return "LLM 调用失败"
        
        # ← 7. 从 raw 里拿 message dict（含可能的 tool_calls）
        message = result["raw"]["choices"][0]["message"]
        
        # ← 8. 判断有没有 tool_calls
        # 如果没有 → message.get("content") 就是最终回答，return
        # 如果有 → 继续往下
        if not message.get("tool_calls"):
            log.info("[最终回答] " + (message.get("content") or "")[:100])
            return message.get("content", "")
        
        # ← 9. LLM 决定调工具：先把 LLM 的 tool_call 决策本身加入 messages
        # 注意：messages 里要带上 LLM 的整个 message dict
        # 但是因为 OpenAI 协议要求，content 可以是 None，我们这里需要保留
        messages.append(message)
        
        # ← 10. 遍历 tool_calls，逐个执行 + 把结果喂回 messages
        for tool_call in message["tool_calls"]:
            # 执行工具
            tool_result_str = execute_tool(tool_call)
            
            # 喂回 messages（关键：tool_call_id 必须对应）
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result_str,
            })
        
        # 继续下一轮 while 循环（让 LLM 看到 tool 结果给最终回答）
    
    # 死循环保护
    log.error(f"超过最大循环次数 {max_iterations}，强制退出")
    return f"工具调用循环超过 {max_iterations} 次，可能存在异常"


# ============ 测试 ============

def main():
    client = LLMClient()
    
    # 用例 1：用户问北京天气，LLM 应该调用 get_weather
    print("\n" + "=" * 60)
    print("【用例 1】用户问北京天气")
    print("=" * 60)
    answer = chat_with_tools(client, "今天北京天气怎么样？")
    print(f"\n最终回答：\n{answer}\n")
    
    # 用例 2：用户问无关问题，LLM 不应该调工具
    print("\n" + "=" * 60)
    print("【用例 2】用户问 Python 装饰器（无关工具）")
    print("=" * 60)
    answer = chat_with_tools(client, "什么是 Python 装饰器，用一句话回答。")
    print(f"\n最终回答：\n{answer}\n")
    
    # 用例 3（进阶）：用户问对比，LLM 应该连续调两次
    print("\n" + "=" * 60)
    print("【用例 3】用户问北京 vs 上海天气对比（多工具调用）")
    print("=" * 60)
    answer = chat_with_tools(client, "北京和上海现在哪个温度更舒服？")
    print(f"\n最终回答：\n{answer}\n")
    
    # 打印 token 用量
    print("\n" + "=" * 60)
    print(f"总 token 用量：{client.get_stats()}")
    print("=" * 60)


if __name__ == "__main__":
    main()