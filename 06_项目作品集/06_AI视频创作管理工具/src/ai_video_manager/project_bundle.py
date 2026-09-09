"""Structured project bundle: unified data root, JSON card sync, import/export."""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_video_manager.api.utils import _dump
from ai_video_manager.models import EntityCard, EntityType, Project, ProjectRole, PromptCard, new_id
from ai_video_manager.storage import SQLiteStore

logger = logging.getLogger(__name__)

BUNDLE_VERSION = 1
MANIFEST_FILE = "manifest.json"
ENTITY_CARDS_FILE = "cards/entity_cards.json"
PROMPT_CARDS_FILE = "cards/prompt_cards.json"

BUNDLE_DIRS = (
    "original",
    "segments",
    "scripts",
    "assets/images",
    "assets/audio",
    "assets/videos",
    "generated",
    "checkpoints",
    "cards",
)

SKIP_EXPORT_NAMES = {MANIFEST_FILE, ENTITY_CARDS_FILE, PROMPT_CARDS_FILE}


class PathOutsideWorkspaceError(ValueError):
    pass


def _workspace_root(store: SQLiteStore) -> Path:
    return store.workspace_root.expanduser().resolve()


def ensure_within_workspace(store: SQLiteStore, path: Path) -> Path:
    resolved = path.expanduser().resolve()
    workspace = _workspace_root(store)
    if resolved == workspace or resolved.is_relative_to(workspace):
        return resolved
    raise PathOutsideWorkspaceError(f"路径必须在 workspace 内：{resolved}")


def resolve_bounded_workspace_path(
    store: SQLiteStore,
    raw: str,
    *,
    must_exist: bool = False,
) -> Path:
    clean = str(raw or "").strip()
    if not clean:
        raise ValueError("路径不能为空")
    candidate = Path(clean).expanduser()
    if not candidate.is_absolute():
        candidate = (_workspace_root(store) / clean)
    resolved = ensure_within_workspace(store, candidate.resolve())
    if must_exist and not resolved.exists():
        raise ValueError(f"路径不存在：{resolved}")
    return resolved


def validate_data_root_path(store: SQLiteStore, raw: str) -> str:
    clean = str(raw or "").strip()
    if not clean:
        return ""
    resolve_bounded_workspace_path(store, clean)
    return clean


def resolve_stored_path(store: SQLiteStore, raw: str) -> Path | None:
    clean = str(raw or "").strip()
    if not clean:
        return None
    root = Path(clean).expanduser()
    if not root.is_absolute():
        root = (store.workspace_root / clean).resolve()
    return root


def default_project_data_root(store: SQLiteStore, project_id: str) -> Path:
    return (store.workspace_root / "projects" / project_id).resolve()


def resolve_project_data_root(store: SQLiteStore, project_id: str) -> Path:
    try:
        store.get_project(project_id)
    except KeyError:
        return default_project_data_root(store, project_id)
    preprocess = store.get_preprocess(project_id) or {}
    raw_data_root = str(preprocess.get("data_root") or "").strip()
    if raw_data_root:
        try:
            return resolve_bounded_workspace_path(store, raw_data_root)
        except (PathOutsideWorkspaceError, ValueError) as exc:
            logger.warning("Invalid data_root for %s, using default: %s", project_id, exc)
    return default_project_data_root(store, project_id)


def stored_path_value(store: SQLiteStore, path: Path) -> str:
    resolved = path.resolve()
    workspace = store.workspace_root.resolve()
    try:
        relative = resolved.relative_to(workspace)
        # 不要强行把 \ 换成 /：Linux 下自定义 data_root 可能字面量含反斜杠（如 Z:\...）
        return str(relative)
    except ValueError:
        return str(resolved)


def ensure_bundle_layout(project_root: Path) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    for child in BUNDLE_DIRS:
        (project_root / child).mkdir(parents=True, exist_ok=True)
    return project_root


