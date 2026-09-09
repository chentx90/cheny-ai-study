"""种子文件加载器。

从预定义的 JSON 文件中读取数据，输出 ``Document`` 或 ``List[DataAsset]``，
用于独立运行时或测试中快速生成样本数据。

支持两种模式：

1. ``load_json_seed``：读取包含 ``chunks`` 字段的 JSON，输出 ``Document``。
2. ``load_data_assets_seed``：读取包含 ``data_assets`` 数组的 JSON，输出
   ``DataAsset`` 列表。
"""
import json
from pathlib import Path
from typing import List
from ..schemas import Document, Chunk, DataAsset


def load_json_seed(file_path: str) -> Document:
    """从 JSON 种子文件加载文档数据。

    读取格式示例：

    .. code-block:: json

        {
            "title": "设备操作手册",
            "doc_type": "manual",
            "source_uri": "file:///path/to/manual.json",
            "business_domain": "equipment",
            "version": "1.0",
            "chunks": [
                {
                    "section_path": "液压系统",
                    "title_context": "设备操作手册",
                    "content": "...",
                    "summary": "...",
                    "preset_questions": ["..."]
                }
            ]
        }

    Args:
        file_path: JSON 种子文件的路径。

    Returns:
        解析后的 ``Document`` 对象。
    """
    data = json.loads(Path(file_path).read_text(encoding="utf-8"))

    if "chunks" in data:
        chunks = [
            Chunk(
                section_path=c.get("section_path", ""),
                title_context=c.get("title_context", data.get("title", "")),
                content=c.get("content", ""),
                summary=c.get("summary", ""),
                preset_questions=c.get("preset_questions", [])
            )
            for c in data["chunks"]
        ]
    else:
        chunks = []

    return Document(
        title=data.get("title", "Untitled"),
        doc_type=data.get("doc_type", "json"),
        source_uri=data.get("source_uri"),
        business_domain=data.get("business_domain", "general"),
        version=data.get("version", "1.0"),
        chunks=chunks
    )


def load_data_assets_seed(file_path: str) -> List[DataAsset]:
    """从 JSON 种子文件加载数据结构资产。

    读取格式示例：

    .. code-block:: json

        {
            "data_assets": [
                {
                    "asset_type": "table",
                    "name": "production_order",
                    "description": "生产工单表",
                    "business_domain": "manufacturing",
                    "synonyms": ["工单", "生产单"],
                    "formula": null,
                    "related_table": null,
                    "related_columns": ["id", "product_id", "quantity"],
                    "example_values": {"status": "in_progress"}
                }
            ]
        }

    Args:
        file_path: JSON 种子文件的路径。

    Returns:
        ``DataAsset`` 对象列表。
    """
    data = json.loads(Path(file_path).read_text(encoding="utf-8"))
    return [
        DataAsset(
            asset_type=item.get("asset_type", "unknown"),
            name=item.get("name", ""),
            description=item.get("description", ""),
            business_domain=item.get("business_domain", "general"),
            parent_name=item.get("parent_name"),
            synonyms=item.get("synonyms", []),
            formula=item.get("formula"),
            related_table=item.get("related_table"),
            related_columns=item.get("related_columns", []),
            example_values=item.get("example_values")
        )
        for item in data.get("data_assets", [])
    ]