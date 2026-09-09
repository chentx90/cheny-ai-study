from __future__ import annotations

import asyncio
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import TaskStatus, VideoTask, new_id
from .video_client import (
    LangChainVideoClient,
    build_video_client,
    map_generation_status,
)
from .video_refs import (
    collect_local_references,
    collect_typed_references,
)
from .xyq_cli import (
    XYQ_DEFAULT_MODEL,
    XiaoyunqueCliClient,
    decode_xyq_task_id,
    encode_xyq_task_id,
    is_xyq_provider,
)


class VideoAPIAdapter(ABC):
    provider: str = "unconfigured"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        assets: dict,
        duration: int | None = None,
        settings: dict | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def check_status(self, task_id: str) -> TaskStatus:
        raise NotImplementedError

    @abstractmethod
    async def download_result(self, task_id: str, save_path: str) -> bool:
        raise NotImplementedError


class MockVideoAPIAdapter(VideoAPIAdapter):
    """Test-only adapter. Not used in production runtime."""

    provider = "mock"

    async def generate(
        self,
        prompt: str,
        assets: dict,
        duration: int | None = None,
        settings: dict | None = None,
    ) -> str:
        return new_id("api_task")

    async def check_status(self, task_id: str) -> TaskStatus:
        return TaskStatus.COMPLETED

    async def download_result(self, task_id: str, save_path: str) -> bool:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Mock video result for {task_id}\n", encoding="utf-8")
        return True


class UnconfiguredVideoAPIAdapter(VideoAPIAdapter):
    provider = "unconfigured"

    async def generate(
        self,
        prompt: str,
        assets: dict,
        duration: int | None = None,
        settings: dict | None = None,
    ) -> str:
        raise RuntimeError("视频服务未配置，请在设置中填写视频 Base URL 和 API Key")

    async def check_status(self, task_id: str) -> TaskStatus:
        raise RuntimeError("视频服务未配置")

    async def download_result(self, task_id: str, save_path: str) -> bool:
        raise RuntimeError("视频服务未配置")


class LangChainVideoAPIAdapter(VideoAPIAdapter):
    """星链云 demo 协议视频生成（images/audios/videos，无 Seedance content 旧路径）。"""

    provider = "newapi"

    def __init__(
        self,
        *,
        client: LangChainVideoClient,
        provider: str = "newapi",
    ) -> None:
        self.client = client
        self.provider = provider or client.provider or "newapi"
        self.poll_interval = client.poll_interval

    async def generate(
        self,
        prompt: str,
        assets: dict,
        duration: int | None = None,
        settings: dict | None = None,
    ) -> str:
        payload = self._build_payload(prompt, assets, duration=duration, settings=settings)
        task_id, _data = await self.client.create_generation(payload)
        return task_id

    async def check_status(self, task_id: str) -> TaskStatus:
        data = await self.client.get_generation(task_id)
        mapped = map_generation_status(data)
        if mapped == "completed":
            return TaskStatus.COMPLETED
        if mapped == "failed":
            return TaskStatus.FAILED
        return TaskStatus.PROCESSING

    async def download_result(self, task_id: str, save_path: str) -> bool:
        return await self.client.download_result(task_id, save_path)

    def _build_payload(
        self,
        prompt: str,
        assets: dict,
        *,
        duration: int | None,
        settings: dict | None,
    ) -> dict[str, Any]:
        merged_settings = dict(settings or {})
        asset_settings = assets.get("settings") if isinstance(assets.get("settings"), dict) else {}
        merged_settings = {**asset_settings, **merged_settings}
        reference_mode = str(assets.get("reference_mode") or "none").strip().lower() or "none"
        generate_audio = merged_settings.get("generate_audio")
        if generate_audio is None:
            generate_audio = True

        typed = collect_typed_references(assets, reference_mode=reference_mode)
        if reference_mode != "none":
            has_remote = bool(typed.get("images") or typed.get("videos") or typed.get("audios"))
            if not has_remote:
                raise ValueError(
                    f"参考模式为 {reference_mode}，但 outbound content 中没有任何 https/asset 引用。"
                    "禁止空参考提交（会浪费额度且结果不受控）。请确认 OSS 直传成功。"
                )
            from ai_video_manager.gateway_media import verify_http_refs_reachable

            verify_http_refs_reachable(
                [item["url"] for bucket in ("images", "videos", "audios") for item in (typed.get(bucket) or [])]
            )

        # 星链云唯一协议：官方 demo /v1/video/submit/generate（禁止降级到 /videos）
        if not self.client.uses_vjimeng_native_api:
            raise ValueError(
                "HTTP 视频通道仅支持星链云/vjimeng。"
                "请将视频 Base URL 设为 https://www.vjimeng.vip（或含 vjimeng 的地址）。"
                "已删除从未生效的 OpenAI /videos + content.image_url 旧路径。"
            )
        return _build_vjimeng_demo_payload(
            prompt,
            typed,
            assets=assets,
            reference_mode=reference_mode,
            duration=duration,
            settings=merged_settings,
            generate_audio=bool(generate_audio),
        )


