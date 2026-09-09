from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.schemas import (
    SaveEntityCardRequest,
    SaveEntityMaterialsRequest,
)
from ai_video_manager.api.utils import _dump
from ai_video_manager.models import EntityCard


def register_entity_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    @app.get("/api/projects/{project_id}/entity-cards")
    def list_entity_cards(project_id: str) -> dict:
        try:
            return {"cards": [_dump(card) for card in store.list_entity_cards(project_id)]}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/entity-cards")
    def create_entity_card(project_id: str, request: SaveEntityCardRequest) -> dict:
        try:
            card = EntityCard(
                project_id=project_id,
                entity_name=request.entity_name,
                type=request.type,
                state=request.state,
                tags=request.tags,
                assets=request.assets,
                reference_images=request.reference_images,
                audio_samples=request.audio_samples,
                video_clips=request.video_clips,
            )
            return _dump(store.save_entity_card(project_id, card))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/projects/{project_id}/entity-cards/{card_id}")
    def update_entity_card(project_id: str, card_id: str, request: SaveEntityCardRequest) -> dict:
        try:
            existing = store.get_entity_card(project_id, card_id)
            card = EntityCard(
                id=existing.id,
                project_id=project_id,
                entity_name=request.entity_name,
                type=request.type,
                state=request.state,
                tags=request.tags,
                assets=request.assets,
                reference_images=request.reference_images,
                audio_samples=request.audio_samples,
                video_clips=request.video_clips,
                created_at=existing.created_at,
            )
            return _dump(store.save_entity_card(project_id, card))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}/entity-cards/{card_id}")
    def delete_entity_card(project_id: str, card_id: str) -> dict:
        try:
            removed_bindings = store.remove_entity_card_bindings(project_id, card_id)
            store.delete_entity_card(project_id, card_id)
            return {"deleted": True, "removed_bindings": removed_bindings}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/entity-materials")
    def list_entity_materials(project_id: str) -> dict:
        try:
            return {"materials": [_dump(material) for material in store.list_entity_materials(project_id)]}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/entity-materials")
    def add_entity_materials(project_id: str, request: SaveEntityMaterialsRequest) -> dict:
        try:
            materials = store.add_entity_materials(project_id, request.entity_name, request.type, request.asset_paths)
            return {"materials": [_dump(material) for material in materials]}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Asset not found: {exc}") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}/entity-materials/{material_id}")
    def delete_entity_material(project_id: str, material_id: str) -> dict:
        try:
            store.delete_entity_material(project_id, material_id)
            return {"deleted": True}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
