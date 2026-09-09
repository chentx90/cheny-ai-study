from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_video_manager.api.utils import _dump
from ai_video_manager.project_bundle import resolve_project_data_root
from ai_video_manager.models import EntityCard, PromptCard
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.video_refs import (
    MAX_REFERENCE_AUDIOS,
    MAX_REFERENCE_FILES,
    MAX_REFERENCE_IMAGES,
    MAX_REFERENCE_VIDEOS,
)
from ai_video_manager.xyq_cli import is_xyq_provider

VideoAssetUploader = Callable[[Path, str], str]

def collect_prompt_card_assets(store: SQLiteStore, card: PromptCard) -> dict[str, object]:
    cards = []
    assets: list[str] = []
    reference_images: list[str] = []
    audio_samples: list[str] = []
    video_clips: list[str] = []

    for entity_card in matched_prompt_card_entities(store, card):
        cards.append(_dump(entity_card))
        assets.extend(entity_card.assets)
        reference_images.extend(entity_card.reference_images)
        audio_samples.extend(entity_card.audio_samples)
        video_clips.extend(entity_card.video_clips)

    return {
        "entity_cards": cards,
        "assets": dedupe_list(assets),
        "reference_images": reference_images,
        "audio_samples": audio_samples,
        "video_clips": video_clips,
    }