# Backward-compatible alias used in tests and imports.
HttpVideoAPIAdapter = LangChainVideoAPIAdapter


class XiaoyunqueCliAdapter(VideoAPIAdapter):
    """Video generation via pippit-tool-cli (小云雀官方 CLI)."""

    provider = "xyq"

    def __init__(self, client: XiaoyunqueCliClient) -> None:
        self.client = client
        self.poll_interval = client.poll_interval
        self.task_timeout = client.timeout
        self._last_status_error = ""

    @property
    def last_status_error(self) -> str:
        return self._last_status_error

    async def generate(
        self,
        prompt: str,
        assets: dict,
        duration: int | None = None,
        settings: dict | None = None,
    ) -> str:
        merged_settings = dict(settings or {})
        asset_settings = assets.get("settings") if isinstance(assets.get("settings"), dict) else {}
        merged_settings = {**asset_settings, **merged_settings}
        reference_mode = str(assets.get("reference_mode") or "none").strip().lower() or "none"
        typed = collect_local_references(assets, reference_mode=reference_mode)
        prompt_text = _inject_seedance_material_mentions(prompt, typed, reference_mode=reference_mode)
        generate_audio = merged_settings.get("generate_audio")
        if generate_audio is None:
            generate_audio = True
        if generate_audio is False and "有声" not in prompt_text and "无声" not in prompt_text:
            prompt_text = f"{prompt_text}\n\n请生成无声视频。".strip()
        elif generate_audio is True and "有声" not in prompt_text and "无声" not in prompt_text:
            prompt_text = f"{prompt_text}\n\n请生成有声视频。".strip()

        model = str(merged_settings.get("model") or "").strip() or XYQ_DEFAULT_MODEL
        ratio = str(
            merged_settings.get("aspect_ratio")
            or merged_settings.get("aspectRatio")
            or "9:16"
        ).strip() or "9:16"
        resolution = str(merged_settings.get("resolution") or "720p").strip() or "720p"
        seconds = duration if duration is not None else merged_settings.get("duration")
        try:
            seconds = int(seconds) if seconds is not None else 5
        except (TypeError, ValueError):
            seconds = 5
        if seconds <= 0:
            seconds = 5

        result = await asyncio.to_thread(
            self.client.generate_video,
            prompt=prompt_text,
            images=[item["path"] for item in typed["images"]],
            videos=[item["path"] for item in typed["videos"]],
            audios=[item["path"] for item in typed["audios"]],
            duration=seconds,
            ratio=ratio,
            model=model,
            resolution=resolution,
        )
        return encode_xyq_task_id(result.thread_id, result.run_id)

    async def check_status(self, task_id: str) -> TaskStatus:
        thread_id, run_id = decode_xyq_task_id(task_id)
        # query-result 现已要求 --download-dir；不传会永远返回 completed=false。
        with tempfile.TemporaryDirectory(prefix="xyq_status_") as temp_dir:
            result = await asyncio.to_thread(
                self.client.query_result,
                thread_id=thread_id,
                run_id=run_id,
                download_dir=temp_dir,
            )
        self._last_status_error = str(result.error_message or "").strip()
        if not result.completed:
            return TaskStatus.PROCESSING
        if result.error_message and not result.videos:
            return TaskStatus.FAILED
        if result.error_message:
            return TaskStatus.FAILED
        if result.videos:
            return TaskStatus.COMPLETED
        return TaskStatus.FAILED

    async def download_result(self, task_id: str, save_path: str) -> bool:
        thread_id, run_id = decode_xyq_task_id(task_id)
        destination = Path(save_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xyq_download_") as temp_dir:
            result = await asyncio.to_thread(
                self.client.query_result,
                thread_id=thread_id,
                run_id=run_id,
                download_dir=temp_dir,
            )
            if result.error_message:
                raise RuntimeError(result.error_message)
            output_path = ""
            for video in result.videos:
                candidate = str(video.get("output_path") or "").strip()
                if candidate and Path(candidate).exists():
                    output_path = candidate
                    break
            if not output_path:
                temp_files = sorted(Path(temp_dir).glob("**/*"))
                for candidate_path in temp_files:
                    if candidate_path.is_file() and candidate_path.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}:
                        output_path = str(candidate_path)
                        break
            if not output_path:
                raise RuntimeError("小云雀任务已完成，但未找到可下载的视频文件")
            shutil.copy2(output_path, destination)
        return True


