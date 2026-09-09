from __future__ import annotations

from pydantic import BaseModel, Field

from ai_video_manager.models import EntityType, PromptCategory, WorkflowState

class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    category: str = "active"
    description: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None


class ProjectMemberRequest(BaseModel):
    user_id: str | None = None
    username: str | None = None
    role: str = Field(min_length=1)


class ProjectVisibilityRequest(BaseModel):
    visibility: str = Field(min_length=1)

class ProjectSegmentPayload(BaseModel):
    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = ""
    content: str = ""


class SaveProjectDocumentRequest(BaseModel):
    document_text: str | None = None
    split_strategy: str | None = None
    custom_split_pattern: str | None = None
    duration_minutes: float | None = Field(default=None, gt=0, le=30)
    active_segment_id: str | None = None
    content_type: str | None = None
    script_convert_template_id: str | None = None
    revision: int | None = None


class SaveProjectSegmentsRequest(BaseModel):
    segments: list[ProjectSegmentPayload] = Field(default_factory=list)
    active_segment_id: str | None = None
    clear_downstream: bool = False
    revision: int | None = None


class SaveProjectScriptRequest(BaseModel):
    content: str = ""
    validation: dict[str, object] = Field(default_factory=dict)
    revision: int | None = None


class SaveProjectScriptsRequest(BaseModel):
    scripts: dict[str, str] = Field(default_factory=dict)
    script_validation: dict[str, dict[str, object]] = Field(default_factory=dict)
    revision: int | None = None


class SaveProjectSettingsRequest(BaseModel):
    expected_total_duration_seconds: float | None = None
    default_aspect_ratio: str | None = None
    default_video_duration: int | None = Field(default=None, ge=1, le=60)
    default_video_model: str | None = None
    default_resolution: str | None = None
    project_style_prompt: str | None = None
    output_root: str | None = None
    source_assets_root: str | None = None
    data_root: str | None = None
    revision: int | None = None


class ImportProjectBundleRequest(BaseModel):
    path: str = ""
    name: str | None = None


class ConfirmAssetsRequest(BaseModel):
    confirmed: bool = True

class SaveApiConfigRequest(BaseModel):
    data: dict[str, object]

class TestLLMConnectionRequest(BaseModel):
    use_case: str
    data: dict[str, object] | None = None

class IngestDocumentRequest(BaseModel):
    project_id: str
    path: str

class SplitDocumentRequest(BaseModel):
    content: str
    strategy: str = "chapter"
    max_chars: int = 1200
    custom_pattern: str | None = None
    duration_minutes: float = Field(default=2.0, gt=0, le=30)
    project_id: str | None = None
    persist: bool = False
    mark_orphaned_tasks: bool = True

class ConvertSegmentRequest(BaseModel):
    segment_id: str = "seg_inline"
    order: int = 1
    content: str
    source_format: str | None = None
    content_type: str = "分集原文"
    template_id: str | None = None

class ValidateScriptRequest(BaseModel):
    content: str

class EntityCardRequest(BaseModel):
    name: str
    type: EntityType
    state: str | None = None
    tags: list[str] = Field(default_factory=list)

class SaveEntityCardRequest(BaseModel):
    entity_name: str
    type: EntityType
    state: str | None = None
    tags: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    reference_images: list[str] = Field(default_factory=list)
    audio_samples: list[str] = Field(default_factory=list)
    video_clips: list[str] = Field(default_factory=list)

class UploadAssetRequest(BaseModel):
    asset_type: str
    filename: str
    content_base64: str

class RenameAssetRequest(BaseModel):
    filename: str = Field(min_length=1)

class SaveEntityMaterialsRequest(BaseModel):
    entity_name: str = Field(min_length=1)
    type: EntityType
    asset_paths: list[str] = Field(default_factory=list)

class UploadDocumentRequest(BaseModel):
    filename: str
    content_base64: str

class RenderPromptRequest(BaseModel):
    template_name_or_id: str
    context: dict[str, object]

class GeneratePromptRequest(BaseModel):
    template_name_or_id: str | None = None
    context: dict[str, object]

class GeneratePromptCardsRequest(BaseModel):
    script: str = Field(min_length=1)
    template_name_or_id: str | None = None
    max_duration_seconds: float | str | None = 15.0
    expected_total_duration_seconds: float | str | None = None
    replace: bool = True

class SavePromptCardRequest(BaseModel):
    title: str = Field(min_length=1)
    prompt_text: str = ""
    anchor_text: str = ""
    duration: float = Field(default=0.0, ge=0, le=600)
    status: str = "draft"
    locked: bool | None = None
    source_text: str | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=0)

class RerunPromptCardRequest(BaseModel):
    script: str = Field(min_length=1)
    template_name_or_id: str | None = None
    max_duration_seconds: float = Field(default=15.0, ge=3, le=60)

class SavePromptCardSubjectsRequest(BaseModel):
    entity_card_ids: list[str] = Field(default_factory=list)

class ResolveMentionsRequest(BaseModel):
    prompt_text: str = ""
    existing_anchor_text: str = ""
    apply: bool = False

class CreatePromptTemplateRequest(BaseModel):
    name: str
    category: PromptCategory
    template: str
    variables: list[str] = Field(default_factory=list)

class WorkflowJumpRequest(BaseModel):
    project_id: str
    target_state: WorkflowState

class LoadCheckpointRequest(BaseModel):
    checkpoint_id: str

class GenerateVideoRequest(BaseModel):
    project_id: str
    segment_id: str
    prompt: str
    assets: dict[str, object] = Field(default_factory=dict)
    duration: int | None = None
    model: str | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    preview: bool = False
    prompt_card_id: str | None = None
    reference_mode: str = "omni"
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: list[str] = Field(default_factory=list)
    reference_videos: list[str] = Field(default_factory=list)
    reference_audios: list[str] = Field(default_factory=list)
    generate_audio: bool = True

class GeneratePromptCardVideoRequest(BaseModel):
    assets: dict[str, object] = Field(default_factory=dict)
    duration: int | None = None
    model: str | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    preview: bool = False
    reference_mode: str = "omni"
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: list[str] = Field(default_factory=list)
    reference_videos: list[str] = Field(default_factory=list)
    reference_audios: list[str] = Field(default_factory=list)
    generate_audio: bool = True


class RetryVideoTaskRequest(BaseModel):
    """Optional overrides when re-submitting a video task (prompt, refs, gateway params)."""

    prompt: str | None = None
    duration: int | None = None
    model: str | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    reference_mode: str | None = None
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: list[str] | None = None
    reference_videos: list[str] | None = None
    reference_audios: list[str] | None = None
    generate_audio: bool | None = None


class GenerateEntityReferenceImageRequest(BaseModel):
    """Generate a reference image; model/size chosen on the image UI per request."""

    prompt: str | None = None
    style: str = ""
    use_llm: bool = True
    parallel_count: int = 1
    attach_to_card: bool = True
    model: str | None = None
    size: str | None = None


class GenerateProjectImageRequest(BaseModel):
    """Freeform image generation for the dedicated 生图 page."""

    prompt: str
    model: str
    size: str = "1024x1024"
    parallel_count: int = 1
    entity_card_id: str | None = None
    attach_to_card: bool = False
    use_llm: bool = False
    style: str = ""


class RecoverVideoTaskRequest(BaseModel):
    """Optional remote task id when local record lost api_task_id after a network blip."""

    api_task_id: str | None = None
