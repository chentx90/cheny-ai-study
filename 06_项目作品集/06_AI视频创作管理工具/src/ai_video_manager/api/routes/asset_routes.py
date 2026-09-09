from __future__ import annotations

import base64

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ai_video_manager.api.app_helpers import resolve_asset_file
from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.schemas import RenameAssetRequest, UploadAssetRequest
from ai_video_manager.storage import SQLiteStore


def _persist_project_asset(store: SQLiteStore, project_id: str, asset_type: str, filename: str, content: bytes) -> dict:
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Asset exceeds 25 MB limit")
    try:
        path = store.save_asset(project_id, asset_type, filename, content)
        asset = store.get_project_asset(project_id, path)
        if asset:
            return asset
        return {"path": path, "asset_type": asset_type, "bytes": len(content)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def register_asset_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store

    @app.get("/api/public/media/{token}")
    def get_signed_public_media(token: str):
        import mimetypes

        from ai_video_manager.signed_media import verify_signed_media_token

        try:
            _project_id, path = verify_signed_media_token(store, token)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=mime, filename=path.name)

    @app.post("/api/projects/{project_id}/assets")
    def upload_project_asset(project_id: str, request: UploadAssetRequest) -> dict:
        try:
            content = base64.b64decode(request.content_base64, validate=True)
            return _persist_project_asset(store, project_id, request.asset_type, request.filename, content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/assets/upload")
    async def upload_project_asset_multipart(
        project_id: str,
        file: UploadFile = File(...),
        asset_type: str = Form(...),
    ) -> dict:
        try:
            content = await file.read()
            filename = file.filename or "upload.bin"
            return _persist_project_asset(store, project_id, asset_type, filename, content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/projects/{project_id}/assets/{asset_path:path}")
    def rename_project_asset(project_id: str, asset_path: str, request: RenameAssetRequest) -> dict:
        try:
            return store.rename_asset(project_id, asset_path, request.filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Asset not found: {exc}") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/assets")
    def list_project_assets(project_id: str) -> dict:
        try:
            return {"assets": store.list_assets(project_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/assets/{asset_path:path}")
    def get_project_asset(project_id: str, asset_path: str):
        try:
            path = resolve_asset_file(store, project_id, asset_path)
            if not path.exists() or not path.is_file():
                raise HTTPException(status_code=404, detail=f"Asset not found: {asset_path}")
            return FileResponse(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/generated/{asset_path:path}")
    def get_project_generated(project_id: str, asset_path: str):
        try:
            store.get_project(project_id)
            from ai_video_manager.project_bundle import resolve_project_data_root

            root = (resolve_project_data_root(store, project_id) / "generated").resolve()
            path = (root / asset_path).resolve()
            if root not in path.parents and path != root:
                raise ValueError("Generated path escapes project directory")
            if not path.exists() or not path.is_file():
                raise HTTPException(status_code=404, detail=f"Generated file not found: {asset_path}")
            return FileResponse(path, media_type="video/mp4")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}/assets/{asset_path:path}")
    def delete_project_asset(project_id: str, asset_path: str) -> dict:
        try:
            path = resolve_asset_file(store, project_id, asset_path)
            if not path.exists() or not path.is_file():
                raise HTTPException(status_code=404, detail=f"Asset not found: {asset_path}")
            path.unlink()
            removed_references = store.remove_asset_references(project_id, asset_path)
            return {"deleted": True, "path": asset_path, "removed_references": removed_references}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
