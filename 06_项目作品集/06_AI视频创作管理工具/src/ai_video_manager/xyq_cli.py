from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

XYQ_DEFAULT_OPENAPI_BASE = "https://xyq.jianying.com"
XYQ_DEFAULT_MODEL = "Seedance_2.0_mini_lite"
XYQ_DEFAULT_POLL_INTERVAL = 10.0
XYQ_DEFAULT_TIMEOUT = 1800.0

XYQ_VIDEO_MODELS = [
    "Seedance_2.0_mini_lite",
    "Seedance_2.0_mini",
    "seedance2.0_vision",
    "seedance2.0_fast_vision",
]

XYQ_PROVIDER_ALIASES = {"xyq", "xiaoyunque", "pippit"}


def is_xyq_provider(provider: str) -> bool:
    return str(provider or "").strip().lower() in XYQ_PROVIDER_ALIASES


def encode_xyq_task_id(thread_id: str, run_id: str) -> str:
    return f"{thread_id}:{run_id}"


def decode_xyq_task_id(task_id: str) -> tuple[str, str]:
    clean = str(task_id or "").strip()
    if ":" not in clean:
        raise ValueError(f"无效的小云雀任务 ID（应为 thread_id:run_id）：{clean}")
    thread_id, run_id = clean.split(":", 1)
    thread_id = thread_id.strip()
    run_id = run_id.strip()
    if not thread_id or not run_id:
        raise ValueError(f"无效的小云雀任务 ID（应为 thread_id:run_id）：{clean}")
    return thread_id, run_id


def parse_cli_json(stdout: str) -> dict[str, Any]:
    text = str(stdout or "").strip()
    if not text:
        raise RuntimeError("小云雀 CLI 未返回输出")
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
    raise RuntimeError(f"无法解析小云雀 CLI JSON 输出：{text[:500]}")


def resolve_xyq_cli_path(configured: str | None = None) -> str:
    """Resolve the native CLI binary.

    Prefer ``pippit-tool-cli.exe`` over the npm ``.cmd`` shim. On Windows the
    shim goes through ``cmd.exe``, which mangles argv when reference paths
    contain spaces or non-ASCII characters — causing ``--model/--ratio/...``
    to be dropped and the API to report missing ``video_part_tool_param`` fields.
    """
    custom = str(configured or "").strip()
    if custom:
        candidate = Path(custom).expanduser()
        if candidate.is_file():
            return str(_ensure_native_cli_binary(_unwrap_npm_shim(candidate)).resolve())
        raise RuntimeError(f"找不到小云雀 CLI 可执行文件：{custom}")

    for name in ("pippit-tool-cli.exe", "pippit-tool-cli"):
        found = shutil.which(name)
        if found:
            return str(_ensure_native_cli_binary(_unwrap_npm_shim(Path(found))).resolve())

    raise RuntimeError(
        "未找到 pippit-tool-cli。请先运行 npx @pippit-dev/cli@latest install，"
        "或在设置中填写 xyqCliPath（请指向 bin/pippit-tool-cli 或 .exe，不要填 .cmd）。"
    )


def _unwrap_npm_shim(path: Path) -> Path:
    """Map npm shim (.cmd/.ps1/no-ext) to the real Go binary when possible."""
    resolved = path.resolve()
    suffix = resolved.suffix.lower()
    if suffix == ".exe":
        return resolved

    # npm global: %APPDATA%/npm/pippit-tool-cli.cmd → .../node_modules/@pippit-dev/cli/bin/pippit-tool-cli.exe
    npm_bin_dir = resolved.parent
    packaged = npm_bin_dir / "node_modules" / "@pippit-dev" / "cli" / "bin" / "pippit-tool-cli.exe"
    if packaged.is_file():
        return packaged

    # Linux/mac packaged binary next to npm prefix
    packaged_posix = npm_bin_dir / "node_modules" / "@pippit-dev" / "cli" / "bin" / "pippit-tool-cli"
    if packaged_posix.is_file():
        return packaged_posix

    sibling_exe = resolved.with_suffix(".exe")
    if sibling_exe.is_file():
        return sibling_exe

    # Local node_modules layout
    local = (
        npm_bin_dir.parent
        / "node_modules"
        / "@pippit-dev"
        / "cli"
        / "bin"
        / "pippit-tool-cli.exe"
    )
    if local.is_file():
        return local
    local_posix = local.with_suffix("")
    if local_posix.is_file():
        return local_posix

    return resolved


def _ensure_native_cli_binary(path: Path) -> Path:
    """Refuse shell wrappers so argv with 【】[] / spaces cannot be re-parsed by cmd/sh."""
    suffix = path.suffix.lower()
    if suffix in {".cmd", ".bat", ".ps1"}:
        raise RuntimeError(
            f"xyqCliPath 指向了脚本包装器（{path.name}），在 Windows 上会经 shell 二次解析，"
            "路径或提示词中的空格、【】[]、中文等可能导致参数丢失。"
            "请改为 @pippit-dev/cli/bin/pippit-tool-cli.exe 真实二进制路径。"
        )
    return path


def _normalize_media_path(path: str) -> str:
    clean = str(path or "").strip()
    if not clean:
        return ""
    return str(Path(clean).expanduser().resolve()) if Path(clean).exists() else clean


@dataclass
class XiaoyunqueGenerateResult:
    thread_id: str
    run_id: str
    web_thread_link: str = ""


@dataclass
class XiaoyunqueQueryResult:
    thread_id: str
    run_id: str
    completed: bool
    videos: list[dict[str, str]]
    error_message: str = ""


