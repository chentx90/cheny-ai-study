"""
RAG 对比实验主入口
用法：
    python run_experiment.py --exp A1_structured_title
    python run_experiment.py --exp all
"""

import argparse
import json
import time
import numpy as np
from pathlib import Path

from config import EXPERIMENTS, DATA_PATHS, CHROMA_ROOT, RESULTS_DIR, EVAL_FILE
from src.chunker import chunk_file
from src.embedder import get_embedder, EmbeddingResult
from src.indexer import ChromaIndexer
from src.evaluator import load_eval_set, evaluate_retrieval


def run_single_experiment(exp_config, eval_questions):
    """跑单组实验：分块 → embedding → 入库 → 评测。"""
    print(f"\n{'='*60}")
    print(f"实验: {exp_config.name}")
    print(f"模型: {exp_config.model_name} | 数据: {exp_config.data_key} | 切块: {exp_config.chunk_method} {exp_config.chunk_size}")
    print(f"{'='*60}")

    data_dir = DATA_PATHS[exp_config.data_key]
    if not data_dir.exists():
        print(f"[错误] 数据目录不存在: {data_dir}")
        return None

    # ---- Layer 2: 分块 ----
    print("[1/4] 分块...")
    t0 = time.time()
    all_chunks = []
    for f in sorted(data_dir.iterdir()):
        if f.is_file():
            chunks = chunk_file(f, exp_config.chunk_method, exp_config.chunk_size, exp_config.chunk_overlap)
            all_chunks.extend(chunks)
    print(f"  文件数: {len(list(data_dir.iterdir()))}, 总 chunks: {len(all_chunks)}, 耗时: {time.time()-t0:.1f}s")

    if not all_chunks:
        print("[错误] 分块结果为空")
        return None

    # ---- Layer 3: Embedding（带缓存）----
    cache_dir = RESULTS_DIR / exp_config.name
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_vectors = cache_dir / "vectors.npy"
    cache_texts = cache_dir / "texts.json"
    cache_metadatas = cache_dir / "metadatas.json"

    if cache_vectors.exists() and cache_texts.exists() and cache_metadatas.exists():
        print("[2/4] Embedding（从缓存加载）...")
        t0 = time.time()
        vectors = np.load(str(cache_vectors))
        texts = json.loads(cache_texts.read_text(encoding="utf-8"))
        metadatas = json.loads(cache_metadatas.read_text(encoding="utf-8"))
        embed_result = EmbeddingResult(vectors=vectors, texts=texts, metadatas=metadatas)
        embedder = get_embedder(exp_config.model_name, exp_config.model_type, getattr(exp_config, 'truncate_dim', 0))
        print(f"  从缓存加载: {vectors.shape}, 耗时: {time.time()-t0:.1f}s")
    else:
        print("[2/4] Embedding...")
        t0 = time.time()
        embedder = get_embedder(exp_config.model_name, exp_config.model_type, getattr(exp_config, 'truncate_dim', 0))
        embed_result = embedder.encode(all_chunks)
        print(f"  向量维度: {embed_result.vectors.shape}, 耗时: {time.time()-t0:.1f}s")
        # 保存缓存
        np.save(str(cache_vectors), embed_result.vectors)
        cache_texts.write_text(json.dumps(embed_result.texts, ensure_ascii=False), encoding="utf-8")
        cache_metadatas.write_text(json.dumps(embed_result.metadatas, ensure_ascii=False), encoding="utf-8")
        print(f"  缓存已保存到: {cache_dir}")

    # ---- Layer 4: 入库 ----
    print("[3/4] 入库 Chroma...")
    t0 = time.time()
    indexer = ChromaIndexer(
        persist_dir=CHROMA_ROOT / exp_config.name,
        collection_name=exp_config.name,
    )
    ids = [f"{c.metadata['source']}_{c.metadata['chunk_idx']}" for c in all_chunks]
    indexer.add(ids, embed_result.vectors, embed_result.texts, embed_result.metadatas)
    print(f"  入库 {indexer.count} 条, 耗时: {time.time()-t0:.1f}s")

    # ---- Layer 5+评测: 检索 + 评测 ----
    print("[4/4] 评测...")
    t0 = time.time()

    # 加载 reranker（如果配置了）
    reranker = None
    reranker_model = getattr(exp_config, 'reranker_model', '')
    if reranker_model:
        from sentence_transformers import CrossEncoder
        print(f"  加载 Reranker: {reranker_model}")
        reranker = CrossEncoder(reranker_model)

    def retriever_fn(question: str) -> list[str]:
        q_vec = embedder.encode_query(question)

        if reranker:
            # 两阶段：粗检索 top-20 → Reranker 精排 → top-5
            results = indexer.query(q_vec, n_results=20)
            if not results["metadatas"] or not results["metadatas"][0]:
                return []
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            pairs = [[question, doc] for doc in docs]
            scores = reranker.predict(pairs)
            ranked = sorted(zip(metas, scores), key=lambda x: -x[1])
            return [m["source"] for m, _ in ranked[:5]]
        else:
            # 单阶段：直接 top-5
            results = indexer.query(q_vec, n_results=5)
            sources = []
            if results["metadatas"] and results["metadatas"][0]:
                sources = [m["source"] for m in results["metadatas"][0]]
            return sources

    eval_result = evaluate_retrieval(eval_questions, retriever_fn, k=5)
    print(f"  Hit Rate: {eval_result['hit_rate']:.3f}")
    print(f"  MRR:      {eval_result['mrr']:.3f}")
    print(f"  耗时: {time.time()-t0:.1f}s")

    # ---- 保存结果 ----
    result_dir = RESULTS_DIR / exp_config.name
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "metrics.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "experiment": exp_config.name,
            "model": exp_config.model_name,
            "data": exp_config.data_key,
            "chunk_method": exp_config.chunk_method,
            "chunk_size": exp_config.chunk_size,
            "total_chunks": len(all_chunks),
            "hit_rate": eval_result["hit_rate"],
            "mrr": eval_result["mrr"],
        }, f, ensure_ascii=False, indent=2)
    print(f"  结果保存: {result_file}")

    # 保存每个问题的详细评测结果
    details_file = result_dir / "eval_details.json"
    with open(details_file, "w", encoding="utf-8") as f:
        json.dump(eval_result["details"], f, ensure_ascii=False, indent=2)
    print(f"  详情保存: {details_file}")

    # 保存每个问题的详细评测结果
    details_file = result_dir / "eval_details.json"
    with open(details_file, "w", encoding="utf-8") as f:
        json.dump(eval_result["details"], f, ensure_ascii=False, indent=2)
    print(f"  详情保存: {details_file}")

    return eval_result


def main():
    parser = argparse.ArgumentParser(description="RAG 对比实验")
    parser.add_argument("--exp", type=str, default="all", help="实验组名称，或 'all' 跑全部")
    args = parser.parse_args()

    # 加载评测集
    if not EVAL_FILE.exists():
        print(f"[错误] 评测集不存在: {EVAL_FILE}")
        print("请先准备 eval_questions.json")
        return

    eval_questions = load_eval_set(EVAL_FILE)
    print(f"评测集: {len(eval_questions)} 个问题")

    # 选择实验组
    if args.exp == "all":
        configs = EXPERIMENTS
    else:
        configs = [e for e in EXPERIMENTS if e.name == args.exp]
        if not configs:
            print(f"[错误] 未找到实验组: {args.exp}")
            print(f"可选: {[e.name for e in EXPERIMENTS]}")
            return

    # 逐组跑
    for config in configs:
        run_single_experiment(config, eval_questions)

    print(f"\n{'='*60}")
    print("全部实验完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()