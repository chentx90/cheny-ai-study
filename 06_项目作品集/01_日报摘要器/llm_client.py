"""
LLMClient · OpenAI 兼容协议的 LLM 客户端封装
作者：cheny
日期：2026-05-22

支持：
  基础版 - 多 client 并存 / messages 接口 / token 累计 / 异常分类
  进阶版 - 流式输出 / 自动重试（指数退避）
"""

import os
import sys
import json
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


# 让本文件能找到 01_Python补强 里的 logger.py
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "01_Python补强"))
from logger import Logger


# 加载 .env（在学习规划根目录）
load_dotenv(ROOT / ".env")


# ============ 异常分类常量 ============

# 可重试：错误来源在"中间环节"
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}

# 不可重试：错误来源在"请求本身"
NON_RETRYABLE_HTTP_CODES = {400, 401, 403, 404}


# ============ 客户端类 ============

class LLMClient:
    """OpenAI 兼容协议的 LLM 客户端。
    
    每个实例独立持有配置和统计数据，可以同时建多个 client 用不同模型：
        client_fast = LLMClient(model="gpt-4o-mini")
        client_smart = LLMClient(model="claude-3-5-sonnet")
    """
    
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """初始化客户端。
        
        Args:
            base_url: API 基地址（不含 /v1/...）。None 时从 .env 读
            api_key: API key。None 时从 .env 读
            model: 模型名。None 时从 .env 读
            timeout: 请求超时（秒）
            max_retries: 最大重试次数（不含首次）
        """
        # ← 1. 配置类属性
        # 提示：参数为 None 时回退到 .env，用 os.getenv("LLM_BASE_URL") 等
        # 配置完整性检查：base_url / api_key / model 任何一个为 None 应抛 ValueError
        base_url = base_url or os.getenv("LLM_BASE_URL")
        api_key = api_key or os.getenv("LLM_API_KEY")
        model = model or os.getenv("LLM_MODEL")
        if not base_url or not api_key or not model:
            raise ValueError(f"LLMClient 配置不完整: "
                             f"base_url={bool(base_url)}, "
                             f"api_key={bool(api_key)}, "
                             f"model={bool(model)}")

        # ← 2. 状态类属性（运行时累计）
        # self.total_tokens / prompt_tokens / completion_tokens / call_count
        # 全部初始 0
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.call_count = 0
        
        # ← 3. 复用类属性
        # self.log = Logger(file_path=Path("logs/llm_client.log"))
        self.log = Logger(file_path=Path("logs/llm_client.log"), to_console=True)
    
    def __repr__(self) -> str:
        """有意义的字符串表示。"""
        # 提示：要包含 model 和 call_count，但不要包含 api_key（安全）
        return (f"LLMClient(model='{self.model}', "
                f"calls={self.call_count}, "
                f"total_tokens={self.total_tokens})")

    
    def chat(self, messages: list[dict], **kwargs) -> dict | None:
        """发送一次完整对话请求，等待完整响应。
        
        Args:
            messages: [{"role": "system|user|assistant", "content": "..."}, ...]
            **kwargs: 透传给 API 的额外参数（temperature / max_tokens 等）
        
        Returns:
            成功：{"answer": str, "usage": dict, "raw": dict}
            失败：None
        """
        # ← 4. 拼 url / headers / body（参考昨天 chat 函数）
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            **kwargs,
        }
        # ← 5. 调 self._request_with_retry(...)
        data = self._request_with_retry(url, headers, body)
        # ← 6. 拿到 data 后：累计 token / 提取 answer / 返回
        if data is None:
            return None
        self._accumulate_tokens(data["usage"])
        return {
            "answer": data["choices"][0]["message"]["content"],
            "usage": data["usage"],
            "raw": data,
        }

    def chat_stream(self, messages: list[dict], **kwargs):
        """流式调用 LLM，返回生成器，逐字 yield 内容。

        用法：
            for piece in client.chat_stream(messages):
                print(piece, end="", flush=True)

        Args:
            messages: [{"role": "...", "content": "..."}, ...]
            **kwargs: 透传给 API 的额外参数

        Yields:
            每次一段新增的 content 字符串

        Note:
            - 仅当流正常结束时才累计 token
            - 中途 break 不会累计（因为 usage 只在最后 chunk）
        """
        # ============ 1. 构造 url / headers / body ============
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,  # ← 关键开关
            "stream_options": {"include_usage": True},  # ← 让 NewAPI 在最后 chunk 给 usage
            **kwargs,
        }

        # ============ 2. 异常处理外层（不重试，简化）============
        # 注意：流式重试逻辑很复杂（要避免重复 yield），今天先不实现
        try:
            resp = requests.post(
                url, headers=headers, json=body,
                stream=True,  # ← requests 的 stream=True
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            self.log.error("流式调用超时")
            return
        except requests.exceptions.ConnectionError:
            self.log.error("流式调用连不上")
            return
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code
            self.log.error(f"流式调用 HTTP {code}: {e.response.text[:200]}")
            return

        # ============ 3. 解析 SSE 流 ============
        last_usage = None  # 保存最后一个 chunk 的 usage

        for line in resp.iter_lines():
            # 3a. 跳过空行（SSE 协议的分隔符）
            if not line:
                continue

            # 3b. bytes 转 str（注意 utf-8）
            line_text = line.decode("utf-8")

            # 3c. 只处理 "data: " 开头的行
            if not line_text.startswith("data: "):
                continue

            # 3d. 去掉 "data: " 前缀（6 个字符）
            payload = line_text[6:]

            # 3e. 流结束信号
            if payload == "[DONE]":
                break

            # 3f. 解析 JSON
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                self.log.warn(f"流式 chunk JSON 解析失败: {payload[:100]}")
                continue

            # 3g. 提取 usage（只在最后一个 chunk 出现）
            if chunk.get("usage"):
                last_usage = chunk["usage"]
                continue  # usage chunk 通常没有 content

            # 3h. 提取 content delta
            choices = chunk.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")

            if content:
                yield content

        # ============ 4. 流正常结束才累计 token ============
        if last_usage:
            self._accumulate_tokens(last_usage)
            self.log.info(f"流式调用完成: tokens total={last_usage['total_tokens']}")

    def _request_with_retry(self, url: str, headers: dict, body: dict) -> dict | None:
        """带重试的请求执行。
        
        重试策略：指数退避 1s -> 2s -> 4s
        可重试错误：Timeout / ConnectionError / 5xx / 429
        不可重试错误：401 / 400 / 404 等，立即返回 None
        """
        for attempt in range(self.max_retries + 1):
            # ← 7. try 块：发 post / raise_for_status / 解析 json / return data
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            # ← 8. except 分类处理：
            #     - Timeout / ConnectionError → 可重试
            #     - HTTPError：看 status_code 在 RETRYABLE_HTTP_CODES 还是 NON_RETRYABLE_HTTP_CODES
            #     - JSONDecodeError → 半重试（重试 1 次）
            except requests.exceptions.Timeout:
                retryable = True
                reason = "连接超时"
            except requests.exceptions.ConnectionError:
                retryable = True
                reason = "连接不上"
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code
                if code in RETRYABLE_HTTP_CODES:
                    retryable = True
                    reason = f"HTTP{code}(可重试)"
                elif code in NON_RETRYABLE_HTTP_CODES:
                    retryable = False
                    reason = f"HTTP{code}(不可重试)，{e.response.text[:200]}"
                else :
                    retryable = False
                    reason = f"HTTP {code}（未知，按不可重试）"
            except json.JSONDecodeError:
                retryable = True
                reason = "JSON 解析失败"
            except Exception as e:
                retryable = False
                reason = f"未预期错误: {e}"
            # ← 9. 可重试 + attempt < max_retries: 算等待时间 2 ** attempt，sleep，continue
            #     不可重试 / 已达上限：log.error，return None
            if not retryable:
                self.log.error(f"调用失败（不可重试）: {reason}")
                return None
            if attempt >= self.max_retries:
                self.log.error(f"调用失败（重试已达上限）: {reason}")
                return None

            wait = 2 ** attempt
            self.log.warn(f"{reason}，等待 {wait}s 后重试 ({attempt + 1}/{self.max_retries})")
            time.sleep(wait)
        return None
    
    def _accumulate_tokens(self, usage: dict) -> None:
        """把本次调用的 usage 累加到实例属性。"""
        # ← 10. 累加 total / prompt / completion，call_count += 1
        self.total_tokens += usage["total_tokens"]
        self.prompt_tokens += usage["prompt_tokens"]
        self.completion_tokens += usage["completion_tokens"]
        self.call_count += 1
    
    def get_stats(self) -> dict:
        """返回当前统计快照。"""
        return {
            "call_count": self.call_count,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


# ============ 测试 ============

def main():
    # 用例 1：基本调用
    client = LLMClient()
    print(repr(client))
    
    # result = client.chat([
    #     {"role": "system", "content": "你是简洁的助手。"},
    #     {"role": "user", "content": "用一句话解释什么是 Python 装饰器"},
    # ])
    #
    # if result:
    #     print("\n回答：")
    #     print(result["answer"])
    #
    # # 用例 2：连续调用 + 看 token 累计
    # print("\n--- 第二次调用 ---")
    # client.chat([{"role": "user", "content": "再用一句话解释什么是 OOP"}])
    #
    # print(f"\n累计统计：{client.get_stats()}")
    # print(repr(client))
    #
    # # 用例 3：故意写错 key
    # print("\n--- 错 key 测试 ---")
    # bad_client = LLMClient(api_key="sk-wrong-key-xxx")
    # bad_result = bad_client.chat([{"role": "user", "content": "你好"}])
    # print(f"错 key 调用结果：{bad_result}（期望是 None + 友好日志）")

    print("\n" + "=" * 50)
    print("  流式测试")
    print("=" * 50)

    # 用例 4：流式调用
    for piece in client.chat_stream([
        {"role": "system", "content": "你是 Python 专家。"},
        {"role": "user", "content": "详细解释 Python 装饰器的原理，举 3 个具体例子，最后总结使用场景。"},
    ]):
        print(piece, end="", flush=True)

    print()  # 换行
    print(f"\n累计统计：{client.get_stats()}")

if __name__ == "__main__":
    main()