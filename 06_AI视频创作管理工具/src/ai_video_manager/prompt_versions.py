"""Prompt card version labels and helpers."""

from __future__ import annotations

VERSION_TYPE_LABELS = {
    "generated": "生成",
    "rerun": "重跑",
    "edited": "手工",
}


def version_type_label(version_type: str) -> str:
    return VERSION_TYPE_LABELS.get(str(version_type or "").strip(), "版本")