def match_prompt_card_subjects(
    store: SQLiteStore,
    card: PromptCard,
    entity_cards: list[EntityCard] | None = None,
    reasons_by_id: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    entity_cards = entity_cards if entity_cards is not None else matched_prompt_card_entities(store, card)
    reasons_by_id = reasons_by_id or {}
    asset_by_path = {asset["path"]: asset for asset in store.list_assets(card.project_id)}

    matches = []
    for entity_card in entity_cards:
        paths = card_asset_paths(entity_card)
        matches.append(
            {
                "entity_card": _dump(entity_card),
                "asset_paths": paths,
                "assets": [asset_by_path.get(path) or missing_asset_record(path) for path in paths],
                "reasons": reasons_by_id.get(entity_card.id) or [],
            }
        )

    assets = collect_prompt_card_assets(store, card)
    assets["asset_records"] = [
        asset_by_path.get(path) or missing_asset_record(path)
        for path in list_value(assets.get("assets"))
        if isinstance(path, str)
    ]
    return {"matches": matches, "assets": assets}


def matched_prompt_card_entities(store: SQLiteStore, card: PromptCard) -> list[EntityCard]:
    matched: list[EntityCard] = []
    seen_card_ids: set[str] = set()
    linked_ids = store.prompt_card_entity_ids(card.project_id, card.id) if card.id else []
    for card_id in linked_ids or entity_card_ids_from_anchor_text(card.anchor_text):
        try:
            entity_card = store.get_entity_card(card.project_id, card_id)
        except KeyError:
            continue
        seen_card_ids.add(entity_card.id)
        matched.append(entity_card)

    return matched


def entity_cards_by_ids(store: SQLiteStore, project_id: str, entity_card_ids: list[str]) -> list[EntityCard]:
    cards: list[EntityCard] = []
    seen: set[str] = set()
    for card_id in entity_card_ids:
        clean_id = str(card_id or "").strip()
        if not clean_id or clean_id in seen:
            continue
        try:
            entity_card = store.get_entity_card(project_id, clean_id)
        except KeyError:
            continue
        seen.add(entity_card.id)
        cards.append(entity_card)
    return cards


def entity_card_ids_from_anchor_text(anchor_text: str) -> list[str]:
    return dedupe_list(re.findall(r"\bcard_[0-9a-fA-F]{12}\b", anchor_text or ""))


CARD_ID_PATTERN = re.compile(r"\bcard_[0-9a-fA-F]{12}\b")
AT_MENTION_PATTERN = re.compile(r"(?<!\w)@([^\s@，,。；;：:\n\r\[\]()（）]+)")


def resolve_prompt_mentions(
    store: SQLiteStore,
    project_id: str,
    prompt_text: str,
    *,
    existing_anchor_text: str = "",
) -> dict[str, object]:
    """Resolve @mentions and card_xxx ids in prompt/anchor text to entity cards."""
    library = store.list_entity_cards(project_id)
    by_id = {card.id: card for card in library}
    name_index: dict[str, list[EntityCard]] = {}
    for card in library:
        key = _normalize_mention_key(card.entity_name)
        name_index.setdefault(key, []).append(card)
        if card.state:
            state_key = _normalize_mention_key(f"{card.entity_name}{card.state}")
            name_index.setdefault(state_key, []).append(card)
            dotted = _normalize_mention_key(f"{card.entity_name}·{card.state}")
            name_index.setdefault(dotted, []).append(card)

    matched: list[EntityCard] = []
    missing: list[str] = []
    seen: set[str] = set()

    def _add(card: EntityCard | None, token: str) -> None:
        if card is None:
            if token and token not in missing:
                missing.append(token)
            return
        if card.id in seen:
            return
        seen.add(card.id)
        matched.append(card)

    for card_id in CARD_ID_PATTERN.findall(f"{prompt_text or ''}\n{existing_anchor_text or ''}"):
        _add(by_id.get(card_id), card_id)

    for raw in AT_MENTION_PATTERN.findall(prompt_text or ""):
        token = raw.strip()
        if not token:
            continue
        if CARD_ID_PATTERN.fullmatch(token):
            _add(by_id.get(token), token)
            continue
        key = _normalize_mention_key(token)
        candidates = name_index.get(key) or []
        if not candidates and "·" in token:
            candidates = name_index.get(_normalize_mention_key(token.replace("·", ""))) or []
        _add(candidates[0] if candidates else None, f"@{token}")

    anchor_text = format_subject_anchor_text(matched)
    return {
        "entity_card_ids": [card.id for card in matched],
        "entity_cards": [_dump(card) for card in matched],
        "anchor_text": anchor_text,
        "missing": missing,
        "assets": collect_prompt_card_assets(
            store,
            PromptCard(
                project_id=project_id,
                segment_id="mention",
                order=0,
                title="mention",
                prompt_text=prompt_text or "",
                anchor_text=anchor_text,
            ),
        ),
    }


def _normalize_mention_key(value: str) -> str:
    return re.sub(r"[\s_\-·.]+", "", str(value or "").strip().lower())


REFERENCE_MODES = {"none", "first_last", "multi", "omni"}


def prioritize_character_reference_images(assets: dict[str, object]) -> dict[str, object]:
    """Put character entity images before scene/prop so @图1 优先锁人物。"""
    merged = dict(assets or {})
    images = [str(item).strip() for item in list_value(merged.get("reference_images")) if str(item).strip()]
    if len(images) <= 1:
        return merged

    character_paths: set[str] = set()
    for card in list_value(merged.get("entity_cards")):
        if not isinstance(card, dict):
            continue
        typ = str(card.get("type") or "").lower()
        if "character" not in typ and typ not in {"人物", "角色"}:
            continue
        for key in ("assets", "reference_images"):
            for path in list_value(card.get(key)):
                clean = str(path or "").strip()
                if clean:
                    character_paths.add(clean)

    if not character_paths:
        return merged

    head = [path for path in images if path in character_paths]
    tail = [path for path in images if path not in character_paths]
    merged["reference_images"] = dedupe_list([*head, *tail])
    return merged


def apply_reference_mode(
    assets: dict[str, object],
    *,
    reference_mode: str = "none",
    first_frame: str | None = None,
    last_frame: str | None = None,
    reference_images: list[str] | None = None,
    reference_videos: list[str] | None = None,
    reference_audios: list[str] | None = None,
) -> dict[str, object]:
    mode = str(reference_mode or "none").strip().lower() or "none"
    if mode not in REFERENCE_MODES:
        raise ValueError(f"Unsupported reference_mode: {reference_mode}")

    merged = dict(assets or {})
    first = str(first_frame or "").strip()
    last = str(last_frame or "").strip()
    images = [str(item).strip() for item in (reference_images or []) if str(item).strip()]
    videos = [str(item).strip() for item in (reference_videos or []) if str(item).strip()]
    audios = [str(item).strip() for item in (reference_audios or []) if str(item).strip()]

    if mode == "none":
        merged["reference_mode"] = "none"
        return merged

    if mode == "first_last":
        frames = [path for path in [first, last] if path]
        if not frames:
            raise ValueError("first_last 模式至少需要首帧或尾帧")
        if len(frames) > 2:
            raise ValueError("first_last 模式最多支持 2 张图")
        merged["reference_mode"] = "first_last"
        merged["first_frame"] = first or None
        merged["last_frame"] = last or None
        merged["reference_images"] = dedupe_list([*list_value(merged.get("reference_images")), *frames])
        return merged

    if mode == "multi":
        if videos or audios:
            raise ValueError("multi 模式不支持视频/音频参考，请改用 omni")
        if not images and not list_value(merged.get("reference_images")):
            raise ValueError("multi 模式至少需要一张参考图")
        merged["reference_mode"] = "multi"
        merged["reference_images"] = dedupe_list([*list_value(merged.get("reference_images")), *images])
        return merged

    # omni — 无素材时自动降级为 none，避免纯提示词任务被误拦
    if not images and not videos and not audios and not any(
        list_value(merged.get(key)) for key in ("reference_images", "video_clips", "audio_samples", "assets")
    ):
        merged["reference_mode"] = "none"
        return merged
    merged["reference_mode"] = "omni"
    merged["reference_images"] = dedupe_list([*list_value(merged.get("reference_images")), *images])
    merged["video_clips"] = dedupe_list([*list_value(merged.get("video_clips")), *videos])
    merged["audio_samples"] = dedupe_list([*list_value(merged.get("audio_samples")), *audios])
    return merged


def subject_match_prompt_card_json(card: PromptCard) -> str:
    return json.dumps(
        {
            "id": card.id,
            "order": card.order,
            "title": card.title,
            "source_text": card.source_text,
            "prompt_text": card.prompt_text,
            "duration": card.duration,
            "existing_anchor_text": card.anchor_text,
        },
        ensure_ascii=False,
        indent=2,
    )


def subject_match_entity_catalog_json(store: SQLiteStore, project_id: str) -> str:
    asset_by_path = {asset["path"]: asset for asset in store.list_assets(project_id)}
    rows = []
    for card in store.list_entity_cards(project_id):
        assets = []
        for path in card_asset_paths(card):
            asset = asset_by_path.get(path) or missing_asset_record(path)
            assets.append(
                {
                    "path": asset.get("path"),
                    "filename": asset.get("filename"),
                    "asset_type": asset.get("asset_type"),
                }
            )
        rows.append(
            {
                "entity_card_id": card.id,
                "name": card.entity_name,
                "type": card.type.value if hasattr(card.type, "value") else str(card.type),
                "state": card.state or "",
                "tags": card.tags,
                "assets": assets,
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def parse_subject_match_entity_ids(rows: list[object], available_ids: set[str]) -> tuple[list[str], dict[str, list[str]]]:
    ids: list[str] = []
    reasons: dict[str, list[str]] = {}
    for item in rows:
        if isinstance(item, str):
            card_id = item.strip()
            reason = ""
        elif isinstance(item, dict):
            card_id = str(
                item.get("entity_card_id")
                or item.get("entityCardId")
                or item.get("card_id")
                or item.get("id")
                or ""
            ).strip()
            reason = str(item.get("reason") or item.get("理由") or "").strip()
        else:
            continue
        if card_id not in available_ids or card_id in ids:
            continue
        ids.append(card_id)
        if reason:
            reasons.setdefault(card_id, []).append(reason)
    return ids, reasons


def card_asset_paths(card: EntityCard) -> list[str]:
    return [
        path
        for path in dedupe_list(
            [
                *card.assets,
                *card.reference_images,
                *card.audio_samples,
                *card.video_clips,
            ]
        )
        if isinstance(path, str)
    ]


def format_subject_anchor_text(entity_cards: list[EntityCard]) -> str:
    if not entity_cards:
        return ""
    return "\n".join(format_subject_anchor_line(card) for card in entity_cards)


def format_subject_anchor_line(card: EntityCard) -> str:
    type_label = {
        "character": "参考人物",
        "scene": "参考场景",
        "prop": "参考物品",
    }.get(str(card.type.value if hasattr(card.type, "value") else card.type), "参考主体")
    state = f" · {card.state}" if card.state else ""
    tags = f"（{' / '.join(card.tags)}）" if card.tags else ""
    return f"{type_label}: {card.entity_name}{state}{tags} [{card.id}]"


def missing_asset_record(path: str) -> dict[str, object]:
    normalized = str(path or "")
    filename = normalized.rsplit("/", 1)[-1] or normalized
    return {
        "path": normalized,
        "filename": filename,
        "asset_type": infer_asset_type(normalized),
        "bytes": 0,
        "missing": True,
    }


def infer_asset_type(path: str) -> str:
    lower = path.casefold()
    if lower.startswith("assets/images/") or lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif")):
        return "image"
    if lower.startswith("assets/audio/") or lower.endswith((".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus")):
        return "audio"
    if lower.startswith("assets/videos/") or lower.endswith((".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")):
        return "video"
    return "unknown"


def merge_video_assets(base: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key in ("entity_cards", "assets", "reference_images", "audio_samples", "video_clips"):
        base_values = merged.get(key) if isinstance(merged.get(key), list) else []
        incoming_values = incoming.get(key) if isinstance(incoming.get(key), list) else []
        merged[key] = dedupe_list([*base_values, *incoming_values])
    return merged


def collect_video_assets(
    *,
    store: SQLiteStore,
    project_id: str,
    segment_id: str,
    request_assets: dict[str, object],
) -> dict[str, object]:
    assets: dict[str, object] = dict(request_assets or {})
    blob = store.get_workspace_blob(project_id)
    entities = blob.get("entities") if isinstance(blob.get("entities"), list) else []
    cards = []
    mixed_assets: list[str] = []
    reference_images: list[str] = []
    audio_samples: list[str] = []
    video_clips: list[str] = []
    seen_card_ids: set[str] = set()

    for entity in entities:
        if not isinstance(entity, dict) or not entity.get("confirmed"):
            continue
        segment_ids = entity.get("segment_ids")
        if isinstance(segment_ids, list) and segment_ids and segment_id not in segment_ids:
            continue
        binding = entity.get("binding") if isinstance(entity.get("binding"), dict) else {}
        card_id = binding.get("cardId") or binding.get("card_id")
        if not isinstance(card_id, str) or card_id in seen_card_ids:
            continue
        try:
            card = store.get_entity_card(project_id, card_id)
        except KeyError:
            continue
        seen_card_ids.add(card.id)
        cards.append(_dump(card))
        mixed_assets.extend(card.assets)
        reference_images.extend(card.reference_images)
        audio_samples.extend(card.audio_samples)
        video_clips.extend(card.video_clips)

    assets["entity_cards"] = dedupe_list([*list_value(assets.get("entity_cards")), *cards])
    assets["assets"] = dedupe_list([*list_value(assets.get("assets")), *mixed_assets])
    assets["reference_images"] = dedupe_list([*list_value(assets.get("reference_images")), *reference_images])
    assets["audio_samples"] = dedupe_list([*list_value(assets.get("audio_samples")), *audio_samples])
    assets["video_clips"] = dedupe_list([*list_value(assets.get("video_clips")), *video_clips])
    return assets


def list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def dedupe_list(items: list[object]) -> list[object]:
    deduped: list[object] = []
    seen: set[str] = set()
    for item in items:
        marker = repr(item)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)
    return deduped


def prepare_video_assets_for_api(
    store: SQLiteStore,
    project_id: str,
    assets: dict[str, object],
    *,
    uploader: VideoAssetUploader | None = None,
) -> dict[str, object]:
    """Resolve local project asset paths for HTTP video gateways.

    Outbound refs must be http(s):// or asset:// only.
    Local files go through OSS 直传 (uploader)；无 base64、无本机签名链回退。
    """
    merged = dict(assets or {})
    mode = str(merged.get("reference_mode") or "none").strip().lower() or "none"
    if mode == "none":
        return merged

    def _resolve(raw: str) -> str:
        return resolve_video_asset_reference(
            store,
            project_id,
            raw,
            uploader=uploader,
        )

    for key in ("first_frame", "last_frame"):
        raw = str(merged.get(key) or "").strip()
        if raw:
            merged[key] = _resolve(raw)

    # 有显式参考列表时，不再把混合 assets 袋一并编码（体积翻倍易 403）
    explicit = any(
        list_value(merged.get(key))
        for key in ("reference_images", "video_clips", "audio_samples", "reference_videos", "reference_audios")
    ) or bool(str(merged.get("first_frame") or "").strip()) or bool(str(merged.get("last_frame") or "").strip())

    # omni：把混合 assets 袋拆进类型列表，确保音频/视频也会走 OSS，而不是被 content 组装静默跳过
    if mode == "omni" and list_value(merged.get("assets")):
        from ai_video_manager.video_refs import infer_ref_kind

        bag_images: list[str] = []
        bag_videos: list[str] = []
        bag_audios: list[str] = []
        for item in list_value(merged.get("assets")):
            kind = infer_ref_kind(str(item))
            if kind == "video":
                bag_videos.append(str(item))
            elif kind == "audio":
                bag_audios.append(str(item))
            else:
                bag_images.append(str(item))
        if bag_images:
            merged["reference_images"] = dedupe_list([*list_value(merged.get("reference_images")), *bag_images])
            explicit = True
        if bag_videos:
            merged["video_clips"] = dedupe_list([*list_value(merged.get("video_clips")), *bag_videos])
            explicit = True
        if bag_audios:
            merged["audio_samples"] = dedupe_list([*list_value(merged.get("audio_samples")), *bag_audios])
            explicit = True
        # 已拆分，避免后续再次把本地袋塞进 content
        merged["assets"] = []

    encode_keys = ["reference_images", "video_clips", "audio_samples", "reference_videos", "reference_audios"]
    if not explicit:
        encode_keys.append("assets")

    limits = {
        "reference_images": MAX_REFERENCE_IMAGES,
        "video_clips": MAX_REFERENCE_VIDEOS,
        "reference_videos": MAX_REFERENCE_VIDEOS,
        "audio_samples": MAX_REFERENCE_AUDIOS,
        "reference_audios": MAX_REFERENCE_AUDIOS,
        "assets": MAX_REFERENCE_FILES,
    }
    for key in encode_keys:
        raw_items = list_value(merged.get(key))
        if not raw_items:
            continue
        capped = [str(item) for item in raw_items if str(item or "").strip()][: limits.get(key, MAX_REFERENCE_FILES)]
        merged[key] = [_resolve(str(item)) for item in capped if str(item or "").strip()]

    # 硬校验：参考模式仍残留本地路径则禁止提交
    leftovers: list[str] = []
    for key in ("first_frame", "last_frame", "reference_images", "video_clips", "reference_videos", "audio_samples", "reference_audios", "assets"):
        raw = merged.get(key)
        items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, str) and str(raw).strip() else [])
        for item in items:
            clean = str(item or "").strip()
            if not clean:
                continue
            if clean.startswith(("http://", "https://", "asset://")):
                continue
            leftovers.append(f"{key}:{clean[:80]}")
    if leftovers:
        raise ValueError(
            "参考素材准备后仍非 https/asset://，禁止提交视频请求："
            + "; ".join(leftovers[:6])
        )
    return merged


def resolve_project_asset_file(store: SQLiteStore, project_id: str, path: str) -> Path:
    """Resolve a project-relative asset path against the configured data_root."""
    clean = str(path or "").strip()
    if not clean:
        raise ValueError("素材路径为空")
    project_root = resolve_project_data_root(store, project_id).resolve()
    candidate = (project_root / clean.lstrip("/")).resolve()
    if not str(candidate).startswith(str(project_root)):
        raise ValueError(f"非法素材路径：{clean}")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"找不到参考素材：{clean}")
    return candidate


