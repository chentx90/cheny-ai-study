"""
W21_Python_05 · 第一次调通 LLM API
作者：cheny
日期：2026-05-21

通过 NewAPI 聚合层调用 OpenAI 兼容格式的 LLM。
"""

import os
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

from logger import Logger


# ===== 加载配置 =====
# 提示：.env 在学习规划根目录，本脚本在 01_Python补强/ 子目录
# 所以要 .parent.parent 才能找到 .env
load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = os.getenv("LLM_BASE_URL")
API_KEY = os.getenv("LLM_API_KEY")
MODEL = os.getenv("LLM_MODEL")
TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

# ===== Logger =====
log = Logger(file_path=Path("logs/llm.log"), to_console=True)

# ===== 核心函数 =====
def chat(user_message: str, system_prompt: str = "你是一个猫娘，每句话结尾都加‘喵’。") -> dict | None:
    """调用 LLM，返回完整响应字典。
    
    Args:
        user_message: 用户问题
        system_prompt: 系统设定，默认简洁助手
    
    Returns:
        成功返回 {"answer": str, "usage": dict}；失败返回 None
    """
    if not BASE_URL or not API_KEY or not MODEL:
        log.error(f"配置缺失：BASE_URL={BASE_URL}, API_KEY={'有'if API_KEY else '无'}, MODEL={MODEL}")
        return None

    url = f"{BASE_URL}/v1/chat/completions"
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        }
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.7,
    }

    try:
        response = requests.post(url, json=body, timeout=TIMEOUT, headers=headers)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        log.error(f"超时：{TIMEOUT}秒未响应")
        return None
    except requests.exceptions.ConnectionError:
        log.error(f"连不上: {url}")
        return None
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code == 401:
            log.error(f"认证失败：检查.env中的LLM_API_KEY")
            return None
        elif code == 429:
            log.error("被限流：稍后重试")
            return None
        elif 500 <= code <= 599:
            log.error(f"服务器错误 {code}：可能是模型厂商欠费或后端故障")
            return None
        else:
            log.error(f"HTTP 错误 {code}: {e.response.text[:200]}")
            return None
    except json.JSONDecodeError:
        log.error("响应不是合法JSON")
        return None
    answer = data["choices"][0]["message"]["content"]
    usage = data["usage"]
    cost =  usage['completion_tokens_details']['reasoning_tokens']/1000000*2 + usage['prompt_cache_hit_tokens']/1000000*0.2 + usage['prompt_cache_miss_tokens']/1000000*0.1

    log.info(f"调用成功：tokens total={usage['total_tokens']}")
    return {"answer": answer, "usage": usage, "cost": cost}

# ===== 主流程 =====
def main():
    user_q = "用一句话解释什么是元组"

    system_prompt = [
        ("对照组", "你是一个简洁的助手。"),
        ("海盗组", "你是海盗船长。所有回答都用 'Arrr!' 开头，使用海盗术语。"),
        ("严苛组", "严格用一句话回答，不超过 30 个字，不举例不解释。"),
    ]
    for name, sys_prompt in system_prompt:
        print(f"\n{'=' * 50}")
        print(f"  {name}: {sys_prompt[:30]}...")
        print('=' * 50)

        result = chat(user_q, system_prompt=sys_prompt)

        if result is None:
            log.error("LLM 调用失败")
            return

        print(result["answer"])
        print(f"-- tokens: {result['usage']['total_tokens']} --")
        print(f"-- 费用: {result['cost']}")

if __name__ == "__main__":
    main()



