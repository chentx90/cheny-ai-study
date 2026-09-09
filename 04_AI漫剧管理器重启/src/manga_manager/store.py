"""结构化 JSON 存储层。

M0 重点：分文件、原子写、跨进程写锁、index.json 可重建/可校验。
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from manga_manager.config import get_default_style, get_works_dir
from manga_manager.models import (
    ArtifactStatus,
    BindingFile,
    Entity,
    EntityVariant,
    Episode,
    Operation,
    Relation,
    RunState,
    Shot,
    StyleGuide,
    Summary,
    ValidationIssue,
    ValidationReport,
    WorkIndex,
    WorkMeta,
)


T = TypeVar("T", bound=BaseModel)
LOCK_STALE_SECONDS = 600
MediaKind = Literal["image", "audio", "video"]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}
AUDIO_EXTENSIONS = {".mp3", ".wav"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mkv", ".m4v"}
MEDIA_EXTENSIONS: dict[str, set[str]] = {
    "image": IMAGE_EXTENSIONS,
    "audio": AUDIO_EXTENSIONS,
    "video": VIDEO_EXTENSIONS,
}
MEDIA_LIMITS = {
    "image": 9,
    "audio": 3,
    "video": 3,
}
MEDIA_LABEL = {"image": "图片", "audio": "音频", "video": "视频"}


@dataclass
class SceneMediaBundle:
    scene_id: str
    images: list[Path] = field(default_factory=list)
    audios: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def paths_by_kind(self, kind: MediaKind) -> list[Path]:
        if kind == "image":
            return self.images
        if kind == "audio":
            return self.audios
        return self.videos

    def counts(self) -> dict[str, int]:
        return {
            "image": len(self.images),
            "audio": len(self.audios),
            "video": len(self.videos),
        }


class StoreError(RuntimeError):
    pass


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def work_dir(work_id: str) -> Path:
    return get_works_dir() / work_id


def _active_file() -> Path:
    return get_works_dir().parent / ".active_work"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


@contextmanager
def write_lock(target_dir: Path) -> Iterator[None]:
    """用 O_EXCL lockfile 做单写者保护，避免并发写脏 index.json。"""

    target_dir.mkdir(parents=True, exist_ok=True)
    lock_path = target_dir / ".write.lock"
    payload = {"pid": os.getpid(), "created_at": datetime.now().isoformat(timespec="seconds")}
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            break
        except FileExistsError:
            age = time.time() - lock_path.stat().st_mtime
            if age > LOCK_STALE_SECONDS:
                lock_path.unlink(missing_ok=True)
                continue
            time.sleep(0.05)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def read_model(path: Path, model: type[T]) -> T:
    return model.model_validate(read_json(path, {}))


def read_model_list(path: Path, model: type[T]) -> list[T]:
    return [model.model_validate(item) for item in read_json(path, [])]


def set_active_work_id(work_id: str) -> None:
    _active_file().write_text(work_id, encoding="utf-8")


def get_active_work_id() -> str | None:
    path = _active_file()
    if not path.exists():
        return None
    work_id = path.read_text(encoding="utf-8").strip()
    return work_id if work_id and work_dir(work_id).exists() else None


def list_works() -> list[WorkMeta]:
    works: list[WorkMeta] = []
    for item in get_works_dir().iterdir():
        if item.is_dir() and (item / "work.json").exists():
            works.append(read_model(item / "work.json", WorkMeta))
    return sorted(works, key=lambda w: w.created_at, reverse=True)


def get_work(work_id: str) -> WorkMeta | None:
    path = work_dir(work_id) / "work.json"
    return read_model(path, WorkMeta) if path.exists() else None


def create_work(title: str) -> WorkMeta:
    work_id = new_id("w")
    root = work_dir(work_id)
    defaults = get_default_style()
    meta = WorkMeta(id=work_id, title=title)
    style = StyleGuide(**defaults)
    with write_lock(root):
        for sub in ["episodes", "shots", "entities", "bindings", "summaries", "export"]:
            (root / sub).mkdir(parents=True, exist_ok=True)
        write_json_atomic(root / "work.json", meta)
        (root / "source.txt").write_text("", encoding="utf-8")
        write_json_atomic(root / "style_guide.json", style)
        write_json_atomic(root / "index.json", WorkIndex())
        write_json_atomic(root / "entities" / "characters.json", [])
        write_json_atomic(root / "entities" / "locations.json", [])
        write_json_atomic(root / "entities" / "props.json", [])
        write_json_atomic(root / "entities" / "relations.json", [])
        write_json_atomic(root / "run_state.json", RunState(stage="M0", status=ArtifactStatus.validated))
        (root / "operations.jsonl").write_text("", encoding="utf-8")
        append_operation_unlocked(root, Operation(command="init", detail=title))
    set_active_work_id(work_id)
    return meta


def append_operation_unlocked(root: Path, operation: Operation) -> None:
    with (root / "operations.jsonl").open("a", encoding="utf-8") as f:
        f.write(operation.model_dump_json() + "\n")


def log_operation(work_id: str, command: str, detail: str = "", **payload: Any) -> None:
    root = work_dir(work_id)
    with write_lock(root):
        append_operation_unlocked(root, Operation(command=command, detail=detail, payload=payload))


def load_operations(work_id: str, limit: int = 30) -> list[Operation]:
    path = work_dir(work_id) / "operations.jsonl"
    if not path.exists():
        return []
    records: list[Operation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(Operation.model_validate_json(line))
    return list(reversed(records))[:limit]


def import_source(work_id: str, source_path: Path) -> WorkMeta:
    if not source_path.exists():
        raise StoreError(f"source file does not exist: {source_path}")
    text = source_path.read_text(encoding="utf-8")
    root = work_dir(work_id)
    with write_lock(root):
        (root / "source.txt").write_text(text, encoding="utf-8")
        meta = read_model(root / "work.json", WorkMeta)
        meta.source_meta = {"path": str(source_path), "chars": len(text)}
        meta.status = ArtifactStatus.validated
        meta.updated_at = datetime.now().isoformat(timespec="seconds")
        write_json_atomic(root / "work.json", meta)
        append_operation_unlocked(root, Operation(command="source.import", detail=f"{source_path.name} ({len(text)} chars)"))
    return meta


def load_entities(work_id: str) -> list[Entity]:
    root = work_dir(work_id) / "entities"
    entities: list[Entity] = []
    for name in ["characters.json", "locations.json", "props.json"]:
        entities.extend(read_model_list(root / name, Entity))
    return entities


_TYPE_FILE_MAP = {
    "character": "characters.json",
    "location": "locations.json",
    "prop": "props.json",
}


def save_entities(work_id: str, entities: list[Entity]) -> None:
    root = work_dir(work_id)
    with write_lock(root):
        ent_dir = root / "entities"
        by_type: dict[str, list[Entity]] = {"character": [], "location": [], "prop": []}
        for ent in entities:
            by_type.get(ent.type, []).append(ent)
        for etype, filename in _TYPE_FILE_MAP.items():
            write_json_atomic(ent_dir / filename, by_type[etype])
        index = build_index(work_id)
        write_json_atomic(root / "index.json", index)


def load_relations(work_id: str) -> list[Relation]:
    return read_model_list(work_dir(work_id) / "entities" / "relations.json", Relation)


def save_relations(work_id: str, relations: list[Relation]) -> None:
    root = work_dir(work_id)
    with write_lock(root):
        write_json_atomic(root / "entities" / "relations.json", relations)


def load_episodes(work_id: str) -> list[Episode]:
    root = work_dir(work_id) / "episodes"
    episodes: list[Episode] = []
    for path in sorted(root.glob("*.json")):
        episodes.append(read_model(path, Episode))
    return episodes


def load_shots(work_id: str) -> list[Shot]:
    shots: list[Shot] = []
    for path in sorted((work_dir(work_id) / "shots").glob("*.json")):
        shots.extend(read_model_list(path, Shot))
    return shots


def load_bindings(work_id: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted((work_dir(work_id) / "bindings").glob("*.json")):
        binding_file = read_model(path, BindingFile)
        for shot_id, items in binding_file.bindings.items():
            result[shot_id] = [item.entity_id for item in items]
    return result


def load_summaries(work_id: str) -> list[Summary]:
    return [read_model(path, Summary) for path in sorted((work_dir(work_id) / "summaries").glob("*.json"))]


def save_summary(work_id: str, summary: Summary) -> None:
    """保存单集摘要到 summaries/{episode_idx:04d}.json（原子写）。"""
    root = work_dir(work_id)
    summary_dir = root / "summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{summary.episode_idx:04d}.json"
    write_json_atomic(summary_dir / filename, summary)


def load_rolling_summary(work_id: str, through_episode_idx: int) -> tuple[str, int]:
    """取到 through_episode_idx 为止的 rolling_summary 及 token_estimate。

    Args:
        work_id: 作品 ID
        through_episode_idx: 截止集号（含）

    Returns:
        (rolling_summary_text, token_estimate)
        若无任何历史摘要，返回 ("", 0)
    """
    summaries = load_summaries(work_id)
    latest = None
    for s in summaries:
        if s.episode_idx <= through_episode_idx:
            latest = s
    if latest and latest.rolling_summary:
        return latest.rolling_summary, latest.token_estimate
    return "", 0


def build_index(work_id: str) -> WorkIndex:
    index = WorkIndex()
    for entity in load_entities(work_id):
        index.entity_name_to_id[entity.name] = entity.id
        for alias in entity.aliases:
            index.alias_to_id[alias] = entity.id
    index.shot_to_scene = {shot.id: shot.scene_id for shot in load_shots(work_id)}
    shot_bindings = load_bindings(work_id)
    for shot_id, entity_ids in shot_bindings.items():
        scene_id = index.shot_to_scene.get(shot_id)
        if not scene_id:
            continue
        merged = set(index.scene_to_entities.get(scene_id, []))
        merged.update(entity_ids)
        index.scene_to_entities[scene_id] = sorted(merged)
    return index


def rebuild_index(work_id: str) -> WorkIndex:
    root = work_dir(work_id)
    with write_lock(root):
        index = build_index(work_id)
        write_json_atomic(root / "index.json", index)
        append_operation_unlocked(root, Operation(command="validate.fix_index", detail="rebuilt index.json"))
    return index


def get_source_text(work_id: str) -> str:
    path = work_dir(work_id) / "source.txt"
    if not path.exists():
        raise StoreError(f"source.txt not found for {work_id}")
    return path.read_text(encoding="utf-8")


def assets_dir(work_id: str) -> Path:
    return work_dir(work_id) / "assets"


def _validate_media_kind(kind: str) -> MediaKind:
    if kind not in MEDIA_EXTENSIONS:
        valid = ", ".join(MEDIA_EXTENSIONS)
        raise ValueError(f"未知媒体类型: {kind}，可选: {valid}")
    return kind


def _variant_ref_field(kind: MediaKind) -> str:
    if kind == "image":
        return "ref_images"
    if kind == "audio":
        return "ref_audios"
    return "ref_videos"


def _find_entity(entities: list[Entity], entity_id: str) -> Entity | None:
    for ent in entities:
        if ent.id == entity_id:
            return ent
    return None


def _find_variant(entity: Entity, variant_label: str) -> EntityVariant | None:
    if not variant_label:
        return None
    for variant in entity.variants:
        if variant.label == variant_label:
            return variant
    return None


def _variant_asset_label_map(work_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entity in load_entities(work_id):
        for variant in entity.variants:
            for kind in MEDIA_EXTENSIONS:
                for relative_path in variant.media_paths(kind):
                    result[Path(relative_path).name] = variant.label
    return result


def _copy_media_asset(
    work_id: str,
    entity_id: str,
    variant_label: str,
    source_path: Path,
    kind: MediaKind,
    *,
    legacy_name: bool = False,
) -> str:
    ext = source_path.suffix.lower()
    allowed = MEDIA_EXTENSIONS[kind]
    if ext not in allowed:
        suffixes = ", ".join(sorted(allowed))
        raise ValueError(f"不支持的{MEDIA_LABEL[kind]}后缀 {ext!r}，支持: {suffixes}")

    entity_asset_dir = assets_dir(work_id) / entity_id
    entity_asset_dir.mkdir(parents=True, exist_ok=True)

    if legacy_name:
        asset_filename = f"{variant_label}{ext}"
    else:
        asset_filename = f"{variant_label}_{uuid.uuid4().hex[:8]}{ext}"
    asset_path = entity_asset_dir / asset_filename

    with open(source_path, "rb") as src, open(asset_path, "wb") as dst:
        shutil.copyfileobj(src, dst)

    return f"assets/{entity_id}/{asset_path.name}"


def bind_ref_media(
    work_id: str,
    entity_id: str,
    variant_label: str,
    media_path: Path,
    kind: MediaKind,
) -> Entity:
    """绑定图片/音频/视频到实体的某个变体。"""
    kind = _validate_media_kind(kind)
    media_path = media_path.expanduser()
    if not media_path.exists():
        raise ValueError(f"{MEDIA_LABEL[kind]}文件不存在: {media_path}")

    entities = load_entities(work_id)
    target = _find_entity(entities, entity_id)
    if not target:
        raise ValueError(f"实体不存在: {entity_id}")

    variant = _find_variant(target, variant_label)
    if not variant:
        variant = EntityVariant(
            label=variant_label,
            time_desc="",
            appearance="",
            ref_images=[],
            ref_audios=[],
            ref_videos=[],
        )
        target.variants.append(variant)

    field_name = _variant_ref_field(kind)
    ref_paths = getattr(variant, field_name)
    if kind == "image" and f"{variant_label}{media_path.suffix.lower()}" in {Path(p).name for p in ref_paths}:
        save_entities(work_id, entities)
        return target

    relative_path = _copy_media_asset(
        work_id,
        entity_id,
        variant_label,
        media_path,
        kind,
        legacy_name=(kind == "image"),
    )
    if relative_path not in ref_paths:
        ref_paths.append(relative_path)

    save_entities(work_id, entities)
    return target


def bind_ref_image(
    work_id: str,
    entity_id: str,
    variant_label: str,
    image_path: Path,
) -> Entity:
    """绑定参考图片到实体的某个变体。

    Args:
        work_id: 作品 ID
        entity_id: 实体 ID
        variant_label: 变体标签
        image_path: 图片文件路径（会被复制到资产目录）

    Returns:
        更新后的 Entity 对象
    """
    return bind_ref_media(work_id, entity_id, variant_label, image_path, "image")


def load_entity_assets(work_id: str, entity_id: str) -> dict[str, list[Path]]:
    """加载实体的所有媒体资产文件路径。

    Returns:
        {variant_label: [asset_paths]}
    """
    entity_asset_dir = assets_dir(work_id) / entity_id
    result: dict[str, list[Path]] = {}

    if not entity_asset_dir.exists():
        return result

    all_extensions = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
    label_by_name = _variant_asset_label_map(work_id)
    for file_path in entity_asset_dir.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in all_extensions:
            variant_label = label_by_name.get(file_path.name, file_path.stem)
            if variant_label.endswith("_"):
                variant_label = variant_label.rsplit("_", 1)[0]
            if variant_label not in result:
                result[variant_label] = []
            result[variant_label].append(file_path)

    return result


def load_entity_media(work_id: str, entity_id: str) -> dict[str, dict[str, list[Path]]]:
    """按媒体类型加载实体资产。

    Returns:
        {"image": {variant_label: [...]}, "audio": {...}, "video": {...}}
    """
    entity_asset_dir = assets_dir(work_id) / entity_id
    result: dict[str, dict[str, list[Path]]] = {
        "image": {},
        "audio": {},
        "video": {},
    }

    if not entity_asset_dir.exists():
        return result

    label_by_name = _variant_asset_label_map(work_id)
    for file_path in entity_asset_dir.iterdir():
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        for kind, extensions in MEDIA_EXTENSIONS.items():
            if suffix not in extensions:
                continue
            variant_label = label_by_name.get(file_path.name, file_path.stem)
            if variant_label.endswith("_"):
                variant_label = variant_label.rsplit("_", 1)[0]
            result[kind].setdefault(variant_label, []).append(file_path)

    return result


def collect_scene_media(
    work_id: str,
    scene_id: str,
    *,
    max_images: int = 9,
    max_videos: int = 3,
    max_audios: int = 3,
) -> SceneMediaBundle:
    """从场景实体绑定中收集可用于 Pippit 的本地媒体路径。"""
    bundle = SceneMediaBundle(scene_id=scene_id)
    binding_path = work_dir(work_id) / "bindings" / f"{scene_id}.json"
    if not binding_path.exists():
        return bundle

    binding_file = read_model(binding_path, BindingFile)
    entities_by_id = {entity.id: entity for entity in load_entities(work_id)}
    seen: dict[str, set[Path]] = {"image": set(), "audio": set(), "video": set()}
    limits = {"image": max_images, "audio": max_audios, "video": max_videos}

    for items in binding_file.bindings.values():
        for item in items:
            entity = entities_by_id.get(item.entity_id)
            if not entity:
                continue
            variant = _find_variant(entity, item.variant_label)
            if not variant:
                continue

            for kind in MEDIA_EXTENSIONS:
                field_name = _variant_ref_field(kind)
                limit = limits[kind]
                for relative_path in getattr(variant, field_name):
                    media_path = work_dir(work_id) / relative_path
                    resolved = media_path.resolve()
                    if resolved in seen[kind]:
                        continue
                    if not media_path.exists():
                        bundle.skipped.append(f"{MEDIA_LABEL[kind]}不存在: {relative_path}")
                        continue
                    if len(bundle.paths_by_kind(kind)) >= limit:
                        bundle.skipped.append(f"{MEDIA_LABEL[kind]}超过限制 {limit}: {relative_path}")
                        continue
                    bundle.paths_by_kind(kind).append(media_path)
                    seen[kind].add(resolved)

    return bundle


def save_episodes(work_id: str, episodes: list[Episode]) -> None:
    """写入 episode 列表，重建 index.json，记录操作。

    安全写顺序（"先写后删"）：
      1. 校验 ep.idx 唯一性，重复立即 raise StoreError。
      2. 先写所有新文件（文件名按 idx 幂等），写失败时旧文件仍在磁盘。
      3. 所有新文件写入成功后，才删除不属于新集合的旧文件。
    这样中途 I/O 异常不会导致全量数据丢失。
    """
    root = work_dir(work_id)
    # idx 唯一性校验（锁外，避免持锁时抛出）
    seen_idx: set[int] = set()
    for ep in episodes:
        if ep.idx in seen_idx:
            raise StoreError(f"duplicate episode idx {ep.idx} in input list")
        seen_idx.add(ep.idx)

    with write_lock(root):
        ep_dir = root / "episodes"
        new_filenames: set[str] = set()
        # Step 1: 写新文件（幂等，不影响旧文件）
        for ep in episodes:
            filename = f"{ep.idx:04d}.json"
            write_json_atomic(ep_dir / filename, ep)
            new_filenames.add(filename)
        # Step 2: 删除不在新集合中的旧文件（此时新文件已全部落盘）
        for old in list(ep_dir.glob("*.json")):
            if old.name not in new_filenames:
                old.unlink(missing_ok=True)
        # 同步刷新 index
        index = build_index(work_id)
        write_json_atomic(root / "index.json", index)
        # 更新 run_state
        rs = read_model(root / "run_state.json", RunState)
        rs.stage = "M1"
        rs.status = ArtifactStatus.validated
        rs.updated_at = datetime.now().isoformat(timespec="seconds")
        write_json_atomic(root / "run_state.json", rs)
        append_operation_unlocked(
            root,
            Operation(
                command="s1.save_episodes",
                detail=f"{len(episodes)} episodes, {sum(len(ep.scenes) for ep in episodes)} scenes",
            ),
        )


def validate_work(work_id: str, fix_index: bool = False) -> ValidationReport:
    root = work_dir(work_id)
    issues: list[ValidationIssue] = []
    if not root.exists():
        return ValidationReport(
            work_id=work_id,
            ok=False,
            issues=[ValidationIssue(path=str(root), message="work directory does not exist")],
        )

    checks: list[tuple[Path, type[BaseModel], bool]] = [
        (root / "work.json", WorkMeta, False),
        (root / "style_guide.json", StyleGuide, False),
        (root / "index.json", WorkIndex, False),
        (root / "run_state.json", RunState, False),
        (root / "entities" / "characters.json", Entity, True),
        (root / "entities" / "locations.json", Entity, True),
        (root / "entities" / "props.json", Entity, True),
        (root / "entities" / "relations.json", Relation, True),
    ]
    for path in sorted((root / "episodes").glob("*.json")):
        checks.append((path, Episode, False))
    for path in sorted((root / "shots").glob("*.json")):
        checks.append((path, Shot, True))
    for path in sorted((root / "bindings").glob("*.json")):
        checks.append((path, BindingFile, False))
    for path in sorted((root / "summaries").glob("*.json")):
        checks.append((path, Summary, False))

    for path, model, is_list in checks:
        if not path.exists():
            issues.append(ValidationIssue(path=str(path), message="required file is missing"))
            continue
        try:
            data = read_json(path, [] if is_list else {})
            if is_list:
                for item in data:
                    model.model_validate(item)
            else:
                model.model_validate(data)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            issues.append(ValidationIssue(path=str(path), message=str(exc)))

    if (root / "source.txt").exists() is False:
        issues.append(ValidationIssue(path=str(root / "source.txt"), message="source.txt is missing"))

    if not any(issue.severity == "error" for issue in issues):
        stored = read_model(root / "index.json", WorkIndex)
        computed = build_index(work_id)
        if stored != computed:
            if fix_index:
                rebuild_index(work_id)
            else:
                issues.append(
                    ValidationIssue(
                        path=str(root / "index.json"),
                        message="index.json diverges from entities/shots/bindings; rerun validate --fix-index",
                    )
                )
    return ValidationReport(work_id=work_id, ok=not issues, issues=issues)