def resolve_video_asset_reference(
    store: SQLiteStore,
    project_id: str,
    path: str,
    *,
    uploader: VideoAssetUploader | None = None,
) -> str:
    """Return a gateway-usable reference: https?:// or asset:// only.

    Local files must succeed via OSS 直传 (uploader). No base64, no signed localhost.
    """
    from ai_video_manager.gateway_media import stabilize_oss_public_url

    clean = str(path or "").strip()
    if not clean:
        return ""
    if clean.startswith("data:"):
        raise ValueError(
            "参考素材禁止使用 base64/data URL（网关常忽略且仍会扣费）。"
            "请使用已上云的 https / asset://，或经 OSS 直传上传。"
        )
    if clean.startswith(("http://", "https://", "asset://")):
        return stabilize_oss_public_url(clean) if clean.startswith(("http://", "https://")) else clean

    candidate = resolve_project_asset_file(store, project_id, clean)

    import mimetypes

    from ai_video_manager.gateway_media import infer_gateway_asset_type

    mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    asset_type = infer_gateway_asset_type(candidate, mime_type)

    if not callable(uploader):
        raise ValueError(
            f"本地参考素材无法提交（{clean}）：未配置 OSS 上传客户端。"
            "请配置 videoBaseUrl/videoApiKey（星链云走 https://oss.vjimeng.vip），"
            "或在参考里直接填 https / asset://。"
        )

    try:
        remote = str(uploader(candidate, asset_type) or "").strip()
    except Exception as exc:
        raise ValueError(
            f"素材 OSS 直传失败（{clean}）：{exc}。"
            "星链云唯一上传途径是 https://oss.vjimeng.vip；禁止 base64 / 本机链回退。"
        ) from exc

    if remote.startswith(("http://", "https://")):
        return stabilize_oss_public_url(remote)
    if remote.startswith("asset://"):
        return remote
    raise ValueError(
        f"素材上传未返回可用公网引用（{clean}）：{remote[:160] or '空响应'}。"
        "仅允许 https 或 asset://；上传失败不会继续提交视频请求。"
    )


