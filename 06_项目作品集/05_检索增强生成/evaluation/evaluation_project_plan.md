# Evaluation Project Plan

## 1. Module Goal

The evaluation module measures whether the RAG system retrieves the right evidence, returns useful knowledge packages, and supports Agent answers reliably.

It should support manual evaluation first, then gradually add automatic metrics.

## 2. Evaluation Targets

```text
retrieval accuracy
top-k evidence quality
latency
strategy effectiveness
backend comparison
answer groundedness
missing information detection
```

## 3. Evaluation Data

Each test case should contain:

```json
{
  "case_id": "case_001",
  "query": "液压泵压力不足怎么办？",
  "expected_chunk_ids": ["chunk_001"],
  "expected_asset_ids": ["asset_001"],
  "expected_keywords": ["过滤器", "油液液位", "泄压阀"],
  "business_domain": "equipment",
  "notes": "设备故障问答测试"
}
```

## 4. Metrics

### Retrieval Metrics

```text
hit@1
hit@3
hit@5
MRR
Recall@k
```

### Quality Metrics

```text
evidence relevance
source correctness
image asset correctness
context completeness
```

### System Metrics

```text
latency
error rate
empty result rate
strategy usage count
backend usage count
```

## 5. Manual Feedback

Frontend or evaluation script should allow:

```text
useful
irrelevant
missing
wrong source
wrong image
needs more context
```

## 6. Suggested Tech Stack

```text
Python
pytest
Pandas
FastAPI optional
SQLite or PostgreSQL logs
Markdown reports
```

## 7. Suggested Directory Structure

```text
evaluation/
  cases/
    retrieval_cases.json
  scripts/
    run_eval.py
    compare_strategies.py
  reports/
  metrics/
    retrieval_metrics.py
  README.md
```

## 8. First Vibe Coding Tasks

1. Create evaluation case JSON.
2. Write script to call backend `/retrieve`.
3. Compare returned chunk IDs with expected chunk IDs.
4. Compute hit@k.
5. Save report as Markdown.
6. Compare fast vs balanced mode.
7. Record latency.
8. Add manual feedback fields.

## 9. Acceptance Criteria

```text
Can run evaluation from command line
Can call backend retrieve API
Can calculate hit@k
Can produce Markdown report
Can compare at least two retrieval modes
Can record failed cases for debugging
```

## 10. Example Report Format

```markdown
# Retrieval Evaluation Report

## Summary

- Total cases:
- Hit@1:
- Hit@3:
- Average latency:

## Failed Cases

| Query | Expected | Returned | Notes |
|:--|:--|:--|:--|
```

## 11. Demo Cases

Recommended first cases:

```text
液压泵压力不足怎么办？
设备压力上不去应该先查哪里？
销售额怎么算？
质量异常处理流程是什么？
```