def build_manifest(store: SQLiteStore, project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    preprocess = store.get_preprocess(project_id) or {}
    segments = store.list_project_segments(project_id)
    scripts: dict[str, Any] = {}
    for item in store.list_project_scripts(project_id):
        scripts[item["segment_id"]] = {
            "content": item.get("content") or "",
            "validation": item.get("validation") if isinstance(item.get("validation"), dict) else {},
        }
    data_root = resolve_project_data_root(store, project_id)
    return {
        "bundle_version": BUNDLE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "name": project.name,
            "category": project.category,
            "description": getattr(project, "description", "") or "",
            "current_state": project.current_state.value,
            "flags": store._project_flags(project),
        },
        "preprocess": {
            "document_text": preprocess.get("document_text", ""),
            "split_strategy": preprocess.get("split_strategy", "chapter"),
            "custom_split_pattern": preprocess.get("custom_split_pattern", ""),
            "duration_minutes": preprocess.get("duration_minutes", 2),
            "document_file": preprocess.get("document_file") if isinstance(preprocess.get("document_file"), dict) else {},
            "active_segment_id": preprocess.get("active_segment_id", ""),
            "expected_total_duration_seconds": preprocess.get("expected_total_duration_seconds"),
            "default_aspect_ratio": preprocess.get("default_aspect_ratio", "9:16"),
            "default_video_duration": preprocess.get("default_video_duration", 5),
            "default_video_model": preprocess.get("default_video_model", ""),
            "default_resolution": preprocess.get("default_resolution", "720p"),
            "output_root": preprocess.get("output_root", ""),
            "source_assets_root": preprocess.get("source_assets_root", ""),
            "data_root": preprocess.get("data_root", ""),
            "assets_confirmed": bool(preprocess.get("assets_confirmed")),
            "revision": int(preprocess.get("revision") or 0),
        },
        "segments": segments,
        "scripts": scripts,
        "data_root_relative": stored_path_value(store, data_root),
    }


def sync_cards_to_files(store: SQLiteStore, project_id: str) -> Path:
    root = ensure_bundle_layout(resolve_project_data_root(store, project_id))
    entity_cards = [_dump(card) for card in store.list_entity_cards(project_id)]
    prompt_cards = [_dump(card) for card in store.list_prompt_cards(project_id)]
    _write_json(root / ENTITY_CARDS_FILE, {"cards": entity_cards})
    _write_json(root / PROMPT_CARDS_FILE, {"cards": prompt_cards})
    _write_json(root / MANIFEST_FILE, build_manifest(store, project_id))
    return root


def sync_project_bundle(store: SQLiteStore, project_id: str) -> Path:
    return sync_cards_to_files(store, project_id)


def export_project_zip(store: SQLiteStore, project_id: str) -> tuple[bytes, str]:
    project = store.get_project(project_id)
    root = sync_cards_to_files(store, project_id)
    buffer = io.BytesIO()
    safe_name = _safe_bundle_name(project.name, project_id)
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            archive.write(path, arcname=f"{safe_name}/{rel}")
    return buffer.getvalue(), f"{safe_name}.zip"


def import_project_bundle(
    store: SQLiteStore,
    bundle_dir: Path,
    *,
    owner_id: str,
    name_override: str | None = None,
) -> Project:
    manifest_path = _find_manifest(bundle_dir)
    if manifest_path is None:
        raise ValueError("未找到 manifest.json，请确认导入的是有效的项目文件夹或压缩包")
    manifest = _read_json(manifest_path)
    if int(manifest.get("bundle_version") or 0) != BUNDLE_VERSION:
        raise ValueError(f"不支持的 bundle 版本：{manifest.get('bundle_version')}")

    bundle_root = manifest_path.parent
    project_info = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    name = (name_override or str(project_info.get("name") or "导入的项目")).strip() or "导入的项目"
    category = str(project_info.get("category") or "active").strip() or "active"
    description = str(project_info.get("description") or "").strip()

    project = Project(name=name, category=category, owner_id=owner_id, description=description)
    project = store.save_project(project)
    store.upsert_project_member(project.id, owner_id, ProjectRole.OWNER)

    target_root = ensure_bundle_layout(default_project_data_root(store, project.id))
    _copy_bundle_tree(bundle_root, target_root)

    segment_map = _build_segment_id_map(manifest)
    workspace_payload = _workspace_payload_from_manifest(manifest, segment_map)
    from ai_video_manager.project_domain import ProjectDomainService

    domain = ProjectDomainService(store)
    domain.import_workspace_dict(project.id, workspace_payload)

    _import_cards_from_bundle(store, project.id, bundle_root, segment_map)
    store._sync_project_assets(project.id)

    flags = project_info.get("flags") if isinstance(project_info.get("flags"), dict) else {}
    if flags:
        project = store.get_project(project.id)
        for key, value in flags.items():
            if hasattr(project, key):
                setattr(project, key, bool(value))
        store.save_project(project)

    sync_cards_to_files(store, project.id)
    return store.get_project(project.id)


