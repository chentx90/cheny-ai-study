"""
RAG 对比实验配置
数据源：<DATA_ROOT>\data_clean\
"""

from dataclasses import dataclass
from pathlib import Path


# ============ 路径 ============

DATA_ROOT = Path(r"<DATA_ROOT>\data_clean")

DATA_PATHS = {
    "结构文本": DATA_ROOT / "3-结构文本",
    "混合文本": DATA_ROOT / "2-混合文本",
    "提取文本": DATA_ROOT / "1-提取文本",
    "pdf文件": DATA_ROOT / "4-pdf文件",
}

EVAL_FILE = Path(r"<REPO_ROOT>\06_项目作品集\02_知识问答\data\cleaned\10-评测集\eval_questions.json")
CHROMA_ROOT = Path(r"<REPO_ROOT>\06_项目作品集\02_知识问答\chroma_db")
RESULTS_DIR = Path(r"<REPO_ROOT>\06_项目作品集\02_知识问答\results")


# ============ 实验组定义 ============

@dataclass
class ExperimentConfig:
    name: str
    model_name: str
    model_type: str          # "text" | "multimodal"
    data_key: str            # DATA_PATHS 的 key
    chunk_method: str        # "title" | "recursive" | "length" | "page"
    chunk_size: int          # 对 length/recursive 有效
    chunk_overlap: int
    truncate_dim: int = 0    # 向量截断维度，0 表示不截断
    reranker_model: str = "" # Reranker 模型路径，空字符串表示不用


EXPERIMENTS = [
    ExperimentConfig(
        name="A1_structured_title",
        model_name="BAAI/bge-m3",
        model_type="text",
        data_key="结构文本",
        chunk_method="title",
        chunk_size=1024,
        chunk_overlap=128,
    ),
    ExperimentConfig(
        name="A2_mixed_recursive",
        model_name="BAAI/bge-m3",
        model_type="text",
        data_key="混合文本",
        chunk_method="recursive",
        chunk_size=1024,
        chunk_overlap=128,
    ),
    ExperimentConfig(
        name="A3_raw_length1024",
        model_name="BAAI/bge-m3",
        model_type="text",
        data_key="提取文本",
        chunk_method="length",
        chunk_size=1024,
        chunk_overlap=128,
    ),
    ExperimentConfig(
        name="B1_raw_length2048",
        model_name="BAAI/bge-m3",
        model_type="text",
        data_key="提取文本",
        chunk_method="length",
        chunk_size=2048,
        chunk_overlap=256,
    ),
    ExperimentConfig(
        name="C1_bge_large_zh",
        model_name=r"<MODELS_DIR>\bge-large-zh-v1.5",
        model_type="text",
        data_key="结构文本",
        chunk_method="title",
        chunk_size=1024,
        chunk_overlap=128,
    ),
    ExperimentConfig(
        name="D1_multimodal_pdf",
        model_name=r"<MODELS_DIR>\bge-vl-large",
        model_type="multimodal",
        data_key="pdf文件",
        chunk_method="page",
        chunk_size=0,
        chunk_overlap=0,
    ),
    ExperimentConfig(
        name="E1_dim768",
        model_name="BAAI/bge-m3",
        model_type="text",
        data_key="结构文本",
        chunk_method="title",
        chunk_size=1024,
        chunk_overlap=128,
        truncate_dim=768,
    ),
    ExperimentConfig(
        name="C2_large_zh_length1024",
        model_name=r"<MODELS_DIR>\bge-large-zh-v1.5",
        model_type="text",
        data_key="结构文本",
        chunk_method="length",
        chunk_size=1024,
        chunk_overlap=128,
    ),
    ExperimentConfig(
        name="C1_rerank",
        model_name=r"<MODELS_DIR>\bge-large-zh-v1.5",
        model_type="text",
        data_key="结构文本",
        chunk_method="title",
        chunk_size=1024,
        chunk_overlap=128,
        reranker_model=r"<MODELS_DIR>\bge-reranker-large",
    ),
]