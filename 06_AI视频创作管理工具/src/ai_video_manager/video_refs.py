"""Shared video reference limits and collection for HTTP / CLI adapters."""

from __future__ import annotations

MAX_REFERENCE_IMAGES = 9
MAX_REFERENCE_VIDEOS = 3
MAX_REFERENCE_AUDIOS = 3
MAX_REFERENCE_FILES = 12


def list_asset_urls(assets: dict, *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = assets.get(key)
        if isinstance(raw, list):
            values.extend(str(item).strip() for item in raw if isinstance(item, str) and item.strip())
    return values


def is_remote_ref(value: str) -> bool:
    clean = str(value or "").strip()
    return clean.startswith(("http://", "https://", "asset://"))


def infer_ref_kind(value: str) -> str:
    lower = value[:80].lower()
    if lower.startswith("data:image/") or looks_like_image_ref(value):
        return "image"
    if lower.startswith("data:video/") or lower.startswith("assets/videos/") or any(
        ext in value.lower() for ext in (".mp4", ".mov", ".webm", ".m4v")
    ):
        return "video"
    if lower.startswith("data:audio/") or lower.startswith("assets/audio/") or any(
        ext in value.lower() for ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
    ):
        return "audio"
    return "image"


def looks_like_image_ref(value: str) -> bool:
    lower = value[:64].lower()
    if lower.startswith("data:image/"):
        return True
    if lower.startswith(("http://", "https://")):
        return any(ext in value.lower() for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"))
    if value.lower().startswith("assets/images/"):
        return True
    return False


def collect_references(
    assets: dict,
    *,
    reference_mode: str = "omni",
    local_paths_only: bool = False,
) -> dict[str, list[dict[str, str]]]:
    """Collect typed refs for Seedance HTTP or 小云雀 CLI (local_paths_only=True)."""
    mode = str(reference_mode or "none").strip().lower() or "none"
    images: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    audios: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(bucket: list[dict[str, str]], value: str, role: str, label: str) -> None:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            return
        if local_paths_only:
            if clean.startswith(("http://", "https://", "data:", "asset://")):
                return
        elif not is_remote_ref(clean):
            # HTTP 出站只吃 prepare 后的 https/asset。出现本地路径 = prepare 没跑完或绕过了 prepare。
            raise ValueError(
                f"内部错误：outbound 仍含本地/data 引用（{clean[:120]}）。"
                "HTTP 通道必须先经 OSS 直传；请勿绕过 prepare_video_assets。"
            )
        seen.add(clean)
        entry: dict[str, str] = {"url": clean, "role": role, "label": label}
        if local_paths_only:
            entry["path"] = clean
        bucket.append(entry)

    if mode == "none":
        return {"images": [], "videos": [], "audios": []}

    if mode == "first_last":
        first = str(assets.get("first_frame") or "").strip()
        last = str(assets.get("last_frame") or "").strip()
        if first:
            _add(images, first, "first_frame", "首帧")
        if last:
            _add(images, last, "last_frame", "尾帧")
        return {"images": images[:2], "videos": [], "audios": []}

    image_role = "reference_image"
    for url in list_asset_urls(assets, "reference_images"):
        _add(images, url, image_role, "参考图")
    if mode == "omni":
        for url in list_asset_urls(assets, "video_clips", "reference_videos"):
            _add(videos, url, "reference_video", "参考视频")
        for url in list_asset_urls(assets, "audio_samples", "reference_audios"):
            _add(audios, url, "reference_audio", "参考音频")
        if not images and not videos and not audios:
            for url in list_asset_urls(assets, "assets"):
                kind = infer_ref_kind(url)
                if kind == "image":
                    _add(images, url, "reference_image", "参考图")
                elif kind == "video":
                    _add(videos, url, "reference_video", "参考视频")
                elif kind == "audio":
                    _add(audios, url, "reference_audio", "参考音频")

    images = images[:MAX_REFERENCE_IMAGES]
    videos = videos[:MAX_REFERENCE_VIDEOS]
    audios = audios[:MAX_REFERENCE_AUDIOS]
    total = len(images) + len(videos) + len(audios)
    if total > MAX_REFERENCE_FILES:
        overflow = total - MAX_REFERENCE_FILES
        while overflow > 0 and audios:
            audios.pop()
            overflow -= 1
        while overflow > 0 and videos:
            videos.pop()
            overflow -= 1
        while overflow > 0 and images:
            images.pop()
            overflow -= 1
    return {"images": images, "videos": videos, "audios": audios}


def collect_typed_references(assets: dict, *, reference_mode: str = "omni") -> dict[str, list[dict[str, str]]]:
    return collect_references(assets, reference_mode=reference_mode, local_paths_only=False)


def collect_local_references(assets: dict, *, reference_mode: str = "omni") -> dict[str, list[dict[str, str]]]:
    return collect_references(assets, reference_mode=reference_mode, local_paths_only=True)
