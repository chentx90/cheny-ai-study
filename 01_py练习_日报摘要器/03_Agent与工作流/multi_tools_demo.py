"""
W22_Python_09 · 多工具并存 + Tool 设计原则
作者：cheny
日期：2026-05-26

3 个工具：
  - get_weather：实时天气（复用 W21 的 weather_api）
  - calculate：安全的数学表达式求值（ast 白名单）
  - get_current_time：当前时间（datetime + zoneinfo）

复用 tools_demo.py 的核心：execute_tool / chat_with_tools 主循环。
本文件只关心"工具定义 + 注册 + 测试"。
"""

import sys
import json
import ast
import operator as op
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# 让本文件能找到所有依赖
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "06_项目作品集" / "01_日报摘要器"))
sys.path.insert(0, str(ROOT / "01_Python补强"))

from llm_client import LLMClient
from logger import Logger
from weather_api import get_weather_cached


log = Logger(file_path=Path("logs/multi_tools.log"), to_console=True)


# ============ 工具 1：天气（复用） ============

def get_weather(city: str) -> dict:
    """实时天气查询（带 5 分钟缓存）。"""
    log.info(f"[工具执行] get_weather(city='{city}')")
    
    weather = get_weather_cached(city)
    if weather is None:
        return {
            "error": f"无法获取 {city} 的天气数据，可能网络异常或城市名不规范。"
                     "请使用中文全名（如 '北京' '上海'），不要用拼音或简称。"
        }
    
    return {
        "city": weather["city"],
        "temp_c": weather["temp_c"],
        "feels_like_c": weather["feels_like_c"],
        "weather": weather["weather_desc"],
        "humidity": weather["humidity"],
        "wind_kmph": weather["wind_speed_kmph"],
    }


# ============ 工具 2：安全数学求值 ============
# 用 AST 节点白名单，禁止函数调用 / import / 属性访问

ALLOWED_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
}


def _eval_node(node):
    """递归求值 AST 节点。遇到非白名单节点拒绝。"""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
    
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in ALLOWED_OPERATORS:
            raise ValueError(f"不支持的运算符: {op_type.__name__}")
        return ALLOWED_OPERATORS[op_type](_eval_node(node.left), _eval_node(node.right))
    
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in ALLOWED_OPERATORS:
            raise ValueError(f"不支持的一元运算符: {op_type.__name__}")
        return ALLOWED_OPERATORS[op_type](_eval_node(node.operand))
    
    raise ValueError(f"不允许的语法节点: {type(node).__name__}")


def calculate(expression: str) -> dict:
    """计算数学表达式（安全求值，禁止任意代码执行）。
    
    支持：加减乘除、乘方、取模、整除、括号、负号
    禁止：变量、函数调用、import、属性访问
    """
    log.info(f"[工具执行] calculate(expression='{expression}')")
    
    try:
        tree = ast.parse(expression, mode="eval").body
        result = _eval_node(tree)
        return {"expression": expression, "result": result}
    
    except SyntaxError as e:
        return {
            "error": f"表达式语法错误：{e.msg}。"
                     f"请确保只使用数字和运算符（+ - * / ** % // ()），不要写代码语句。"
        }
    except ValueError as e:
        return {
            "error": f"不允许的表达式：{e}。"
                     f"calculate 只支持纯数学运算，如 '23 * 45' 或 '(10 + 5) ** 2'。"
        }
    except ZeroDivisionError:
        return {"error": "除以 0 错误"}
    except Exception as e:
        return {"error": f"计算失败: {e}"}


# ============ 工具 3：当前时间 ============

def get_current_time(timezone: str = "Asia/Shanghai") -> dict:
    """获取指定时区的当前时间。
    
    Args:
        timezone: IANA 时区名，例如 'Asia/Shanghai' / 'America/New_York' / 'UTC'
    
    Returns:
        dict 含 timezone / iso_time / readable / weekday
    """
    log.info(f"[工具执行] get_current_time(timezone='{timezone}')")
    
    try:
        # ← 1. 用 ZoneInfo(timezone) 创建时区对象
        tz = ZoneInfo(timezone)
        # ← 2. datetime.now(tz=...) 拿到带时区的当前时间
        now = datetime.now(tz)
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        # ← 3. 返回 dict 含：
        return {
            "timezone": timezone,
            "iso_time": now.isoformat(),
            "readable": now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": weekdays[now.weekday()],
        }
        #      - timezone: 时区名
        #      - iso_time: ISO 8601 格式（now.isoformat()）
        #      - readable: 人类友好格式（如 '2026-05-26 15:30:00'，用 strftime）
        #      - weekday: 星期几（中文）
        ...
    except Exception as e:
        return {
            "error": f"获取时间失败: {e}。"
                     "请使用合法的 IANA 时区名（如 'Asia/Shanghai' 'America/New_York' 'UTC'），"
                     "不要使用 'GMT+8' 这种偏移格式。"
        }