class VideoGenerationEngine:
    def __init__(
        self,
        api_client: VideoAPIAdapter | None = None,
        archive_root: str | Path = "projects",
        archive_path_resolver: Callable[[VideoTask], Path] | None = None,
    ) -> None:
        self.api_client = api_client or UnconfiguredVideoAPIAdapter()
        self.archive_root = Path(archive_root)
        self.archive_path_resolver = archive_path_resolver

    @property
    def provider(self) -> str:
        return getattr(self.api_client, "provider", "unconfigured") or "unconfigured"

    def set_api_client(self, api_client: VideoAPIAdapter) -> None:
        self.api_client = api_client

    async def generate_preview(self, task: VideoTask, duration: int = 4, *, on_submitted=None, wait: bool = True) -> VideoTask:
        task.duration = duration
        return await self._run_task(task, on_submitted=on_submitted, wait=wait)

    async def generate_full_video(self, task: VideoTask, *, on_submitted=None, wait: bool = True) -> VideoTask:
        return await self._run_task(task, on_submitted=on_submitted, wait=wait)

    async def _run_task(self, task: VideoTask, *, on_submitted=None, wait: bool = True) -> VideoTask:
        task.status = TaskStatus.PROCESSING
        task.provider = self.provider
        task.error_message = None
        try:
            task.api_task_id = await self.api_client.generate(
                task.prompt,
                task.assets,
                duration=task.duration,
                settings=video_task_settings(task),
            )
            if on_submitted is not None:
                on_submitted(task)
            if wait:
                await self.wait_until_done(task)
        except asyncio.CancelledError:
            task.status = TaskStatus.PROCESSING
            task.error_message = task.error_message or "服务关闭，任务仍在远端运行，可稍后追回"
            raise
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error_message = str(exc)
        return task

    async def recover_task(self, task: VideoTask, *, api_task_id: str | None = None, timeout: float | None = None) -> VideoTask:
        """Re-poll a remote gateway task and download the result when ready."""
        remote_id = str(api_task_id or task.api_task_id or "").strip()
        if not remote_id:
            raise ValueError("没有远端任务 ID，无法追回。请填写网关返回的 task id。")
        task.api_task_id = remote_id
        task.status = TaskStatus.PROCESSING
        task.error_message = None
        task.provider = self.provider
        try:
            await self.wait_until_done(task, timeout=timeout)
        except asyncio.CancelledError:
            task.status = TaskStatus.PROCESSING
            task.error_message = "服务关闭，任务仍在远端运行，可稍后追回"
            raise
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error_message = str(exc)
        return task

    async def wait_until_done(self, task: VideoTask, timeout: float | None = None, interval: float | None = None) -> VideoTask:
        if not task.api_task_id:
            raise ValueError("task.api_task_id is required before polling")

        effective_timeout = timeout
        if effective_timeout is None:
            effective_timeout = float(getattr(self.api_client, "task_timeout", None) or 600)

        poll_interval = interval
        if poll_interval is None:
            poll_interval = float(getattr(self.api_client, "poll_interval", 2.0) or 2.0)

        elapsed = 0.0
        while elapsed <= effective_timeout:
            status = await self.api_client.check_status(task.api_task_id)
            task.status = status
            if status == TaskStatus.FAILED:
                remote_error = str(getattr(self.api_client, "last_status_error", "") or "").strip()
                if remote_error:
                    task.error_message = remote_error
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        if task.status == TaskStatus.COMPLETED:
            task.result_path = str(self._archive_path(task))
            task.error_message = None
            await self.api_client.download_result(task.api_task_id, task.result_path)
        elif task.status == TaskStatus.FAILED:
            task.error_message = task.error_message or "远端视频任务失败"
        elif elapsed > effective_timeout:
            task.status = TaskStatus.FAILED
            task.error_message = task.error_message or f"Video generation timed out after {effective_timeout}s"
        return task

    async def batch_generate(self, tasks: list[VideoTask], concurrency: int = 2) -> list[VideoTask]:
        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(task: VideoTask) -> VideoTask:
            async with semaphore:
                try:
                    return await self.generate_full_video(task)
                except Exception as exc:
                    task.status = TaskStatus.FAILED
                    task.error_message = str(exc)
                    return task

        return await asyncio.gather(*(run_one(task) for task in tasks))

    def _archive_path(self, task: VideoTask) -> Path:
        if self.archive_path_resolver is not None:
            return self.archive_path_resolver(task)
        filename = f"{task.id}.mp4"
        return self.archive_root / task.project_id / "generated" / task.segment_id / filename


