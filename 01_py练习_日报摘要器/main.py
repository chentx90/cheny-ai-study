"""
日报摘要器 V1 · 主入口
作者：cheny
日期：2026-05-22

用法：
  python main.py --text "今天完成了订单接口"
  python main.py --input report.txt
  python main.py --input report.txt --output result.json
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from unittest import result

from llm_client import LLMClient
import prompts

# 项目根目录（main.py 所在目录）
PROJECT_ROOT = Path(__file__).parent
HISTORY_DIR = PROJECT_ROOT / "history"

# ============ 输入解析 ============

def parse_args() -> argparse.Namespace:
    """命令行参数解析。
    
    思路：
    - 用 ArgumentParser 创建解析器
    - 创建一个 mutually_exclusive_group(required=True)
    - 在 group 上加 --input（文件路径）和 --text（直接文字）
    - 在 parser 上加 --output（默认 None，存 history/）
    - 返回 parser.parse_args()
    """
    # ← 1. 在这里写 argparse 配置
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--text', '-t', help='从文本读取')
    group.add_argument('--input', '-i', help='从文件读取')
    parser.add_argument('--output', '-o', help='指定输出，默认为history/time_at.json')
    parser.add_argument("--stream", "-s",action="store_true",help="流式输出")  # 这是开关参数，写了就 True，不写就 False

    return parser.parse_args()

# ============ 输入读取 ============

def get_report_text(args: argparse.Namespace) -> tuple[str, str] | None:
    """根据参数拿到日报文字 + 来源描述。
    
    思路：
    - 如果 args.text 不为 None：直接用，source 标记为 "text"
    - 如果 args.input 不为 None：
        - 用 pathlib.Path 处理路径
        - 检查文件存在 → 不存在抛 FileNotFoundError
        - 读文件（with + utf-8）
        - source 标记为 f"file:{文件名}"
    - 返回 (报告文字, source 字符串)
    """
    # ← 2. 在这里写读取逻辑
    if args.text:
        return args.text, "text"
    if args.input is not None:
        input_path = Path(args.input)
        if not input_path.exists():
            raise FileNotFoundError(f"文件不存在{input_path}")
        if not input_path.is_file():
            raise FileNotFoundError(f"路径不是文件{input_path}")
        source = "file"
        text = input_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"文件内容为空：{input_path}")
        return text, source
    return None


# ============ LLM 调用 ============

def summarize(report_text: str, client: LLMClient,  stream: bool = False) -> dict | None:
    """调用 LLM 返回结构化摘要。
    
    思路：
    - 拼 messages：system 用 prompts.DAILY_SUMMARIZER_SYSTEM
                  user 用 prompts.build_user_message(report_text)
    - 调 client.chat(messages, response_format={"type": "json_object"}, temperature=0.3)
    - chat 返回 None 时直接返回 None
    - 否则从 result["answer"] 拿到 JSON 字符串
    - 用 json.loads 解析成 dict
    - 解析失败时不要崩，返回 None + 打印原始 answer 便于调试
    - 返回成功时把 dict 和 usage 都返回
    
    返回结构建议：
    {
      "summary": dict,        # LLM 返回的结构化摘要
      "usage": dict,          # token 用量
      "raw_answer": str,      # 原始字符串（调试用）
    }
    """
    # ← 3. 在这里写 LLM 调用 + JSON 解析逻辑
    messages = [
        {"role": "system", "content": prompts.DAILY_SUMMARIZER_SYSTEM},
        {"role": "user", "content": prompts.build_user_message(report_text)},
    ]
    if stream:
        before_stats = client.get_stats()
        full_response = ""
        for chunk in client.chat_stream(messages=messages, response_format={"type": "json_object"}, temperature=0.3):
            print(chunk, end="", flush=True)
            full_response += chunk
            print()
        try:
            summary = json.loads(full_response)
        except json.JSONDecodeError as e:
            client.log.error(f"LLM 返回的不是合法 JSON: {e}")
            client.log.error(f"原始内容（前 500 字）: {full_response[:500]}")
            return None

        after_stats = client.get_stats()
        usage = {
            "prompt_tokens": after_stats["prompt_tokens"] - before_stats["prompt_tokens"],
            "completion_tokens": after_stats["completion_tokens"] - before_stats["completion_tokens"],
            "total_tokens": after_stats["total_tokens"] - before_stats["total_tokens"],
        }

        return {
            "summary": summary,
            "usage": usage,
            "raw_answer": full_response,
        }
    else:
        result = client.chat(messages=messages, response_format={"type": "json_object"})
        if result  is  None:
            return None
        raw_answer = result["answer"]
        try:
            summary = json.loads(raw_answer)
        except json.JSONDecodeError as e:
            client.log.error(f"LLM 返回的不是合法 JSON: {e}")
            client.log.error(f"原始内容（前 500 字）: {raw_answer[:500]}")
            return None

        return {
            "summary": summary,
            "usage": result["usage"],
            "raw_answer": raw_answer,
        }



# ============ 历史记录 ============

def save_history(
    report_text: str,
    source: str,
    summarize_result: dict,
    model: str,
    output_path: Path | None = None,
) -> Path:
    """把这次调用的完整记录写到 history/。
    
    思路：
    - 时间戳格式：%Y-%m-%d_%H-%M-%S（**不要用冒号**，Windows 文件名禁止）
    - 默认路径：history/{timestamp}.json
    - 如果传了 output_path，用传的
    - 内容字段（参考之前讨论）：
        timestamp / model / input(source + raw + char_count) / 
        output(summary) / usage
    - 用 with + utf-8 + ensure_ascii=False + indent=2 写
    - 返回最终的写入路径
    """
    timestamp = datetime.now()

    record = {
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "input": {
            "source": source,
            "raw": report_text,
            "char_count": len(report_text),
        },
        "output": summarize_result["summary"],
        "usage": summarize_result["usage"],
    }


    # ← 4. 在这里写历史记录写入逻辑
    if output_path is None:
        # 默认 history/2026-05-22_15-30-12.json
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        filename = timestamp.strftime("%Y-%m-%d_%H-%M-%S") + ".json"
        output_path = HISTORY_DIR / filename
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return output_path


# ============ 控制台展示 ============

def display(summary: dict, usage: dict, history_path: Path, stream: bool = False) -> None:
    """友好排版打印结果。
    
    思路：
    - 加个分隔线让输出可读
    - 4 个类别分别打印（完成项 / 进行中 / 计划项 / 风险点）
    - 每个类别下用 "- " 列出条目
    - 空类别打印 "（无）"
    - 末尾打印 token 用量 + 历史文件路径
    """
    SECTION_LINE = "─" * 50

    print()
    print("=" * 50)
    print("  日报摘要")
    print("=" * 50)

    # 4 个固定类别，按这个顺序展示
    categories = ["完成项", "进行中", "计划项", "风险点"]
    icons = {"完成项": "✓", "进行中": "→", "计划项": "□", "风险点": "⚠"}

    if not stream:
        for cat in categories:
            items = summary.get(cat, [])
            print(f"\n{icons[cat]} {cat}")
            print(SECTION_LINE)
            if not items:
                print("  （无）")
            else:
                for item in items:
                    print(f"  • {item}")

    # 元信息
    print()
    print("=" * 50)
    print(f"  Token 用量: prompt={usage['prompt_tokens']} / "
          f"completion={usage['completion_tokens']} / "
          f"total={usage['total_tokens']}")
    print(f"  历史记录: {history_path}")
    print("=" * 50)


# ============ 主流程 ============

def main():
    """主入口。
    
    思路：
    1. 解析参数
    2. 读取日报文字
       - 文件不存在等异常 → 友好报错并 sys.exit(1)
    3. 创建 LLMClient
    4. 调 summarize → 失败时友好报错并 sys.exit(2)
    5. 写 history
    6. display 打印
    """
    # ← 6. 在这里写主流程
    args = parse_args()
    stream = args.stream

    try:
        report_text, source = get_report_text(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ 输入错误: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        client = LLMClient()
    except ValueError as e:
        print(f"❌ LLM 配置错误: {e}", file=sys.stderr)
        print("   请检查 .env 文件里的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL",
              file=sys.stderr)
        sys.exit(1)

    summarize_result = summarize(report_text, client, stream)

    output_path = Path(args.output) if args.output else None
    history_path = save_history(
        report_text=report_text,
        source=source,
        summarize_result=summarize_result,
        model=client.model,
        output_path=output_path,
    )

    display(summarize_result["summary"], summarize_result["usage"], history_path, stream)

if __name__ == "__main__":
    main()