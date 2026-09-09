import json
import re
from pathlib import Path
from typing import Optional, Union
from ..schemas import Document, LoadedDocument, DataAsset


def _safe_filename(name: str) -> str:
    """将字符串转换为安全的文件名（去除非法字符）。"""
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return Path(name).name


class JsonWriter:
    """JSON 文件写入器，用于将 ``Document`` 或 ``DataAsset`` 序列化为 JSON 文件。

    主要用途：

    1. **开发调试**：在流水线运行后，将中间结果写入指定目录，方便人工审核。
    2. **CI 测试**：将解析结果写入文件，与预期 JSON 进行对比（snapshot testing）。
    3. **独立 CLI**：ingestion 独立运行时，作为无数据库时的输出媒介。
    """

    def __init__(self, output_dir: str):
        """初始化 JSON 写入器。

        Args:
            output_dir: JSON 文件输出目录。若目录不存在，会自动创建。
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_document(self, document: Union[Document, LoadedDocument], filename: Optional[str] = None) -> str:
        """将 ``Document`` 或 ``LoadedDocument`` 序列化为 JSON 文件并写入输出目录。

        Args:
            document: 待写入的对象，支持 ``Document``（含 chunks）或 ``LoadedDocument``（含 pages）。
            filename: 可选的文件名（不含路径），为空则使用 ``document.title``。

        Returns:
            写入文件的完整路径。
        """
        if not filename:
            filename = _safe_filename(document.title) + ".json"
        path = self.output_dir / filename
        
        if isinstance(document, LoadedDocument):
            payload = {
                "title": document.title,
                "source_uri": document.source_uri,
                "doc_type": document.doc_type,
                "business_domain": document.business_domain,
                "pages": [
                    {
                        "page_number": p.page_number,
                        "text": p.text,
                        "metadata": p.metadata,
                    }
                    for p in document.pages
                ],
            }
        else:
            payload = {
                "title": document.title,
                "doc_type": document.doc_type,
                "source_uri": getattr(document, "source_uri", None),
                "business_domain": getattr(document, "business_domain", None),
                "version": getattr(document, "version", None),
                "status": getattr(document, "status", "active"),
                "chunks": [
                    {
                        "section_path": c.section_path,
                        "title_context": c.title_context,
                        "content": c.content,
                        "summary": c.summary,
                        "preset_questions": c.preset_questions,
                        "physical_context": c.physical_context,
                    }
                    for c in document.chunks
                ],
            }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def write_data_asset(self, asset: DataAsset, filename: Optional[str] = None) -> str:
        """将 ``DataAsset`` 序列化为 JSON 文件并写入输出目录。

        Args:
            asset: 待写入的 ``DataAsset``。
            filename: 可选的文件名（不含路径），为空则使用 ``asset.name``。

        Returns:
            写入文件的完整路径。
        """
        if not filename:
            filename = _safe_filename(asset.name) + ".json"
        path = self.output_dir / filename
        payload = {
            "asset_type": asset.asset_type,
            "name": asset.name,
            "description": asset.description,
            "business_domain": asset.business_domain,
            "parent_name": asset.parent_name,
            "synonyms": asset.synonyms,
            "formula": asset.formula,
            "related_table": asset.related_table,
            "related_columns": asset.related_columns,
            "example_values": asset.example_values,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
