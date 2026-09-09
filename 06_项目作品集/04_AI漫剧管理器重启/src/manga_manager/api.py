"""FastAPI web interface for the manga manager workspace."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from manga_manager import store
from manga_manager.models import Entity, Episode, RunState, Shot, StyleGuide


WEB_DIR = Path(__file__).resolve().parent / "web"


class WorkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class SourceUpdate(BaseModel):
    text: str = ""


class PromptUpdate(BaseModel):
    text: str = ""


class PromptConfigUpdate(BaseModel):
    narrative_style: str = ""
    visual_style: str = ""
    palette: str = ""
    render_keywords: str = ""
    camera_language: str = ""
    negative_prompt: str = ""


class AssetUpdate(BaseModel):
    entity_id: str = Field(min_length=1)
    variant_label: str = ""
    kind: Literal["image", "audio", "video"]


def _not_found(message: str = "resource not found") -> None:
    raise HTTPException(status_code=404, detail=message)


def _get_work_or_404(work_id: str):
    work = store.get_work(work_id)
    if work is None:
        _not_found(f"work not found: {work_id}")
    return work


def _read_run_state(work_id: str) -> RunState | None:
    path = store.work_dir(work_id) / "run_state.json"
    return store.read_model(path, RunState) if path.exists() else None


def _read_style(work_id: str) -> StyleGuide | None:
    path = store.work_dir(work_id) / "style_guide.json"
    return store.read_model(path, StyleGuide) if path.exists() else None


def _all_scenes(episodes: list[Episode]) -> list[dict[str, Any]]:
    return [
        scene.model_dump(mode="json") | {"episode_title": episode.title}
        for episode in episodes
        for scene in episode.scenes
    ]


def _scene_lookup(episodes: list[Episode]) -> dict[str, dict[str, Any]]:
    return {scene["id"]: scene for scene in _all_scenes(episodes)}


def _entity_counts(entities: list[Entity]) -> dict[str, int]:
    counts = {"character": 0, "location": 0, "prop": 0}
    for entity in entities:
        counts[entity.type] = counts.get(entity.type, 0) + 1
    return counts


def _file_count(root: Path, pattern: str) -> int:
    return len(list(root.glob(pattern))) if root.exists() else 0


def _prompt_path(work_id: str, scene_id: str) -> Path:
    return store.work_dir(work_id) / "video_prompts" / f"{scene_id}.txt"


def _safe_work_file(work_id: str, relative_path: str) -> Path:
    root = store.work_dir(work_id).resolve()
    target = (root / relative_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=400, detail="path escapes work directory")
    if not target.exists() or not target.is_file():
        _not_found(f"file not found: {relative_path}")
    return target


def _asset_items(work_id: str, entities: list[Entity]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    entity_names = {entity.id: entity.name for entity in entities}
    for entity in entities:
        for variant in entity.variants:
            for kind in ("image", "audio", "video"):
                for relative_path in variant.media_paths(kind):
                    path = store.work_dir(work_id) / relative_path
                    items.append(
                        {
                            "entity_id": entity.id,
                            "entity_name": entity_names.get(entity.id, entity.id),
                            "variant_label": variant.label,
                            "kind": kind,
                            "path": relative_path,
                            "filename": path.name,
                            "exists": path.exists(),
                            "url": f"/api/works/{work_id}/files/{relative_path.replace('\\', '/')}",
                        }
                    )
    return items


def _get_asset_item(work_id: str, relative_path: str) -> dict[str, Any] | None:
    for item in _asset_items(work_id, store.load_entities(work_id)):
        if item["path"] == relative_path:
            return item
    return None


def _variant_paths_by_kind(variant, kind: str) -> list[str]:
    if kind == "image":
        return variant.ref_images
    if kind == "audio":
        return variant.ref_audios
    return variant.ref_videos


def _delete_asset_reference(work_id: str, relative_path: str) -> bool:
    entities = store.load_entities(work_id)
    removed = False
    for entity in entities:
        for variant in entity.variants:
            for paths in (variant.ref_images, variant.ref_audios, variant.ref_videos):
                before = len(paths)
                paths[:] = [path for path in paths if path != relative_path]
                removed = removed or len(paths) != before
    if removed:
        store.save_entities(work_id, entities)
    return removed


def _rebind_asset_reference(work_id: str, relative_path: str, payload: AssetUpdate) -> dict[str, Any]:
    entities = store.load_entities(work_id)
    target_entity = None
    target_variant = None
    removed = False
    for entity in entities:
        if entity.id == payload.entity_id:
            target_entity = entity
        for variant in entity.variants:
            for kind in ("image", "audio", "video"):
                paths = _variant_paths_by_kind(variant, kind)
                before = len(paths)
                paths[:] = [path for path in paths if path != relative_path]
                removed = removed or len(paths) != before

    if target_entity is None:
        raise HTTPException(status_code=400, detail=f"entity not found: {payload.entity_id}")

    for variant in target_entity.variants:
        if variant.label == payload.variant_label:
            target_variant = variant
            break
    if target_variant is None:
        from manga_manager.models import EntityVariant

        target_variant = EntityVariant(label=payload.variant_label, time_desc="", appearance="")
        target_entity.variants.append(target_variant)

    target_paths = _variant_paths_by_kind(target_variant, payload.kind)
    if relative_path not in target_paths:
        target_paths.append(relative_path)

    if not removed and _get_asset_item(work_id, relative_path) is None:
        _safe_work_file(work_id, relative_path)

    store.save_entities(work_id, entities)
    item = _get_asset_item(work_id, relative_path)
    if item is None:
        _not_found(f"asset not found after update: {relative_path}")
    return item


app = FastAPI(title="AI Manga Manager", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/works")
def list_works() -> dict[str, Any]:
    active = store.get_active_work_id()
    return {
        "active_work_id": active,
        "works": [work.model_dump(mode="json") for work in store.list_works()],
    }


@app.post("/api/works", status_code=201)
def create_work(payload: WorkCreate) -> dict[str, Any]:
    work = store.create_work(payload.title.strip())
    store.set_active_work_id(work.id)
    return work.model_dump(mode="json")


@app.post("/api/works/{work_id}/activate")
def activate_work(work_id: str) -> dict[str, str]:
    _get_work_or_404(work_id)
    store.set_active_work_id(work_id)
    return {"active_work_id": work_id}


@app.get("/api/works/{work_id}/overview")
def work_overview(work_id: str) -> dict[str, Any]:
    work = _get_work_or_404(work_id)
    root = store.work_dir(work_id)
    episodes = store.load_episodes(work_id)
    shots = store.load_shots(work_id)
    entities = store.load_entities(work_id)
    summaries = store.load_summaries(work_id)
    run_state = _read_run_state(work_id)
    style = _read_style(work_id)
    scenes = _all_scenes(episodes)
    source_path = root / "source.txt"
    return {
        "work": work.model_dump(mode="json"),
        "active": store.get_active_work_id() == work_id,
        "run_state": run_state.model_dump(mode="json") if run_state else None,
        "style_guide": style.model_dump(mode="json") if style else None,
        "counts": {
            "episodes": len(episodes),
            "scenes": len(scenes),
            "shots": len(shots),
            "entities": len(entities),
            "summaries": len(summaries),
            "video_prompts": _file_count(root / "video_prompts", "*.txt"),
            "generated_videos": _file_count(root / "generated_videos", "**/*.mp4"),
            "assets": _file_count(root / "assets", "**/*.*"),
        },
        "entity_counts": _entity_counts(entities),
        "source": {
            "chars": len(source_path.read_text(encoding="utf-8")) if source_path.exists() else 0,
            "path": str(source_path),
        },
    }


@app.get("/api/works/{work_id}/episodes")
def get_episodes(work_id: str) -> dict[str, Any]:
    _get_work_or_404(work_id)
    return {"episodes": [episode.model_dump(mode="json") for episode in store.load_episodes(work_id)]}


@app.get("/api/works/{work_id}/entities")
def get_entities(
    work_id: str,
    kind: Literal["all", "character", "location", "prop"] = Query("all"),
) -> dict[str, Any]:
    _get_work_or_404(work_id)
    entities = store.load_entities(work_id)
    if kind != "all":
        entities = [entity for entity in entities if entity.type == kind]
    return {"entities": [entity.model_dump(mode="json") for entity in entities]}


@app.get("/api/works/{work_id}/shots")
def get_shots(
    work_id: str,
    episode: int | None = None,
    scene_id: str | None = None,
) -> dict[str, Any]:
    _get_work_or_404(work_id)
    episodes = store.load_episodes(work_id)
    scenes = _scene_lookup(episodes)
    shots = store.load_shots(work_id)
    if scene_id:
        shots = [shot for shot in shots if shot.scene_id == scene_id]
    if episode is not None:
        scene_ids = {scene["id"] for scene in scenes.values() if scene["episode_idx"] == episode}
        shots = [shot for shot in shots if shot.scene_id in scene_ids]
    return {
        "shots": [
            shot.model_dump(mode="json") | {"scene": scenes.get(shot.scene_id)}
            for shot in sorted(shots, key=lambda item: (item.scene_id, item.idx))
        ]
    }


@app.get("/api/works/{work_id}/shot-tree")
def get_shot_tree(work_id: str) -> dict[str, Any]:
    _get_work_or_404(work_id)
    episodes = store.load_episodes(work_id)
    shots_by_scene: dict[str, list[Shot]] = {}
    for shot in store.load_shots(work_id):
        shots_by_scene.setdefault(shot.scene_id, []).append(shot)

    tree = []
    for episode in episodes:
        scenes = []
        for scene in episode.scenes:
            scene_shots = sorted(shots_by_scene.get(scene.id, []), key=lambda item: item.idx)
            scenes.append(
                scene.model_dump(mode="json")
                | {
                    "episode_title": episode.title,
                    "shots": [shot.model_dump(mode="json") for shot in scene_shots],
                }
            )
        tree.append(
            episode.model_dump(mode="json", exclude={"scenes"})
            | {
                "scene_count": len(episode.scenes),
                "shot_count": sum(len(scene["shots"]) for scene in scenes),
                "scenes": scenes,
            }
        )
    return {"episodes": tree}


@app.get("/api/works/{work_id}/prompts")
def get_prompts(work_id: str) -> dict[str, Any]:
    _get_work_or_404(work_id)
    episodes = store.load_episodes(work_id)
    scenes = _scene_lookup(episodes)
    prompt_dir = store.work_dir(work_id) / "video_prompts"
    prompts = []
    if prompt_dir.exists():
        for path in sorted(prompt_dir.glob("*.txt")):
            text = path.read_text(encoding="utf-8")
            prompts.append(
                {
                    "scene_id": path.stem,
                    "scene": scenes.get(path.stem),
                    "filename": path.name,
                    "chars": len(text),
                    "preview": text[:240],
                }
            )
    return {"prompts": prompts}


@app.get("/api/works/{work_id}/prompt-config")
def get_prompt_config(work_id: str) -> dict[str, Any]:
    _get_work_or_404(work_id)
    style = _read_style(work_id)
    if style is None:
        _not_found("style_guide.json not found")
    return {"style_guide": style.model_dump(mode="json")}


@app.put("/api/works/{work_id}/prompt-config")
def update_prompt_config(work_id: str, payload: PromptConfigUpdate) -> dict[str, Any]:
    _get_work_or_404(work_id)
    style = StyleGuide(**payload.model_dump())
    root = store.work_dir(work_id)
    with store.write_lock(root):
        store.write_json_atomic(root / "style_guide.json", style)
        store.append_operation_unlocked(
            root,
            store.Operation(command="web.prompt_config.update", detail="style_guide.json"),
        )
    return {"style_guide": style.model_dump(mode="json")}


@app.get("/api/works/{work_id}/prompts/{scene_id}")
def get_prompt(work_id: str, scene_id: str) -> dict[str, Any]:
    _get_work_or_404(work_id)
    path = _prompt_path(work_id, scene_id)
    if not path.exists():
        _not_found(f"prompt not found: {scene_id}")
    return {"scene_id": scene_id, "text": path.read_text(encoding="utf-8")}


@app.put("/api/works/{work_id}/prompts/{scene_id}")
def update_prompt(work_id: str, scene_id: str, payload: PromptUpdate) -> dict[str, Any]:
    _get_work_or_404(work_id)
    path = _prompt_path(work_id, scene_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.text, encoding="utf-8")
    store.log_operation(work_id, "web.prompt.update", scene_id, chars=len(payload.text))
    return {"scene_id": scene_id, "chars": len(payload.text)}


@app.get("/api/works/{work_id}/assets")
def get_assets(work_id: str) -> dict[str, Any]:
    _get_work_or_404(work_id)
    entities = store.load_entities(work_id)
    return {"assets": _asset_items(work_id, entities)}


@app.get("/api/works/{work_id}/assets/detail")
def get_asset_detail(work_id: str, path: str = Query(...)) -> dict[str, Any]:
    _get_work_or_404(work_id)
    _safe_work_file(work_id, path)
    item = _get_asset_item(work_id, path)
    if item is None:
        _not_found(f"asset reference not found: {path}")
    return {"asset": item}


@app.post("/api/works/{work_id}/assets", status_code=201)
def upload_asset(
    work_id: str,
    entity_id: str = Form(...),
    variant_label: str = Form(...),
    kind: Literal["image", "audio", "video"] = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    _get_work_or_404(work_id)
    suffix = Path(file.filename or "").suffix
    if not suffix:
        raise HTTPException(status_code=400, detail="uploaded file must have an extension")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        shutil.copyfileobj(file.file, tmp)
    try:
        entity = store.bind_ref_media(work_id, entity_id, variant_label.strip(), tmp_path, kind)
    finally:
        tmp_path.unlink(missing_ok=True)
        file.file.close()
    store.log_operation(
        work_id,
        "web.asset.upload",
        f"{entity_id} / {variant_label} / {kind}",
    )
    return entity.model_dump(mode="json")


@app.delete("/api/works/{work_id}/assets")
def delete_asset(work_id: str, path: str = Query(...)) -> dict[str, Any]:
    _get_work_or_404(work_id)
    target = _safe_work_file(work_id, path)
    removed_ref = _delete_asset_reference(work_id, path)
    target.unlink(missing_ok=True)
    store.log_operation(work_id, "web.asset.delete", path)
    return {"path": path, "removed_reference": removed_ref}


@app.patch("/api/works/{work_id}/assets")
def update_asset(work_id: str, payload: AssetUpdate, path: str = Query(...)) -> dict[str, Any]:
    _get_work_or_404(work_id)
    _safe_work_file(work_id, path)
    item = _rebind_asset_reference(work_id, path, payload)
    store.log_operation(
        work_id,
        "web.asset.update",
        f"{path} -> {payload.entity_id} / {payload.variant_label} / {payload.kind}",
    )
    return {"asset": item}


@app.get("/api/works/{work_id}/operations")
def get_operations(work_id: str, limit: int = Query(40, ge=1, le=200)) -> dict[str, Any]:
    _get_work_or_404(work_id)
    return {
        "operations": [
            operation.model_dump(mode="json")
            for operation in store.load_operations(work_id, limit=limit)
        ]
    }


@app.get("/api/works/{work_id}/source")
def get_source(work_id: str) -> dict[str, Any]:
    _get_work_or_404(work_id)
    text = store.get_source_text(work_id)
    return {"text": text, "chars": len(text)}


@app.put("/api/works/{work_id}/source")
def update_source(work_id: str, payload: SourceUpdate) -> dict[str, Any]:
    _get_work_or_404(work_id)
    root = store.work_dir(work_id)
    with store.write_lock(root):
        (root / "source.txt").write_text(payload.text, encoding="utf-8")
        work = store.read_model(root / "work.json", type(_get_work_or_404(work_id)))
        work.source_meta = work.source_meta | {"chars": len(payload.text)}
        store.write_json_atomic(root / "work.json", work)
        store.append_operation_unlocked(root, store.Operation(command="web.source.update", detail=f"{len(payload.text)} chars"))
    return {"chars": len(payload.text)}


@app.post("/api/works/{work_id}/validate")
def validate_work(work_id: str, fix_index: bool = Query(False)) -> dict[str, Any]:
    _get_work_or_404(work_id)
    report = store.validate_work(work_id, fix_index=fix_index)
    return report.model_dump(mode="json")


@app.get("/api/works/{work_id}/files/{relative_path:path}")
def get_work_file(work_id: str, relative_path: str) -> FileResponse:
    _get_work_or_404(work_id)
    return FileResponse(_safe_work_file(work_id, relative_path))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def run() -> None:
    uvicorn.run("manga_manager.api:app", host="127.0.0.1", port=8000, reload=True)
