"""M0 结构化 JSON 产物 schema。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ArtifactStatus(StrEnum):
    draft = "draft"
    validated = "validated"
    human_approved = "human_approved"
    failed = "failed"


class Importance(StrEnum):
    major = "major"
    minor = "minor"


class RawSpan(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_order(self) -> "RawSpan":
        if self.end < self.start:
            raise ValueError("raw_span.end must be >= raw_span.start")
        return self


class WorkMeta(StrictModel):
    id: str
    title: str
    source_meta: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    status: ArtifactStatus = ArtifactStatus.draft
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class StyleGuide(StrictModel):
    narrative_style: str
    visual_style: str
    palette: str = ""
    render_keywords: str = ""
    camera_language: str = ""
    negative_prompt: str = ""


class Scene(StrictModel):
    id: str
    episode_idx: int = Field(ge=0)
    idx: int = Field(ge=0)
    time: str = ""
    location: str = ""
    pov: str = ""
    summary: str = ""
    raw_span: RawSpan
    status: ArtifactStatus = ArtifactStatus.draft


class Episode(StrictModel):
    id: str
    idx: int = Field(ge=0)
    title: str
    summary: str = ""
    raw_span: RawSpan | None = None
    scenes: list[Scene] = Field(default_factory=list)
    status: ArtifactStatus = ArtifactStatus.draft

    @field_validator("scenes")
    @classmethod
    def scenes_sorted(cls, scenes: list[Scene]) -> list[Scene]:
        indexes = [s.idx for s in scenes]
        if indexes != sorted(indexes):
            raise ValueError("episode.scenes must be sorted by idx")
        return scenes


class EntityAttr(StrictModel):
    key: str
    value: str
    source_scene: str = ""
    confidence: float = Field(ge=0, le=1, default=1.0)


class EntityVariant(StrictModel):
    """角色/实体的外观变体（如不同年龄阶段）。"""
    label: str = Field(description="变体标签，如'幼年哥哥''成年妹妹'")
    time_desc: str = Field(description="生效时间描述，如'0-10岁''第5集后'")
    appearance: str = Field(description="完整外观描述，用于 prompt 绑定")
    ref_images: list[str] = Field(default_factory=list, description="参考图片相对路径列表")
    ref_audios: list[str] = Field(default_factory=list, description="参考音频相对路径列表")
    ref_videos: list[str] = Field(default_factory=list, description="参考视频相对路径列表")
    ref_image: str = Field(default="", description="[已废弃] 兼容旧数据，会自动迁移到 ref_images")

    @model_validator(mode="after")
    def migrate_ref_image(self) -> "EntityVariant":
        """将旧的 ref_image 字段迁移到 ref_images 列表。"""
        if self.ref_image and self.ref_image not in self.ref_images:
            self.ref_images.append(self.ref_image)
        return self

    def media_paths(self, kind: Literal["image", "audio", "video"]) -> list[str]:
        if kind == "image":
            return self.ref_images
        if kind == "audio":
            return self.ref_audios
        return self.ref_videos


class Entity(StrictModel):
    id: str
    type: Literal["character", "location", "prop"]
    name: str
    aliases: list[str] = Field(default_factory=list)
    importance: Importance = Importance.minor
    status: ArtifactStatus = ArtifactStatus.draft
    attrs: list[EntityAttr] = Field(default_factory=list)
    variants: list[EntityVariant] = Field(default_factory=list)
    appearance_count: int = Field(default=0, ge=0, description="出现的场景数，用于过滤一次性实体")


class Relation(StrictModel):
    id: str
    subject_id: str
    object_id: str
    relation: str
    source_scene: str = ""
    status: ArtifactStatus = ArtifactStatus.draft


class ShotEntityBinding(StrictModel):
    """Shot 中角色的实体绑定结果（M5 产物）。"""
    character_key: str = Field(description="Screenwriter 提取的角色称呼（如'哥哥'）")
    entity_id: str = Field(description="映射到的实体 ID")
    variant_label: str = Field(default="", description="匹配到的变体标签（如'高中哥哥'），未匹配为空")
    confidence: float = Field(default=1.0, ge=0, le=1)


class Shot(StrictModel):
    id: str
    scene_id: str
    idx: int = Field(ge=0)
    shot_type: str
    action: str
    emotion: str = ""
    dialogue: str = ""
    duration: float = Field(ge=0, default=4.0)
    characters: list[str] = Field(default_factory=list, description="Screenwriter 提取的角色称呼")
    matched_entities: list[ShotEntityBinding] = Field(
        default_factory=list, description="M5 产物：角色→实体绑定"
    )
    image_prompt: str = ""
    video_prompt: str = ""
    status: ArtifactStatus = ArtifactStatus.draft


class BindingItem(StrictModel):
    entity_id: str
    role: str = "present"
    variant_label: str = Field(default="", description="绑定的变体标签")
    appearance_snapshot: str = Field(default="", description="本镜头中该实体的外观快照")
    confidence: float = Field(default=1.0, ge=0, le=1)


class BindingFile(StrictModel):
    scene_id: str = Field(default="")
    bindings: dict[str, list[BindingItem]] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list, description="本场景绑定发现的问题")


class Summary(StrictModel):
    episode_idx: int = Field(ge=0)
    episode_summary: str = Field(default="", description="本集摘要（从场景压缩）")
    rolling_summary: str = Field(default="", description="截至本集的滚动摘要（前情提要）")
    summary: str = Field(default="", description="[兼容旧] 本集摘要，优先使用 episode_summary")
    source_scene_ids: list[str] = Field(default_factory=list)
    token_estimate: int = Field(default=0, description="rolling_summary 的 token 估算")
    status: ArtifactStatus = ArtifactStatus.draft

    @model_validator(mode="after")
    def migrate_summary(self) -> "Summary":
        if self.summary and not self.episode_summary:
            self.episode_summary = self.summary
        return self


class RunState(StrictModel):
    stage: str = "M0"
    cursor: dict[str, Any] = Field(default_factory=dict)
    status: ArtifactStatus = ArtifactStatus.draft
    retry_budget: dict[str, int] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class WorkIndex(StrictModel):
    entity_name_to_id: dict[str, str] = Field(default_factory=dict)
    alias_to_id: dict[str, str] = Field(default_factory=dict)
    scene_to_entities: dict[str, list[str]] = Field(default_factory=dict)
    shot_to_scene: dict[str, str] = Field(default_factory=dict)


class Operation(StrictModel):
    time: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    command: str
    detail: str = ""
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ValidationIssue(StrictModel):
    path: str
    severity: Literal["error", "warning"] = "error"
    message: str


class ValidationReport(StrictModel):
    work_id: str
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
