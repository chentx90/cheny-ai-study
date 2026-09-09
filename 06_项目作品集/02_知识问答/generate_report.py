"""
RAG 对比实验报告生成器
读取 results/ 下各实验组的 metrics.json + eval_details.json，生成 report.md。

用法：
    python generate_report.py
    python generate_report.py --output custom_report.md
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from config import RESULTS_DIR, EXPERIMENTS


def load_all_results(results_dir: Path) -> dict:
    """加载所有实验组的结果。"""
    results = {}
    for exp_dir in sorted(results_dir.iterdir()):
        if not exp_dir.is_dir():
            continue
        metrics_file = exp_dir / "metrics.json"
        details_file = exp_dir / "eval_details.json"
        if not metrics_file.exists():
            continue

        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
        details = []
        if details_file.exists():
            details = json.loads(details_file.read_text(encoding="utf-8"))

        results[exp_dir.name] = {
            "metrics": metrics,
            "details": details,
        }
    return results


def build_header() -> str:
    """报告标题。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""# RAG 对比实验报告

> 生成时间：{now}
> 自动生成，基于 results/ 目录下的实验数据

---"""


def build_overview(results: dict) -> str:
    """实验概览。"""
    lines = [
        "## 一、实验概览",
        "",
        f"- 已完成实验组数：**{len(results)}**",
        f"- 计划实验组数：**{len(EXPERIMENTS)}**",
        "",
        "| 实验组 | 模型 | 数据类型 | 切块方式 | chunk_size | 状态 |",
        "|--------|------|----------|----------|------------|------|",
    ]
    for exp in EXPERIMENTS:
        status = "✓ 完成" if exp.name in results else "⏳ 待跑"
        lines.append(
            f"| {exp.name} | {exp.model_name.split('/')[-1]} | {exp.data_key} | {exp.chunk_method} | {exp.chunk_size} | {status} |"
        )
    return "\n".join(lines)


def build_comparison_table(results: dict) -> str:
    """总体指标对比表格。"""
    if not results:
        return "## 二、总体指标对比\n\n暂无数据。"

    lines = [
        "## 二、总体指标对比",
        "",
        "| 实验组 | 模型 | 数据类型 | 切块方式 | chunks | Hit Rate@5 | MRR@5 |",
        "|--------|------|----------|----------|--------|------------|-------|",
    ]

    for name, data in sorted(results.items()):
        m = data["metrics"]
        lines.append(
            f"| {m['experiment']} | {m['model'].split('/')[-1]} | {m['data']} | "
            f"{m['chunk_method']} {m['chunk_size']} | {m['total_chunks']} | "
            f"**{m['hit_rate']:.3f}** | **{m['mrr']:.3f}** |"
        )
    return "\n".join(lines)


def build_category_analysis(results: dict) -> str:
    """按问题维度分组统计 Hit Rate。"""
    if not results:
        return "## 三、分维度分析\n\n暂无数据。"

    # 收集所有类别
    all_categories = set()
    for data in results.values():
        for d in data["details"]:
            all_categories.add(d.get("category", "未分类"))

    if not all_categories:
        return "## 三、分维度分析\n\n无详情数据（需重跑实验生成 eval_details.json）。"

    all_categories = sorted(all_categories)
    exp_names = sorted(results.keys())

    # 按类别统计每组的命中率
    category_stats = {}  # {category: {exp_name: hit_rate}}
    category_counts = {}  # {category: count}

    for cat in all_categories:
        category_stats[cat] = {}
        for name, data in results.items():
            cat_questions = [d for d in data["details"] if d.get("category", "未分类") == cat]
            if cat_questions:
                hits = sum(1 for d in cat_questions if d["hit"])
                category_stats[cat][name] = hits / len(cat_questions)
                category_counts[cat] = len(cat_questions)
            else:
                category_stats[cat][name] = None

    lines = [
        "## 三、分维度分析",
        "",
        "各问题类别下的 Hit Rate@5：",
        "",
    ]

    # 表头
    header = "| 类别 | 问题数 | " + " | ".join(exp_names) + " |"
    sep = "|------|--------|" + "|".join(["--------"] * len(exp_names)) + "|"
    lines.append(header)
    lines.append(sep)

    for cat in all_categories:
        count = category_counts.get(cat, 0)
        row = f"| {cat} | {count} |"
        for name in exp_names:
            val = category_stats[cat].get(name)
            if val is not None:
                row += f" {val:.3f} |"
            else:
                row += " - |"
        lines.append(row)

    return "\n".join(lines)


def build_failure_analysis(results: dict) -> str:
    """未命中分析：找出跨实验组都未命中的问题。"""
    if not results:
        return "## 四、未命中分析\n\n暂无数据。"

    # 统计每个问题在各组的命中情况
    question_hits = defaultdict(dict)  # {question: {exp_name: hit}}
    question_meta = {}  # {question: {category, gold_doc_ids}}

    for name, data in results.items():
        for d in data["details"]:
            q = d["question"]
            question_hits[q][name] = d["hit"]
            if q not in question_meta:
                question_meta[q] = {
                    "category": d.get("category", ""),
                    "gold_doc_ids": d.get("gold_doc_ids", []),
                }

    # 按"未命中次数"降序排列
    exp_names = sorted(results.keys())
    failure_scores = []
    for q, hits in question_hits.items():
        miss_count = sum(1 for h in hits.values() if not h)
        if miss_count > 0:
            failure_scores.append((miss_count, q))

    failure_scores.sort(reverse=True)

    lines = [
        "## 四、未命中分析（Top 失败案例）",
        "",
        f"共 {len(failure_scores)} 个问题在至少一组实验中未命中。",
        "",
        "| # | 问题（前50字）| 类别 | 金标文档 | " + " | ".join(exp_names) + " |",
        "|---|--------------|------|----------|" + "|".join(["----"] * len(exp_names)) + "|",
    ]

    for i, (miss_count, q) in enumerate(failure_scores[:15], 1):
        meta = question_meta[q]
        q_short = q[:50] + ("..." if len(q) > 50 else "")
        gold = ",".join(meta["gold_doc_ids"][:2])
        row = f"| {i} | {q_short} | {meta['category']} | {gold} |"
        for name in exp_names:
            hit = question_hits[q].get(name)
            if hit is None:
                row += " - |"
            elif hit:
                row += " ✓ |"
            else:
                row += " ✗ |"
        lines.append(row)

    return "\n".join(lines)


def build_findings(results: dict) -> str:
    """关键发现：自动对比差值，超过 5% 标记为显著差异。"""
    if len(results) < 2:
        return "## 五、关键发现\n\n需要至少 2 组实验数据才能对比。"

    lines = [
        "## 五、关键发现",
        "",
    ]

    exp_names = sorted(results.keys())
    findings = []

    # 两两对比
    for i in range(len(exp_names)):
        for j in range(i + 1, len(exp_names)):
            name_a = exp_names[i]
            name_b = exp_names[j]
            hr_a = results[name_a]["metrics"]["hit_rate"]
            hr_b = results[name_b]["metrics"]["hit_rate"]
            diff = hr_a - hr_b

            if abs(diff) >= 0.05:  # 5% 阈值
                if diff > 0:
                    findings.append(
                        f"- **{name_a}** 比 **{name_b}** Hit Rate 高 **{diff:.1%}**（显著差异 ⚠️）"
                    )
                else:
                    findings.append(
                        f"- **{name_b}** 比 **{name_a}** Hit Rate 高 **{abs(diff):.1%}**（显著差异 ⚠️）"
                    )
            else:
                findings.append(
                    f"- {name_a} vs {name_b}：Hit Rate 差异 {abs(diff):.1%}（无显著差异）"
                )

    if findings:
        lines.extend(findings)
    else:
        lines.append("暂无显著差异发现。")

    # 最优配置
    lines.append("")
    lines.append("### 当前最优配置")
    best = max(results.items(), key=lambda x: x[1]["metrics"]["hit_rate"])
    m = best[1]["metrics"]
    lines.append(f"- 实验组：**{m['experiment']}**")
    lines.append(f"- Hit Rate@5：**{m['hit_rate']:.3f}**")
    lines.append(f"- MRR@5：**{m['mrr']:.3f}**")
    lines.append(f"- 配置：{m['model'].split('/')[-1]} + {m['data']} + {m['chunk_method']} {m['chunk_size']}")

    return "\n".join(lines)


def build_conclusion(results: dict) -> str:
    """结论与下一步。"""
    lines = [
        "## 六、结论与下一步",
        "",
        "### 已验证",
    ]

    if results:
        best = max(results.items(), key=lambda x: x[1]["metrics"]["hit_rate"])
        lines.append(f"- 当前最优：{best[0]}（Hit Rate {best[1]['metrics']['hit_rate']:.3f}）")

    lines.extend([
        "",
        "### 待优化方向",
        "- [ ] 加入 Rerank（cross-encoder 精排 top-20 → top-5）",
        "- [ ] 混合检索（向量 + BM25 关键词）",
        "- [ ] 多查询改写（用 LLM 生成 query 变体）",
        "- [ ] 扩大评测集（当前 100 题，目标 300+）",
        "- [ ] GPU 加速（装 CUDA 版 PyTorch）",
        "- [ ] 全量 4 万文档跑通",
        "",
        "### 待跑实验",
    ])

    for exp in EXPERIMENTS:
        if exp.name not in results:
            lines.append(f"- [ ] {exp.name}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="生成 RAG 实验报告")
    parser.add_argument("--output", type=str, default="report.md", help="输出文件名")
    args = parser.parse_args()

    results = load_all_results(RESULTS_DIR)
    print(f"加载了 {len(results)} 组实验结果")

    sections = [
        build_header(),
        build_overview(results),
        build_comparison_table(results),
        build_category_analysis(results),
        build_failure_analysis(results),
        build_findings(results),
        build_conclusion(results),
    ]

    report = "\n\n".join(sections)
    output_path = Path(args.output)
    output_path.write_text(report, encoding="utf-8")
    print(f"报告已生成: {output_path}")
    print(f"字数: {len(report)}")


if __name__ == "__main__":
    main()