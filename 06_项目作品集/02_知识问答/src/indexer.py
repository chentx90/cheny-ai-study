"""
indexer.py - Chroma 向量库索引模块
"""

import json
import chromadb
from pathlib import Path


class ChromaIndexer:
    def __init__(self, persist_dir: Path, collection_name: str):
        """创建持久化 client + 获取/创建 collection"""
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add(self, ids: list[str], embeddings, documents: list[str], metadatas: list[dict]):
        """批量入库。"""
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()

        # Chroma 不支持嵌套 dict/list/None，清洗 metadata
        clean_metadatas = []
        for m in metadatas:
            clean = {}
            for k, v in m.items():
                if isinstance(v, (dict, list)):
                    clean[k] = json.dumps(v, ensure_ascii=False)
                elif v is None:
                    clean[k] = ""
                else:
                    clean[k] = v
            clean_metadatas.append(clean)

        # 分批入库
        batch_size = 5000
        for i in range(0, len(ids), batch_size):
            self.collection.add(
                ids=ids[i:i+batch_size],
                embeddings=embeddings[i:i+batch_size],
                documents=documents[i:i+batch_size],
                metadatas=clean_metadatas[i:i+batch_size],
            )

    def query(self, query_embedding, n_results: int = 5) -> dict:
        """检索 top-K。"""
        if hasattr(query_embedding, "tolist"):
            query_embedding = query_embedding.tolist()

        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

    @property
    def count(self) -> int:
        return self.collection.count()