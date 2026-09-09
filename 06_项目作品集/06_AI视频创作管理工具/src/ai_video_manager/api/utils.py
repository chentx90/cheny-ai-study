from __future__ import annotations

from dataclasses import asdict

from fastapi import HTTPException

from ai_video_manager.document_processor import (
    ChapterSplitStrategy,
    CustomRegexSplitStrategy,
    DurationSplitStrategy,
    LengthSplitStrategy,
    ManualMarkerSplitStrategy,
)

def _strategy(
    name: str,
    max_chars: int,
    llm_client: object | None = None,
    custom_pattern: str | None = None,
    duration_minutes: float = 2.0,
):
    if name == "chapter":
        return ChapterSplitStrategy()
    if name == "custom_regex":
        return CustomRegexSplitStrategy(custom_pattern or "")
    if name == "manual":
        return ManualMarkerSplitStrategy()
    if name == "length":
        return LengthSplitStrategy(max_chars=max_chars)
    if name in {"duration", "duration_2min"}:
        return DurationSplitStrategy(minutes=duration_minutes, llm_client=llm_client)
    raise HTTPException(status_code=400, detail=f"Unsupported split strategy: {name}")

def _dump(value):
    if value is None:
        return None
    data = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    return _jsonable(data)

def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
