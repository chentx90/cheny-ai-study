# 评估模块

## 定位

对 RAG 检索质量进行定量评估：给定问题 + 标准答案 chunk，检验系统是否能召回正确证据。

## 目录

```
evaluation/
  cases/
    retrieval_cases.json   # 测试用例（query / expected_chunk_ids / method）
  metrics/
    retrieval_metrics.py   # recall@k, precision@k, MRR, hit_rate
  scripts/
    run_eval.py            # 批量评估：调 /api/retrieve，输出报告
  README.md
```

## 指标说明

| 指标 | 公式 | 含义 |
|:--|:--|:--|
| Hit Rate | 命中用例数 / 总用例数 | Top-k 内至少有一个正确结果的比例 |
| Recall@k | \|relevant ∩ retrieved\| / \|relevant\| | 相关结果被召回的比例 |
| Precision@k | \|relevant ∩ retrieved\| / k | 召回结果中相关的比例 |
| MRR | mean(1 / rank_of_first_hit) | 第一个正确结果排名的倒数均值 |

## 用例格式

```json
{
  "case_id": "c001",
  "query": "液压泵压力不足怎么办？",
  "expected_chunk_ids": ["chunk-uuid-1"],
  "method": "equipment_troubleshooting_v1",
  "constraints": {"business_domain": "equipment"}
}
```

## 运行

```bash
cd evaluation
python scripts/run_eval.py --cases cases/retrieval_cases.json --api http://localhost:8000
```

输出：各用例 hit/miss，汇总 recall@5、MRR。
