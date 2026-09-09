"""Excel 文件加载器。

支持两种输出模式：

1. **结构化模式**（``load_data_assets``）：读取预定义的 sheet（tables、columns、
   metrics、cases、tools），将每行数据转换为 ``DataAsset`` 对象列表。
   用于从设计文档 Excel 中批量提取结构化资产信息。
2. **文本模式**（``load_as_text``）：读取所有 sheet，将每个 sheet 格式化为
   Markdown 表格文字，输出 ``LoadedDocument``，供后续 ``Chunker`` 分块。

Do note: the schemas import for LoadedDocument and RawPage are resolved via the shared
``app.schemas``; if these types are defined in additional schema files, the import chain
should be updated accordingly.
"""
from pathlib import Path
from typing import List, Any
import pandas as pd
from ..schemas import DataAsset, LoadedDocument, RawPage


class ExcelLoader:
    """Excel 文件加载器，提供结构化资产提取和文本化两层能力。"""

    EXPECTED_SHEETS = ["tables", "columns", "metrics", "cases", "tools"]

    def load_data_assets(self, file_path: str, business_domain: str = "general") -> List[DataAsset]:
        """从预期 sheet 中提取结构化 ``DataAsset`` 列表。

        只读取 ``EXPECTED_SHEETS`` 中定义的 sheet 名称，跳过其他 sheet。

        Args:
            file_path: Excel 文件路径。
            business_domain: 业务领域标识。

        Returns:
            ``DataAsset`` 对象列表，每行对应一个资产。
        """
        path = Path(file_path)
        excel_file = pd.ExcelFile(file_path)
        assets: List[DataAsset] = []
        for sheet_name in excel_file.sheet_names:
            if sheet_name not in self.EXPECTED_SHEETS:
                continue
            df = pd.read_excel(excel_file, sheet_name=sheet_name).fillna("")
            assets.extend(self._parse_sheet(sheet_name, df, business_domain))
        return assets

    def load_as_text(self, file_path: str, title: str = "", business_domain: str = "general", doc_type: str = "excel") -> LoadedDocument:
        """将所有 sheet 文本化，输出 ``LoadedDocument``。

        每个 sheet 被格式化为 Markdown 表格文字，供下游 ``Chunker`` 分块。

        Args:
            file_path: Excel 文件路径。
            title: 文档标题，为空则使用文件名。
            business_domain: 业务领域标识。
            doc_type: 文档类型标识。

        Returns:
            包含所有 sheet 文本页的 ``LoadedDocument``。
        """
        path = Path(file_path)
        from backend.app.services.excel_extractor import extract_excel_markdown

        extracted = extract_excel_markdown(path)
        pages: List[RawPage] = [
            RawPage(
                page_number=i + 1,
                text=sheet.text,
                metadata={
                    "sheet": sheet.name,
                    "rows": sheet.rows,
                    "columns": sheet.columns,
                    "tables": sheet.tables,
                },
            )
            for i, sheet in enumerate(extracted.sheets)
        ]
        return LoadedDocument(
            title=title or path.stem,
            source_uri=str(path),
            doc_type=doc_type,
            business_domain=business_domain,
            pages=pages,
        )

    def _parse_sheet(self, sheet_name: str, df: pd.DataFrame, business_domain: str) -> List[DataAsset]:
        """解析单个 sheet 的逐行数据为 ``DataAsset`` 列表。

        自动将 sheet 名转换为 asset_type（去除末尾 "s"，如 "tables" → "table"）。
        对 metrics sheet 额外处理 formula、related_table、related_columns 字段。

        Args:
            sheet_name: 当前 sheet 名称。
            df: 该 sheet 的 DataFrame。
            business_domain: 业务领域标识。

        Returns:
            ``DataAsset`` 对象列表。
        """
        assets: List[DataAsset] = []
        for _, row in df.iterrows():
            if not str(row.get("name", "")).strip():
                continue
            assets.append(DataAsset(
                asset_type=sheet_name.rstrip("s"),
                name=str(row["name"]).strip(),
                description=str(row.get("description", "")).strip(),
                business_domain=business_domain,
                parent_name=str(row.get("parent_name", "")).strip() or None,
                synonyms=self._split_list(row.get("synonyms", "")),
                formula=str(row.get("formula", "")).strip() or None if sheet_name == "metrics" else None,
                related_table=str(row.get("related_table", "")).strip() or None if sheet_name == "metrics" else None,
                related_columns=self._split_list(row.get("related_columns", "")) if sheet_name == "metrics" else [],
            ))
        return assets

    def _split_list(self, value: Any) -> List[str]:
        """将逗号分隔的字符串拆分为列表。"""
        text = str(value).strip() if value is not None else ""
        return [item.strip() for item in text.split(",") if item.strip()]