def build_video_adapter(config: dict[str, object]) -> VideoAPIAdapter:
    provider = str(config.get("videoProvider") or "").strip() or "custom"
    if provider.lower() in {"mock", "offline", "local"}:
        raise RuntimeError("mock 视频模式已移除，请在设置中配置真实视频服务")
    api_key = str(config.get("videoApiKey") or "").strip()
    if is_xyq_provider(provider):
        if not api_key:
            raise RuntimeError("小云雀 CLI 需要配置 Access Key（videoApiKey）")
        xyq_client = XiaoyunqueCliClient(
            access_key=api_key,
            cli_path=str(config.get("xyqCliPath") or "").strip() or None,
            openapi_base=str(config.get("xyqOpenApiBase") or "").strip() or None,
        )
        return XiaoyunqueCliAdapter(xyq_client)
    base_url = str(config.get("videoBaseUrl") or "").strip()
    if not base_url or not api_key:
        raise RuntimeError("真实视频服务需要配置 videoBaseUrl 和 videoApiKey")
    client = build_video_client(config)
    return LangChainVideoAPIAdapter(client=client, provider=provider)


def video_task_settings(task: VideoTask) -> dict:
    return dict(task.assets.get("settings") or {}) if isinstance(task.assets.get("settings"), dict) else {}


# Backward-compatible aliases for tests and legacy imports.
_collect_typed_references = collect_typed_references
_collect_local_references = collect_local_references


