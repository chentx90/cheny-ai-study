import asyncio
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from backend.app.evaluation.eval_runner import run_evaluation_sync  # noqa: E402


async def main():
    results, metrics = await run_evaluation_sync()
    print("# Retrieval Evaluation Report")
    print()
    print(f"- Total cases: {metrics['total']}")
    print(f"- Hit@1: {metrics['hit@1']:.2%}")
    print(f"- Hit@3: {metrics['hit@3']:.2%}")
    print(f"- Hit@5: {metrics['hit@5']:.2%}")
    print(f"- MRR: {metrics['mrr']:.4f}")
    print(f"- Average latency: {metrics['avg_latency']:.0f} ms")
    print(f"- Report: {metrics.get('report_path')}")
    print()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