# ============ Tool Schema（5 段式 description） ============

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                # ← 2. 写 get_weather 的 5 段式 description：
                # 1) 一句话定位
                # 2) 能力范围
                # 3) 示例
                # 4) 何时用
                # 5) 何时不用（提示：天气历史 / 预测不在范围内）
                "..."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市中文全名，例如 '北京' '上海' '广州'。"
                                       "不接受拼音、英文或简称（如 '京' 'BJ'）。",
                    },
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                # ← 3. 写 calculate 的 5 段式 description：
                # 1) 一句话定位
                # 2) 能力范围（加减乘除乘方取模整除）
                # 3) 示例（'23 * 45'，'(100 + 50) / 3'）
                # 4) 何时用（明确数字和运算符的场景）
                # 5) 何时不用（统计分析 / 含变量 / 需查询数据）
                "..."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "纯数学表达式字符串，只能含数字、+ - * / ** % // ( )。"
                                       "不能含变量名、函数调用、import 等代码语句。"
                                       "示例：'23 * 45'，'(100 - 30) / 7'。",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                # ← 4. 写 get_current_time 的 5 段式 description：
                # 1) 一句话定位
                # 2) 能力范围
                # 3) 示例
                # 4) 何时用（用户问"现在几点" / "今天是星期几"）
                # 5) 何时不用（用户问"昨天" "明天" 这类历史/未来）
                "..."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA 时区名。默认 'Asia/Shanghai'。"
                                       "示例：'Asia/Shanghai' 'America/New_York' 'Europe/London' 'UTC'。"
                                       "不接受 'GMT+8' 这类偏移格式。",
                    },
                },
                "required": [],   # timezone 可省略
            },
        },
    },
]


# ============ 工具注册中心 ============

TOOL_REGISTRY = {
    "get_weather": get_weather,
    "calculate": calculate,
    "get_current_time": get_current_time,
}


# ============ 通用执行器（沿用 tools_demo 的设计） ============

def execute_tool(tool_call: dict) -> str:
    """执行 LLM 决策的一次工具调用，返回字符串结果。"""
    function_name = tool_call["function"]["name"]
    arguments_str = tool_call["function"]["arguments"]
    
    log.info(f"[工具调度] {function_name} args={arguments_str}")
    
    try:
        arguments = json.loads(arguments_str)
        
        if function_name not in TOOL_REGISTRY:
            error_msg = f"未知工具: {function_name}"
            log.error(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
        
        func = TOOL_REGISTRY[function_name]
        result = func(**arguments)
        result_str = json.dumps(result, ensure_ascii=False)
        log.info(f"[工具结果] {result_str[:200]}")
        return result_str
    
    except json.JSONDecodeError as e:
        error_msg = f"arguments 不是合法 JSON: {e}"
        log.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)
    
    except TypeError as e:
        error_msg = f"参数错误: {e}"
        log.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)
    
    except Exception as e:
        error_msg = f"工具执行失败: {e}"
        log.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)


# ============ 主循环 ============

def chat_with_tools(client: LLMClient, user_message: str, max_iterations: int = 5) -> str:
    """让 LLM 用工具回答用户问题。"""
    messages = [
        {"role": "system", "content": "你是一个有用的助手，可以使用多种工具帮用户查询信息和计算。"
                                       "选择工具时仔细看每个工具的 description，特别是'何时用 / 何时不用'。"},
        {"role": "user", "content": user_message},
    ]
    
    log.info(f"[用户提问] {user_message}")
    
    for iteration in range(max_iterations):
        log.info(f"[第 {iteration + 1} 轮 LLM 调用]")
        
        result = client.chat(messages, tools=TOOLS)
        if result is None:
            return "LLM 调用失败"
        
        message = result["raw"]["choices"][0]["message"]
        
        if not message.get("tool_calls"):
            log.info("[最终回答] " + (message.get("content") or "")[:100])
            return message.get("content", "")
        
        # LLM 决策调工具：保留决策 + 执行 + 喂回
        messages.append(message)
        for tool_call in message["tool_calls"]:
            tool_result_str = execute_tool(tool_call)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result_str,
            })
    
    log.error(f"超过最大循环次数 {max_iterations}")
    return f"工具调用循环超过 {max_iterations} 次，可能存在异常"


# ============ 测试 ============

def main():
    client = LLMClient()
    
    test_cases = [
        ("用例 1 · 单工具 weather", "今天北京天气怎么样？"),
        ("用例 2 · 单工具 calculate", "23 * 45 + 7 等于多少？"),
        ("用例 3 · 单工具 time", "现在几点？"),
        ("用例 4 · 多工具一次决策", "北京天气怎么样，现在几点？"),
        ("用例 5 · 多步规划", "北京气温的两倍是多少度？"),
        ("用例 6 · 无关问题", "什么是 Python 装饰器，用一句话回答。"),
        ("用例 7 · 安全测试", "calculate 一下：__import__('os').system('echo hacked')"),
    ]
    
    for label, question in test_cases:
        print("\n" + "=" * 60)
        print(f"【{label}】{question}")
        print("=" * 60)
        answer = chat_with_tools(client, question)
        print(f"\n最终回答：\n{answer}\n")
    
    print("\n" + "=" * 60)
    print(f"总 token 用量：{client.get_stats()}")
    print("=" * 60)


if __name__ == "__main__":
    main()