def _build_vjimeng_demo_payload(
    prompt: str,
    typed: dict[str, list[dict[str, str]]],
    *,
    assets: dict,
    reference_mode: str,
    duration: int | None,
    settings: dict[str, Any],
    generate_audio: bool,
) -> dict[str, Any]:
    """Match official demo测试_v3.1 body for /v1/video/submit/generate."""
    mode = "text2video"
    if reference_mode == "first_last":
        mode = "frames2video"
    elif reference_mode != "none":
        mode = "image2video"

    prompt_text = _inject_vjimeng_material_mentions(prompt, typed, reference_mode=reference_mode)
    ratio = str(settings.get("aspect_ratio") or settings.get("aspectRatio") or settings.get("ratio") or "16:9").strip() or "16:9"
    enable_sound = "on" if generate_audio else "off"
    body: dict[str, Any] = {
        "model": str(settings.get("model") or "").strip() or "sd2-720p-mini",
        "prompt": prompt_text,
        "metadata": {
            "modeType": mode,
            "ratio": ratio,
            "enableSound": enable_sound,
        },
    }
    seconds = duration if duration is not None else settings.get("duration")
    if seconds:
        body["duration"] = int(seconds)

    if mode == "text2video":
        pass
    elif mode == "frames2video":
        first = str(assets.get("first_frame") or "").strip()
        last = str(assets.get("last_frame") or "").strip()
        images: list[str] = []
        if first:
            images.append(first)
        if last:
            images.append(last)
        if not images:
            images = [item["url"] for item in (typed.get("images") or [])][:2]
        if images:
            body["images"] = images
    else:
        images = [item["url"] for item in (typed.get("images") or [])]
        audios = [item["url"] for item in (typed.get("audios") or [])]
        videos = [item["url"] for item in (typed.get("videos") or [])]
        if images:
            body["images"] = images
        if audios:
            body["audios"] = audios
        if videos:
            body["videos"] = videos
    return {key: value for key, value in body.items() if value not in (None, "", [], {})}


def _inject_vjimeng_material_mentions(
    prompt: str,
    typed: dict[str, list[dict[str, str]]],
    *,
    reference_mode: str,
) -> str:
    """官方 demo 用「图片N/音频N/视频N」标签，不是 @图N。"""
    text = str(prompt or "").strip()
    if reference_mode == "none":
        return text
    if "图片1" in text or "音频1" in text or "视频1" in text:
        return text

    mentions: list[str] = []
    for index, item in enumerate(typed.get("images") or [], start=1):
        role = item.get("role") or "reference_image"
        if role == "first_frame":
            mentions.append(f"图片{index}作为首帧")
        elif role == "last_frame":
            mentions.append(f"图片{index}作为尾帧")
        else:
            mentions.append(f"图片{index}作为参考图，保持外观与场景一致性")
    for index, _item in enumerate(typed.get("videos") or [], start=1):
        mentions.append(f"视频{index}参考运镜与动作节奏")
    for index, _item in enumerate(typed.get("audios") or [], start=1):
        mentions.append(f"音频{index}用于配乐/音色参考")
    if not mentions:
        return text
    block = "【素材引用】" + "；".join(mentions) + "。"
    return f"{block}\n{text}" if text else block


def _inject_seedance_material_mentions(
    prompt: str,
    typed: dict[str, list[dict[str, str]]],
    *,
    reference_mode: str,
) -> str:
    """在提示词中注入 @图N/@视频N/@音频N，并写明用途（即梦全能参考语法）。"""
    text = str(prompt or "").strip()
    if reference_mode == "none":
        return text

    mentions: list[str] = []
    for index, item in enumerate(typed.get("images") or [], start=1):
        role = item.get("role") or "reference_image"
        if role == "first_frame":
            mentions.append(f"@图{index} 作为首帧")
        elif role == "last_frame":
            mentions.append(f"@图{index} 作为尾帧")
        else:
            mentions.append(f"@图{index} 作为参考图，保持外观与场景一致性")
    for index, _item in enumerate(typed.get("videos") or [], start=1):
        mentions.append(f"@视频{index} 参考运镜与动作节奏")
    for index, _item in enumerate(typed.get("audios") or [], start=1):
        mentions.append(f"@音频{index} 用于配乐/音色参考")

    if not mentions:
        return text

    block = "【素材引用】" + "；".join(mentions) + "。"
    # 已含同类引用则不重复堆叠
    if "@图1" in text or "@视频1" in text or "@音频1" in text or "【素材引用】" in text:
        return text
    if text:
        return f"{block}\n{text}"
    return block
