from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentFormat(StrEnum):
    TXT = "txt"
    MARKDOWN = "markdown"
    DOCX = "docx"
    UNKNOWN = "unknown"


class EntityType(StrEnum):
    CHARACTER = "character"
    PROP = "prop"
    SCENE = "scene"


class PromptCategory(StrEnum):
    SPLIT_PLANNING = "split_planning"
    SCRIPT_CONVERT = "script_convert"
    ENTITY_EXTRACT = "entity_extract"
    ENTITY_CONSOLIDATE = "entity_consolidate"
    ENTITY_SETTING = "entity_setting"
    CHARACTER_ASSET_PROMPT = "character_asset_prompt"
    SCENE_ASSET_PROMPT = "scene_asset_prompt"
    PROP_ASSET_PROMPT = "prop_asset_prompt"
    SUBJECT_MATCH = "subject_match"
    SHOT_PLAN = "shot_plan"
    PROMPT_SPLIT = "prompt_split"
    VIDEO_GENERATE = "video_generate"
    PROMPT_RERUN = "prompt_rerun"
    VIDEO_AGENT = "video_agent"
    WORKFLOW_AGENT = "workflow_agent"


class WorkflowState(StrEnum):
    INITIALIZED = "initialized"
    DOCUMENT_SPLIT = "document_split"
    SCRIPT_CONVERTED = "script_converted"
    ENTITIES_EXTRACTED = "entities_extracted"
    ENTITIES_BOUND = "entities_bound"
    PROMPTS_GENERATED = "prompts_generated"
    ASSETS_CONFIRMED = "assets_confirmed"
    VIDEO_GENERATING = "video_generating"
    VIDEO_COMPLETED = "video_completed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SystemRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class ProjectVisibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


@dataclass
class User:
    username: str
    password_hash: str
    id: str = field(default_factory=lambda: new_id("user"))
    display_name: str = ""
    role: SystemRole = SystemRole.USER
    is_active: bool = True
    permissions: dict[str, bool | None] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class ProjectMember:
    project_id: str
    user_id: str
    role: ProjectRole = ProjectRole.VIEWER
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Project:
    name: str
    id: str = field(default_factory=lambda: new_id("proj"))
    category: str = "active"
    current_state: WorkflowState = WorkflowState.INITIALIZED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None
    owner_id: str | None = None
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    description: str = ""
    has_document: bool = False
    has_segments: bool = False
    has_scripts: bool = False
    has_entities: bool = False
    has_bindings: bool = False
    has_prompts: bool = False
    assets_confirmed: bool = False
    has_completed_video: bool = False


@dataclass
class Document:
    filename: str
    content: str
    format: DocumentFormat
    project_id: str
    id: str = field(default_factory=lambda: new_id("doc"))
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Segment:
    document_id: str
    order: int
    content: str
    id: str = field(default_factory=lambda: new_id("seg"))
    start_marker: str | None = None
    end_marker: str | None = None
    is_script: bool = False


@dataclass
class Script:
    segment_id: str
    content: str
    id: str = field(default_factory=lambda: new_id("script"))


@dataclass
class Entity:
    name: str
    type: EntityType
    state: str | None = None
    context: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class EntityCard:
    entity_name: str
    type: EntityType
    id: str = field(default_factory=lambda: new_id("card"))
    project_id: str | None = None
    state: str | None = None
    assets: list[str] = field(default_factory=list)
    reference_images: list[str] = field(default_factory=list)
    audio_samples: list[str] = field(default_factory=list)
    video_clips: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class EntityMaterial:
    project_id: str
    entity_name: str
    type: EntityType
    asset_path: str
    id: str = field(default_factory=lambda: new_id("mat"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class EntityBinding:
    entity: Entity
    card: EntityCard | None
    confidence: float
    confirmed: bool = False
    id: str = field(default_factory=lambda: new_id("bind"))


@dataclass
class PromptCard:
    project_id: str
    segment_id: str
    order: int
    title: str
    prompt_text: str
    anchor_text: str = ""
    duration: float = 0.0
    source_text: str = ""
    source_start: int = 0
    source_end: int = 0
    source_hash: str = ""
    status: str = "draft"
    locked: bool = False
    id: str = field(default_factory=lambda: new_id("pcard"))
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class PromptTemplate:
    name: str
    category: PromptCategory
    template: str
    variables: list[str]
    id: str = field(default_factory=lambda: new_id("tpl"))
    examples: list[dict[str, Any]] = field(default_factory=list)
    is_default: bool = False
    version: int = 1


@dataclass
class VideoTask:
    project_id: str
    segment_id: str
    prompt: str
    assets: dict[str, Any] = field(default_factory=dict)
    duration: int | None = None
    prompt_card_id: str | None = None
    source_prompt_hash: str = ""
    id: str = field(default_factory=lambda: new_id("task"))
    status: TaskStatus = TaskStatus.PENDING
    result_path: str | None = None
    api_task_id: str | None = None
    provider: str = "unconfigured"
    is_preview: bool = False
    version: int = 1
    prompt_version: int = 1
    request_snapshot: dict[str, Any] = field(default_factory=dict)
    attempt: int = 0
    orphaned: bool = False
    error_message: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Checkpoint:
    project_id: str
    state: WorkflowState
    data: dict[str, Any]
    id: str = field(default_factory=lambda: new_id("chk"))
    created_at: datetime = field(default_factory=utc_now)
