from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EpisodeStatus(StrEnum):
    SOURCE_READY = "source_ready"
    SCRIPT_READY = "script_ready"


class AIRunUseCase(StrEnum):
    DURATION_SPLIT = "duration_split"
    SCRIPT_CONVERT = "script_convert"
    PROMPT_GENERATE = "prompt_generate"
    PROMPT_RERUN = "prompt_rerun"
    SUBJECT_MATCH = "subject_match"
    ENTITY_EXTRACT = "entity_extract"
    ENTITY_CONSOLIDATE = "entity_consolidate"
    ENTITY_SETTING = "entity_setting"
    CHARACTER_ASSET_PROMPT = "character_asset_prompt"
    SCENE_ASSET_PROMPT = "scene_asset_prompt"
    PROP_ASSET_PROMPT = "prop_asset_prompt"


class AIRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MatchSource(StrEnum):
    LLM = "llm"
    MANUAL = "manual"


@dataclass(slots=True)
class Episode:
    project_id: str
    order: int
    title: str
    source_text: str
    id: str = field(default_factory=lambda: _id("ep"))
    document_id: str | None = None
    script_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    script_validation: dict[str, Any] = field(default_factory=dict)
    source_start: int = 0
    source_end: int = 0
    status: EpisodeStatus = EpisodeStatus.SOURCE_READY
    revision: int = 0
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def save_script(self, text: str) -> None:
        self.script_text = text.strip()
        self.status = EpisodeStatus.SCRIPT_READY if self.script_text else EpisodeStatus.SOURCE_READY
        self.revision += 1
        self.updated_at = _now()


@dataclass(slots=True)
class PromptCardEntityLink:
    project_id: str
    prompt_card_id: str
    entity_card_id: str
    source: MatchSource
    id: str = field(default_factory=lambda: _id("pcel"))
    confidence: float | None = None
    confirmed: bool = False
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class VideoOutput:
    project_id: str
    video_task_id: str
    prompt_card_id: str | None
    storage_path: str
    id: str = field(default_factory=lambda: _id("vout"))
    metadata: dict[str, Any] = field(default_factory=dict)
    adopted: bool = False
    created_at: datetime = field(default_factory=_now)