class XiaoyunqueCliClient:
    def __init__(
        self,
        *,
        access_key: str,
        cli_path: str | None = None,
        openapi_base: str | None = None,
        poll_interval: float = XYQ_DEFAULT_POLL_INTERVAL,
        timeout: float = XYQ_DEFAULT_TIMEOUT,
    ) -> None:
        self.access_key = str(access_key or "").strip()
        self.cli_path = resolve_xyq_cli_path(cli_path)
        self.openapi_base = str(openapi_base or XYQ_DEFAULT_OPENAPI_BASE).strip() or XYQ_DEFAULT_OPENAPI_BASE
        self.poll_interval = float(poll_interval or XYQ_DEFAULT_POLL_INTERVAL)
        self.timeout = float(timeout or XYQ_DEFAULT_TIMEOUT)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["XYQ_ACCESS_KEY"] = self.access_key
        env["XYQ_OPENAPI_BASE"] = self.openapi_base
        env["XYQ_BASE_URL"] = self.openapi_base
        return env

    def _run(self, args: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        from ai_video_manager.process_registry import register_process, unregister_process

        command = [self.cli_path, *args]
        popen_kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": self._env(),
            "cwd": cwd,
            "shell": False,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(command, **popen_kwargs)  # type: ignore[arg-type]
        except FileNotFoundError as exc:
            raise RuntimeError(f"无法执行小云雀 CLI：{self.cli_path}") from exc

        register_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise RuntimeError(f"小云雀 CLI 超时（>{self.timeout:.0f}s）") from exc
        finally:
            unregister_process(proc)

        completed = subprocess.CompletedProcess(
            args=command,
            returncode=int(proc.returncode or 0),
            stdout=stdout or "",
            stderr=stderr or "",
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            flag_summary = " ".join(
                part
                for part in args
                if part.startswith("--") or part in {"generate-video", "query-result", "--version"}
            )
            raise RuntimeError(
                detail or f"小云雀 CLI 失败（exit {completed.returncode}；args={flag_summary}）"
            )
        return completed

    def test_connection(self) -> dict[str, object]:
        if not self.access_key:
            return {"ok": False, "detail": "请填写小云雀 Access Key（videoApiKey）"}
        try:
            completed = self._run(["--version"])
        except RuntimeError as exc:
            return {"ok": False, "detail": str(exc)}
        version = (completed.stdout or completed.stderr or "").strip()
        return {
            "ok": True,
            "detail": f"小云雀 CLI 可用：{version or self.cli_path}",
            "cli_path": self.cli_path,
            "base_url": self.openapi_base,
        }

    def generate_video(
        self,
        *,
        prompt: str,
        images: list[str] | None = None,
        videos: list[str] | None = None,
        audios: list[str] | None = None,
        duration: int | None = None,
        ratio: str | None = None,
        model: str | None = None,
        resolution: str | None = None,
    ) -> XiaoyunqueGenerateResult:
        seconds = None
        if duration is not None:
            try:
                seconds = int(duration)
            except (TypeError, ValueError):
                seconds = None
        if seconds is None or seconds <= 0:
            seconds = 5
        model = str(model or "").strip() or XYQ_DEFAULT_MODEL
        ratio = str(ratio or "").strip() or "9:16"
        resolution = str(resolution or "").strip() or "720p"
        prompt_text = str(prompt or "").strip()

        # 必填参数必须放在素材路径之前：Windows npm .cmd 在路径含空格/中文时会截断后续 argv
        args = [
            "generate-video",
            "--prompt",
            prompt_text,
            "--model",
            model,
            "--ratio",
            ratio,
            "--duration",
            str(seconds),
            "--resolution",
            resolution,
        ]
        for path in images or []:
            normalized = _normalize_media_path(path)
            if normalized:
                args.extend(["--image", normalized])
        for path in videos or []:
            normalized = _normalize_media_path(path)
            if normalized:
                args.extend(["--video", normalized])
        for path in audios or []:
            normalized = _normalize_media_path(path)
            if normalized:
                args.extend(["--audio", normalized])

        completed = self._run(args)
        payload = parse_cli_json(completed.stdout or completed.stderr)
        thread_id = str(payload.get("thread_id") or "").strip()
        run_id = str(payload.get("run_id") or "").strip()
        if not thread_id or not run_id:
            raise RuntimeError(f"小云雀 generate-video 未返回 thread_id/run_id：{payload}")
        return XiaoyunqueGenerateResult(
            thread_id=thread_id,
            run_id=run_id,
            web_thread_link=str(payload.get("web_thread_link") or "").strip(),
        )

    def query_result(
        self,
        *,
        thread_id: str,
        run_id: str,
        download_dir: str | None = None,
    ) -> XiaoyunqueQueryResult:
        args = ["query-result", "--thread-id", thread_id, "--run-id", run_id]
        if download_dir:
            args.extend(["--download-dir", download_dir])
        completed = self._run(args)
        payload = parse_cli_json(completed.stdout)
        videos_raw = payload.get("videos")
        videos: list[dict[str, str]] = []
        if isinstance(videos_raw, list):
            for item in videos_raw:
                if not isinstance(item, dict):
                    continue
                videos.append(
                    {
                        "download_url": str(item.get("download_url") or "").strip(),
                        "output_path": str(item.get("output_path") or "").strip(),
                    }
                )
        return XiaoyunqueQueryResult(
            thread_id=str(payload.get("thread_id") or thread_id).strip(),
            run_id=str(payload.get("run_id") or run_id).strip(),
            completed=bool(payload.get("completed")),
            videos=videos,
            error_message=str(payload.get("error_message") or "").strip(),
        )
