# Evaluation Module Framework

## 1. Module Boundary

The evaluation module tests retrieval quality and system behavior.

It calls the backend API like a user or Agent would. It does not directly query the database unless running diagnostic checks.

## 2. Recommended Stack

```text
Python
pytest
Pandas
httpx
Markdown reports
```

## 3. Directory Framework

```text
evaluation/
  cases/
    retrieval_cases.json

  scripts/
    run_eval.py
    compare_modes.py
    generate_report.py

  metrics/
    retrieval_metrics.py
    latency_metrics.py

  reports/
    latest_report.md

  tests/
    test_metrics.py

  README.md
```

## 4. Evaluation Case Format

```json
{
  "case_id": "case_001",
  "query": "液压泵压力不足怎么办？",
  "mode": "balanced",
  "constraints": {
    "business_domain": "equipment",
    "need_image": true
  },
  "expected_chunk_ids": ["chunk_001"],
  "expected_asset_ids": ["asset_001"],
  "expected_keywords": ["过滤器", "油液液位", "泄压阀"]
}
```

## 5. Metrics

```text
hit@1
hit@3
hit@5
MRR
Recall@k
Average latency
Empty result rate
Wrong source count
Missing asset count
```

## 6. Evaluation Flow

```text
load cases
  ↓
call POST /retrieve
  ↓
collect returned evidence
  ↓
compare with expected ids / keywords
  ↓
compute metrics
  ↓
write markdown report
```

## 7. Script Contract

```bash
python scripts/run_eval.py --backend http://localhost:8000 --cases cases/retrieval_cases.json
```

Output:

```text
reports/latest_report.md
```

## 8. First Files To Create

```text
cases/retrieval_cases.json
metrics/retrieval_metrics.py
scripts/run_eval.py
scripts/generate_report.py
```

## 9. First Acceptance Test

```text
Evaluation script can call backend
hit@k can be calculated
latency is recorded
failed cases are listed in Markdown report
```