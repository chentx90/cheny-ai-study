"""结构化数据资产构建器。

将来自 Excel 或其他来源的原始行数据，转换为 ``DataAsset`` 对象。

关键职责：

- 自动推断 ``asset_type``：优先读取行中的 ``type`` 字段，否则根据 sheet
  名称映射（如 "tables" → "table"）。
- 处理 ``parent_name``、``formula``、``related_table``、``related_columns``
  等结构化字段的格式化。
- 将逗号分隔的字符串正确解析为 ``List[str]``。
"""
from typing import List, Dict, Any
from ..schemas import DataAsset


class DataAssetBuilder:
    """将原始行数据构建为 ``DataAsset`` 的处理器。"""

    def build_from_excel(self, sheet_name: str, row: Dict[str, Any], business_domain: str) -> DataAsset:
        """根据 sheet 名称和行数据构建 ``DataAsset``。

        自动判断 ``asset_type`` 并格式化各字段。

        Args:
            sheet_name: 来源 sheet 名称（如 "tables"、"metrics"）。
            row: Excel 行的字典表示（通常来自 ``df.iterrows()``）。
            business_domain: 业务领域标识。

        Returns:
            构建完成的 ``DataAsset``。
        """
        asset_type = self._guess_type(sheet_name, row)
        return DataAsset(
            asset_type=asset_type,
            name=str(row.get("name", "")).strip(),
            description=str(row.get("description", "")).strip(),
            business_domain=business_domain,
            parent_name=str(row.get("parent_name", "")).strip() or None,
            synonyms=self._split(row.get("synonyms", "")),
            formula=str(row.get("formula", "")).strip() or None,
            related_table=str(row.get("related_table", "")).strip() or None,
            related_columns=self._split(row.get("related_columns", "")),
            example_values=row.get("example_values") if row.get("example_values") else None,
        )

    def _guess_type(self, sheet_name: str, row: Dict[str, Any]) -> str:
        """推断资产类型。

        优先级：

        1. 行中的 ``type`` 字段值。
        2. sheet 名称的固定映射字典。

        Args:
            sheet_name: 来源 sheet 名称。
            row: 行数据字典。

        Returns:
            资产类型字符串（小写）。
        """
        if "type" in row and str(row["type"]).strip():
            return str(row["type"]).strip().lower()
        mapping = {
            "tables": "table",
            "columns": "column",
            "metrics": "metric",
            "cases": "case",
            "tools": "tool",
        }
        return mapping.get(sheet_name.lower(), "unknown")

    def _split(self, value: Any) -> List[str]:
        """安全地将逗号分隔值解析为字符串列表。"""
        if value is None:
            return []
        text = str(value).strip()
        if not text:
            return []
        return [item.strip() for item in text.split(",") if item.strip()]
