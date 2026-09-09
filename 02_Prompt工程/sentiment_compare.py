"""
W21_Prompt_01 · 情感分析三种 Prompt 风格对比
作者：cheny
日期：2026-05-21

复用 01_Python补强/llm_first_call.py 的 chat 函数。
评测维度：正确率 / 严格合规率 / token 消耗。
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "01_Python补强"))

from llm_first_call import chat
from logger import Logger


log = Logger(file_path=Path("logs/prompt_compare.log"), to_console=True)


# ============ Prompt 模板 ============

ZERO_SHOT_SYSTEM = """你是一个情感分析助手。
判断用户给出的中文评论的情感倾向。
只输出一个标签词：正面 / 负面 / 中性。不要其他任何字。"""

FEW_SHOT_SYSTEM = """你是一个情感分析助手。
判断用户给出的中文评论的情感倾向。
只输出一个标签词:正面 / 负面 / 中性。不要其他任何字。

参考以下示例:
评论:服务很周到 -> 正面
评论:等了一小时还没上菜 -> 负面
评论:价格中规中矩 -> 中性
评论:东西还行吧,没啥惊喜 -> 中性"""

COT_SYSTEM = """你是一个情感分析助手。
判断用户给出的中文评论的情感倾向。

请按以下步骤分析:
1. 列出评论中的情感词汇(正面 / 负面)
2. 判断有无转折、反讽
3. 综合给出最终结论

最后一行必须是:「结论:正面」或「结论:负面」或「结论:中性」之一。"""


# ============ 12 条评测样本 ============
SAMPLES: list[dict] = [
    {"text": "这家咖啡馆环境舒服,服务也好", "label": "正面"},
    {"text": "排队两小时上菜五分钟,效率值得点赞", "label": "负面"},
    {"text": "整体一般般,不算坏", "label": "中性"},
    {"text": "菜不错,但服务员态度差", "label": "负面"},
    {"text": "老板很热情,下次还来", "label": "正面"},
    {"text": "性价比超高,强烈推荐", "label": "正面"},
    {"text": "服务态度恶劣,再也不来了", "label": "负面"},
    {"text": "卫生堪忧,看到了一只苍蝇", "label": "负面"},
    {"text": "凑合吃,没特别的", "label": "中性"},
    {"text": "这家店真“便宜”啊,一份青菜38块", "label": "负面"},
    {"text": "慢得像在山里挖矿", "label": "负面"},
    {"text": "好吃到能吃到地老天荒", "label": "正面"},
]


# ============ 标签解析(双标准) ============

def parse_label(text: str) -> tuple[str | None, bool]:
    """
    返回 (识别到的标签, 是否严格合规)
    
    严格合规:去除标点空白后等于"正面/负面/中性"之一
    宽松匹配:包含且只包含一个标签词,但有其他文字(strict_ok=False,仍能算正确率)
    无法识别:返回 (None, False)
    """
    cleaned = text.strip().rstrip("。.！!,，")
    
    if cleaned in ("正面", "负面", "中性"):
        return cleaned, True
    
    found = [label for label in ("正面", "负面", "中性") if label in cleaned]
    if len(found) == 1:
        return found[0], False
    
    return None, False


def parse_cot_label(text: str) -> tuple[str | None, bool]:
    """CoT 输出最后一行应该是「结论:xx」,单独处理。"""
    last_line = text.strip().split("\n")[-1].strip()
    
    for prefix in ("「结论:", "「结论：", "结论:", "结论："):
        if last_line.startswith(prefix):
            last_line = last_line[len(prefix):]
            break
    last_line = last_line.rstrip("」").strip()
    
    return parse_label(last_line)


# ============ 三种风格的调用 ============

def run_zero_shot(comment: str) -> dict | None:
    """跑 zero-shot 一次。"""
    data = chat(comment, system_prompt=ZERO_SHOT_SYSTEM)
    if data is None:
        log.error("zero_shot 调用失败")
        return None
    pred, strict_ok = parse_label(data["answer"])
    return {
        "pred": pred,
        "strict_ok": strict_ok,
        "total_tokens": data["usage"]["total_tokens"],
    }


def run_few_shot(comment: str) -> dict | None:
    """跑 few-shot 一次。"""
    data = chat(comment, system_prompt=FEW_SHOT_SYSTEM)
    if data is None:
        log.error("few_shot 调用失败")
        return None
    pred, strict_ok = parse_label(data["answer"])
    return {
        "pred": pred,
        "strict_ok": strict_ok,
        "total_tokens": data["usage"]["total_tokens"],
    }


def run_cot(comment: str) -> dict | None:
    """跑 cot 一次,用 parse_cot_label 解析。"""
    data = chat(comment, system_prompt=COT_SYSTEM)
    if data is None:
        log.error("cot 调用失败")
        return None
    pred, strict_ok = parse_cot_label(data["answer"])
    return {
        "pred": pred,
        "strict_ok": strict_ok,
        "total_tokens": data["usage"]["total_tokens"],
    }


# ============ 评测主流程 ============

def evaluate_one_style(style_name: str, runner, samples: list[dict]) -> dict:
    """跑一种风格的所有样本,返回统计。"""
    log.info(f"开始评测: {style_name}")
    
    correct = 0
    strict_compliant = 0
    total_tokens = 0
    failures = []
    details = []
    
    for i, sample in enumerate(samples, 1):
        result = runner(sample["text"])
        if result is None:
            log.warn(f"  样本 {i} 调用失败")
            failures.append(i)
            continue
        
        pred = result["pred"]
        strict = result["strict_ok"]
        total_tokens += result["total_tokens"]
        
        is_correct = (pred == sample["label"])
        if is_correct:
            correct += 1
        if strict:
            strict_compliant += 1
        
        details.append({
            "text": sample["text"],
            "expected": sample["label"],
            "predicted": pred,
            "correct": is_correct,
            "strict_ok": strict,
            "tokens": result["total_tokens"],
        })
    
    n = len(samples) - len(failures)
    return {
        "style": style_name,
        "n_samples": len(samples),
        "n_failed": len(failures),
        "correct_rate": correct / n if n else 0,
        "strict_rate": strict_compliant / n if n else 0,
        "total_tokens": total_tokens,
        "avg_tokens": total_tokens / n if n else 0,
        "details": details,
    }


def print_summary(reports: list[dict]) -> None:
    """打印对比表。"""
    print("\n" + "=" * 60)
    print(f"{'风格':<12} {'正确率':<10} {'严格合规率':<12} {'平均tokens':<12}")
    print("=" * 60)
    for r in reports:
        print(f"{r['style']:<12} "
              f"{r['correct_rate']:.1%}    "
              f"{r['strict_rate']:.1%}      "
              f"{r['avg_tokens']:.0f}")
    print("=" * 60)


# ============ 主入口 ============

def main():
    if len(SAMPLES) < 12:
        log.warn(f"样本数 {len(SAMPLES)} 不足 12 条")
    
    reports = [
        evaluate_one_style("zero_shot", run_zero_shot, SAMPLES),
        evaluate_one_style("few_shot",  run_few_shot,  SAMPLES),
        evaluate_one_style("cot",       run_cot,       SAMPLES),
    ]
    
    print_summary(reports)
    
    output = Path("sentiment_results.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    log.info(f"评测完成,保存到 {output}")


if __name__ == "__main__":
    main()