def import_project_zip(store: SQLiteStore, payload: bytes, *, owner_id: str, name_override: str | None = None) -> Project:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        temp_root = store.workspace_root / ".import_tmp" / new_id("import")
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            for member in archive.infolist():
                target = (temp_root / member.filename).resolve()
                if not str(target).startswith(str(temp_root.resolve())):
                    raise ValueError(f"压缩包包含非法路径：{member.filename}")
            archive.extractall(temp_root)
            bundle_dir = _resolve_bundle_root(temp_root)
            return import_project_bundle(store, bundle_dir, owner_id=owner_id, name_override=name_override)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


def import_project_from_path(
    store: SQLiteStore,
    raw_path: str,
    *,
    owner_id: str,
    name_override: str | None = None,
) -> Project:
    root = resolve_bounded_workspace_path(store, raw_path, must_exist=True)
    if not root.is_dir():
        raise ValueError(f"导入路径必须是目录：{root}")
    bundle_dir = _resolve_bundle_root(root)
    return import_project_bundle(store, bundle_dir, owner_id=owner_id, name_override=name_override)


def _build_segment_id_map(manifest: dict[str, Any]) -> dict[str, str]:
    segment_map: dict[str, str] = {}
    segments = manifest.get("segments") if isinstance(manifest.get("segments"), list) else []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        old_id = str(segment.get("id") or "").strip()
        if old_id and old_id not in segment_map:
            segment_map[old_id] = new_id("seg")

    preprocess = manifest.get("preprocess") if isinstance(manifest.get("preprocess"), dict) else {}
    active_id = str(preprocess.get("active_segment_id") or "").strip()
    if active_id and active_id not in segment_map:
        segment_map[active_id] = new_id("seg")

    scripts = manifest.get("scripts") if isinstance(manifest.get("scripts"), dict) else {}
    for segment_id in scripts:
        old_id = str(segment_id).strip()
        if old_id and old_id not in segment_map:
            segment_map[old_id] = new_id("seg")
    return segment_map


def _remap_segment_id(segment_map: dict[str, str], raw_id: str) -> str:
    old_id = str(raw_id or "").strip()
    if not old_id:
        return ""
    return segment_map.get(old_id) or new_id("seg")


def _workspace_payload_from_manifest(
    manifest: dict[str, Any],
    segment_map: dict[str, str],
) -> dict[str, Any]:
    preprocess = manifest.get("preprocess") if isinstance(manifest.get("preprocess"), dict) else {}
    scripts = manifest.get("scripts") if isinstance(manifest.get("scripts"), dict) else {}
    scripts_map: dict[str, str] = {}
    validation_map: dict[str, dict[str, Any]] = {}
    for segment_id, payload in scripts.items():
        new_segment_id = _remap_segment_id(segment_map, str(segment_id))
        if isinstance(payload, dict):
            scripts_map[new_segment_id] = str(payload.get("content") or "")
            validation = payload.get("validation")
            if isinstance(validation, dict):
                validation_map[new_segment_id] = validation
        else:
            scripts_map[new_segment_id] = str(payload or "")

    raw_segments = manifest.get("segments") if isinstance(manifest.get("segments"), list) else []
    remapped_segments: list[dict[str, Any]] = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        old_id = str(segment.get("id") or "").strip()
        new_id_value = _remap_segment_id(segment_map, old_id)
        remapped_segments.append({**segment, "id": new_id_value})

    active_segment_id = _remap_segment_id(
        segment_map,
        str(preprocess.get("active_segment_id") or ""),
    )
    return {
        "documentText": preprocess.get("document_text", ""),
        "splitStrategy": preprocess.get("split_strategy", "chapter"),
        "customSplitPattern": preprocess.get("custom_split_pattern", ""),
        "durationMinutes": preprocess.get("duration_minutes", 2),
        "documentFile": preprocess.get("document_file") if isinstance(preprocess.get("document_file"), dict) else {},
        "activeSegmentId": active_segment_id,
        "expectedTotalDurationSeconds": preprocess.get("expected_total_duration_seconds"),
        "defaultAspectRatio": preprocess.get("default_aspect_ratio", "9:16"),
        "defaultVideoDuration": preprocess.get("default_video_duration", 5),
        "defaultVideoModel": preprocess.get("default_video_model", ""),
        "defaultResolution": preprocess.get("default_resolution", "720p"),
        "outputRoot": preprocess.get("output_root", ""),
        "sourceAssetsRoot": preprocess.get("source_assets_root", ""),
        "dataRoot": "",
        "assetsConfirmed": bool(preprocess.get("assets_confirmed")),
        "segments": remapped_segments,
        "scripts": scripts_map,
        "scriptValidation": validation_map,
        "revision": preprocess.get("revision"),
    }