def resolve_xyq_local_path(store: SQLiteStore, project_id: str, path: str) -> str:
    """Resolve a project-relative asset path to an absolute local file for 小云雀 CLI."""
    clean = str(path or "").strip()
    if not clean:
        return ""
    if clean.startswith(("http://", "https://")):
        raise ValueError(f"小云雀 CLI 需要本地文件路径，不支持 URL：{clean}")
    if clean.startswith("data:"):
        raise ValueError(f"小云雀 CLI 需要本地文件路径，不支持 data URL：{clean[:48]}...")
    if clean.startswith("asset://"):
        raise ValueError(f"小云雀 CLI 需要本地文件路径，不支持 asset://：{clean}")

    return str(resolve_project_asset_file(store, project_id, clean))


def prepare_video_assets_for_xyq(store: SQLiteStore, project_id: str, assets: dict[str, object]) -> dict[str, object]:
    """Resolve local project asset paths to absolute paths for pippit-tool-cli."""
    merged = dict(assets or {})
    mode = str(merged.get("reference_mode") or "none").strip().lower() or "none"
    if mode == "none":
        return merged

    for key in ("first_frame", "last_frame"):
        raw = str(merged.get(key) or "").strip()
        if raw:
            merged[key] = resolve_xyq_local_path(store, project_id, raw)

    explicit = any(
        list_value(merged.get(key))
        for key in ("reference_images", "video_clips", "audio_samples", "reference_videos", "reference_audios")
    ) or bool(str(merged.get("first_frame") or "").strip()) or bool(str(merged.get("last_frame") or "").strip())

    resolve_keys = ["reference_images", "video_clips", "audio_samples", "reference_videos", "reference_audios"]
    if not explicit:
        resolve_keys.append("assets")

    limits = {
        "reference_images": MAX_REFERENCE_IMAGES,
        "video_clips": MAX_REFERENCE_VIDEOS,
        "reference_videos": MAX_REFERENCE_VIDEOS,
        "audio_samples": MAX_REFERENCE_AUDIOS,
        "reference_audios": MAX_REFERENCE_AUDIOS,
        "assets": MAX_REFERENCE_FILES,
    }
    for key in resolve_keys:
        raw_items = list_value(merged.get(key))
        if not raw_items:
            continue
        capped = [str(item) for item in raw_items if str(item or "").strip()][: limits.get(key, MAX_REFERENCE_FILES)]
        merged[key] = [
            resolve_xyq_local_path(store, project_id, str(item))
            for item in capped
            if str(item or "").strip()
        ]
    return merged


def prepare_video_assets(
    store: SQLiteStore,
    project_id: str,
    assets: dict[str, object],
    *,
    provider: str,
    uploader: VideoAssetUploader | None = None,
) -> dict[str, object]:
    """Resolve references for the active video provider (HTTP OSS URLs vs CLI local paths)."""
    if is_xyq_provider(provider):
        return prepare_video_assets_for_xyq(store, project_id, assets)
    return prepare_video_assets_for_api(
        store,
        project_id,
        assets,
        uploader=uploader,
    )
