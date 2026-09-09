from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.auth.permissions import require_user
from ai_video_manager.image_generation import ImageGenerationError


class RunAnalysisRequest(BaseModel):
    episode_ids: list[str] = Field(default_factory=list)


class UpdateProfileRequest(BaseModel):
    canonical_name: str | None = None
    type: Literal["character", "scene", "prop"] | None = None
    aliases: list[str] | None = None
    role: str | None = None
    importance: Literal["S", "A", "B", "C"] | None = None
    setting: str | None = None
    status: Literal["draft", "reviewed", "archived"] | None = None


class CreateEntityCardFromProfileRequest(BaseModel):
    variant_id: str | None = None


class SaveVisualStyleRequest(BaseModel):
    name: str = Field(min_length=1)
    prompt: str = ""
    negative_prompt: str = ""
    reference_asset_ids: list[str] = Field(default_factory=list)
    is_active: bool = False


class SaveAssetPresetRequest(BaseModel):
    provider: str = "openai"
    model: str = ""
    size: str = "1024x1024"
    aspect_ratio: str = "1:1"
    output_count: int = Field(default=1, ge=1, le=8)
    view_types: list[str] = Field(default_factory=list)
    type_prompt: str = ""
    type_negative_prompt: str = ""
    auto_adopt: bool = False


class GenerateAssetPromptRequest(BaseModel):
    variant_id: str | None = None
    view_type: str = ""


class UpdateAssetPromptRequest(BaseModel):
    view_type: str = ""
    prompt_text: str = Field(min_length=1)
    negative_prompt: str = ""


class CreateImageTaskRequest(BaseModel):
    asset_prompt_id: str = Field(min_length=1)


def register_asset_production_routes(app: FastAPI, services: AppServices) -> None:
    repository = services.asset_production_repository
    service = services.entity_asset_service

    @app.post("/api/v3/projects/{project_id}/entity-analysis-runs")
    def run_analysis(project_id: str, body: RunAnalysisRequest, request: Request) -> dict:
        try:
            return service.analyze(project_id, require_user(request).id, body.episode_ids or None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v3/projects/{project_id}/entity-analysis-runs")
    def list_analysis_runs(project_id: str) -> dict:
        try:
            return {"runs": repository.list_extraction_runs(project_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v3/projects/{project_id}/entity-profiles")
    def list_profiles(project_id: str) -> dict:
        try:
            return {"profiles": repository.list_profiles(project_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/v3/projects/{project_id}/entity-profiles/{profile_id}")
    def update_profile(project_id: str, profile_id: str, body: UpdateProfileRequest) -> dict:
        try:
            return repository.update_profile(project_id, profile_id, body.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/v3/projects/{project_id}/entity-profiles/{profile_id}")
    def delete_profile(project_id: str, profile_id: str) -> dict:
        try:
            repository.delete_profile(project_id, profile_id)
            return {"deleted": True}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v3/projects/{project_id}/entity-profiles/{profile_id}/setting")
    def generate_setting(project_id: str, profile_id: str, request: Request) -> dict:
        try:
            return service.generate_setting(project_id, profile_id, require_user(request).id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v3/projects/{project_id}/entity-profiles/{profile_id}/entity-card")
    def create_card(project_id: str, profile_id: str, body: CreateEntityCardFromProfileRequest) -> dict:
        try:
            return service.create_entity_card(project_id, profile_id, body.variant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v3/projects/{project_id}/visual-styles")
    def list_visual_styles(project_id: str) -> dict:
        try:
            return {"styles": repository.list_visual_styles(project_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v3/projects/{project_id}/visual-styles")
    def create_visual_style(project_id: str, body: SaveVisualStyleRequest) -> dict:
        try:
            return repository.save_visual_style(project_id, body.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/v3/projects/{project_id}/visual-styles/{style_id}")
    def update_visual_style(project_id: str, style_id: str, body: SaveVisualStyleRequest) -> dict:
        try:
            return repository.save_visual_style(project_id, body.model_dump(), style_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/v3/projects/{project_id}/visual-styles/{style_id}")
    def delete_visual_style(project_id: str, style_id: str) -> dict:
        try:
            repository.delete_visual_style(project_id, style_id)
            return {"deleted": True}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v3/projects/{project_id}/asset-presets")
    def list_asset_presets(project_id: str) -> dict:
        try:
            return {"presets": repository.list_presets(project_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/v3/projects/{project_id}/asset-presets/{entity_type}")
    def save_asset_preset(project_id: str, entity_type: str, body: SaveAssetPresetRequest) -> dict:
        try:
            return repository.save_preset(project_id, entity_type, body.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v3/projects/{project_id}/asset-prompts")
    def list_asset_prompts(project_id: str, profile_id: str | None = None) -> dict:
        return {"prompts": repository.list_asset_prompts(project_id, profile_id)}

    @app.post("/api/v3/projects/{project_id}/entity-profiles/{profile_id}/asset-prompts")
    def generate_asset_prompt(
        project_id: str, profile_id: str, body: GenerateAssetPromptRequest, request: Request
    ) -> dict:
        try:
            return service.generate_asset_prompt(
                project_id, profile_id, require_user(request).id,
                variant_id=body.variant_id, view_type=body.view_type,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/v3/projects/{project_id}/asset-prompts/{prompt_id}")
    def update_asset_prompt(project_id: str, prompt_id: str, body: UpdateAssetPromptRequest) -> dict:
        try:
            current = repository.get_asset_prompt(project_id, prompt_id)
            return repository.save_asset_prompt(project_id, {**current, **body.model_dump(), "id": prompt_id})
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v3/projects/{project_id}/image-tasks")
    def create_image_task(project_id: str, body: CreateImageTaskRequest, request: Request) -> dict:
        try:
            return service.generate_images(project_id, require_user(request).id, body.asset_prompt_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError, ImageGenerationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v3/projects/{project_id}/image-tasks")
    def list_image_tasks(project_id: str) -> dict:
        return {"tasks": repository.list_image_tasks(project_id)}

    @app.post("/api/v3/projects/{project_id}/image-outputs/{output_id}/adopt")
    def adopt_image_output(project_id: str, output_id: str) -> dict:
        try:
            return service.adopt_output(project_id, output_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
