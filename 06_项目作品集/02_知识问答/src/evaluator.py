"""
evaluator.py - 评测模块
指标：Hit Rate@K / MRR@K
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class EvalQuestion:
    question: str
    gold_doc_ids: list[str]
    category: str = ""


def load_eval_set(eval_file: Path) -> list[EvalQuestion]:
    """加载评测集 JSON。"""
    data = json.loads(eval_file.read_text(encoding="utf-8"))
    questions = []
    for item in data:
        if "question" in item and "gold_doc_ids" in item:
            questions.append(EvalQuestion(
                question=item["question"],
                gold_doc_ids=item["gold_doc_ids"],
                category=item.get("category", ""),
            ))
    logger.info(f"加载评测集: {len(questions)} 个问题")
    return questions


def evaluate_retrieval(
    questions: list[EvalQuestion],
    retriever_fn,
    k: int = 5,
) -> dict:
    """跑评测，返回汇总指标。

    Args:
        questions: 评测问题列表
        retriever_fn: callable，输入 question(str)，返回 list[str]（检索到的 source 列表）
        k: top-K
    
    Returns:
        {"hit_rate": float, "mrr": float, "n_questions": int, "details": list}
    """
    hits = 0
    mrr_sum = 0.0
    details = []

    for q in questions:
        retrieved = retriever_fn(q.question)[:k]

        # 去后缀统一格式（"04486.md" → "04486"）
        retrieved_ids = [Path(r).stem for r in retrieved]

        # Hit: top-K 里至少有一个金标
        hit = any(gid in retrieved_ids for gid in q.gold_doc_ids)
        if hit:
            hits += 1

        # MRR: 第一个命中的金标排名
        rr = 0.0
        for rank, rid in enumerate(retrieved_ids, 1):
            if rid in q.gold_doc_ids:
                rr = 1.0 / rank
                break

        mrr_sum += rr
        details.append({
            "question": q.question,
            "category": q.category,
            "gold_doc_ids": q.gold_doc_ids,
            "retrieved_ids": retrieved_ids,
            "hit": hit,
            "reciprocal_rank": rr,
        })

    n = len(questions)
    return {
        "n_questions": n,
        "k": k,
        "hit_rate": hits / n if n else 0,
        "mrr": mrr_sum / n if n else 0,
        "details": details,
    }