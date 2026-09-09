# 知识问答 RAG 系统 · 对比实验

基于 4-5 万份内部归档文档，构建本地 RAG 问答系统。通过控制变量实验对比不同数据处理、分块策略、embedding 模型的检索效果。

## 实验矩阵

| 组 | 模型 | 数据类型 | 切块方式 |
|---|---|---|---|
| A1 | BGE-M3 (568M) | 结构文本 | 标题分割 |
| A2 | BGE-M3 (568M) | 混合文本 | 递归分割 |
| A3 | BGE-M3 (568M) | 提取文本 | 长度 1024 |
| B1 | BGE-M3 (568M) | 提取文本 | 长度 2048 |
| C1 | BGE-Large-zh-v1.5 (326M) | 结构文本 | 标题分割 |
| D1 | BGE-VL-Large (428M) | PDF 文件 | 按页分割 |

## 评测指标

- Hit Rate@5: top-5 召回至少命中一个金标的比例
- MRR@5: 金标文档平均倒数排名

## 项目结构

```
02_知识问答/
├── config.py              # 实验参数配置
├── run_experiment.py      # 主入口
├── src/
│   ├── chunker.py         # 分块模块
│   ├── embedder.py        # Embedding 模块
│   ├── indexer.py         # Chroma 向量库
│   └── evaluator.py       # 评测模块
├── chroma_db/             # 向量库持久化（gitignore）
└── results/               # 实验结果
```

## 用法

```bash
# 跑单组
python run_experiment.py --exp A1_structured_title

# 跑全部
python run_experiment.py --exp all
```

## 技术栈

- Python 3.11
- sentence-transformers (BGE-M3 / BGE-Large-zh)
- chromadb
- langchain (text_splitter)
- pypdfium2

## 数据安全

- 所有 embedding 和检索在本地完成
- 数据目录不进 Git
- 仅查询阶段经过 NewAPI 聚合层（可控）