def _import_cards_from_bundle(
    store: SQLiteStore,
    project_id: str,
    bundle_root: Path,
    segment_map: dict[str, str],
) -> None:
    entity_path = bundle_root / ENTITY_CARDS_FILE
    prompt_path = bundle_root / PROMPT_CARDS_FILE
    if entity_path.is_file():
        payload = _read_json(entity_path)
        cards = payload.get("cards") if isinstance(payload.get("cards"), list) else []
        for item in cards:
            if isinstance(item, dict):
                store.save_entity_card(project_id, _parse_entity_card(item, project_id))
    if prompt_path.is_file():
        payload = _read_json(prompt_path)
        cards = payload.get("cards") if isinstance(payload.get("cards"), list) else []
        for item in cards:
            if isinstance(item, dict):
                store.save_prompt_card(_parse_prompt_card(item, project_id, segment_map))


def _parse_entity_card(data: dict[str, Any], project_id: str) -> EntityCard:
    raw_type = data.get("type")
    entity_type = EntityType(raw_type) if raw_type else EntityType.CHARACTER
    created_at = _parse_datetime(data.get("created_at"))
    updated_at = _parse_datetime(data.get("updated_at"))
    return EntityCard(
        id=new_id("card"),
        project_id=project_id,
        entity_name=str(data.get("entity_name") or ""),
        type=entity_type,
        state=data.get("state"),
        assets=[str(item) for item in data.get("assets") or [] if str(item).strip()],
        reference_images=[str(item) for item in data.get("reference_images") or [] if str(item).strip()],
        audio_samples=[str(item) for item in data.get("audio_samples") or [] if str(item).strip()],
        video_clips=[str(item) for item in data.get("video_clips") or [] if str(item).strip()],
        tags=[str(item) for item in data.get("tags") or [] if str(item).strip()],
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse_prompt_card(
    data: dict[str, Any],
    project_id: str,
    segment_map: dict[str, str],
) -> PromptCard:
    created_at = _parse_datetime(data.get("created_at"))
    updated_at = _parse_datetime(data.get("updated_at"))
    return PromptCard(
        id=new_id("pcard"),
        project_id=project_id,
        segment_id=_remap_segment_id(segment_map, str(data.get("segment_id") or "")),
        order=int(data.get("order") or 1),
        title=str(data.get("title") or ""),
        prompt_text=str(data.get("prompt_text") or ""),
        anchor_text=str(data.get("anchor_text") or ""),
        duration=float(data.get("duration") or 0),
        source_text=str(data.get("source_text") or ""),
        source_start=int(data.get("source_start") or 0),
        source_end=int(data.get("source_end") or 0),
        source_hash=str(data.get("source_hash") or ""),
        status=str(data.get("status") or "draft"),
        locked=bool(data.get("locked")),
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _find_manifest(root: Path) -> Path | None:
    direct = root / MANIFEST_FILE
    if direct.is_file():
        return direct
    for child in sorted(root.iterdir()):
        if child.is_dir():
            nested = child / MANIFEST_FILE
            if nested.is_file():
                return nested
    return None


def _resolve_bundle_root(extracted_root: Path) -> Path:
    manifest = _find_manifest(extracted_root)
    if manifest is None:
        raise ValueError("压缩包内未找到 manifest.json")
    return manifest.parent


def _copy_bundle_tree(source: Path, target: Path) -> None:
    ensure_bundle_layout(target)
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        if rel in SKIP_EXPORT_NAMES or rel.startswith("cards/"):
            continue
        if rel == MANIFEST_FILE:
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _safe_bundle_name(name: str, project_id: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "project").strip()) or "project"
    suffix = project_id[:8] if project_id else new_id("proj")[:8]
    return f"{clean}-{suffix}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}
