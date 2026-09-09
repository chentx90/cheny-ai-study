"""S6 视频提示词管线。

每个场景（Scene）生成一个 txt 文件写入 video_prompts/{scene_id}.txt，
同时把每段 prompt 写回对应 Shot.video_prompt 字段（更新 shots/{scene_id}.json）。

断点续跑：跳过已有 video_prompts/{scene_id}.txt 的场景。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from manga_manager.agents.prompt_composer import (
    ScenePromptResult,
    call_prompt_composer,
    get_video_prompt_config,
)
from manga_manager.models import (
    ArtifactStatus,
    Entity,
    Episode,
    RunState,
    Scene,
    Shot,
    WorkIndex,
)
from manga_manager import store

DEFAULT_WORKERS = 4


@dataclass
class S6Stats:
    total_scenes: int = 0
    scenes_processed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    total_segments: int = 0


@dataclass
class S6Result:
    results: list[ScenePromptResult]
    stats: S6Stats
    scenes_skipped: int = 0

    @property
    def ok(self) -> bool:
        return not self.stats.errors

    def summary_lines(self) -> list[str]:
        return [
            f"处理场景: {self.stats.scenes_processed}/{self.stats.total_scenes}"
            + (f" (跳过 {self.scenes_skipped})" if self.scenes_skipped else ""),
            f"生成段落: {self.stats.total_segments}",
            f"错误: {len(self.stats.errors)}",
        ]


def save_scene_prompt(work_id: str, scene_id: str, prompt_text: str) -> None:
    """保存 prompt 到 video_prompts/{scene_id}.txt。"""
    out_dir = store.work_dir(work_id) / "video_prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{scene_id}.txt"
    path.write_text(prompt_text, encoding="utf-8")


def _filter_episodes_by_scene_range(
    episodes: list[Episode],
    scene_start: int | None,
    scene_end: int | None,
) -> list[Episode]:
    if scene_start is None and scene_end is None:
        return episodes

    filtered: list[Episode] = []
    for ep in episodes:
        scenes = ep.scenes
        if scene_start is not None:
            scenes = [s for s in scenes if s.idx >= scene_start]
        if scene_end is not None:
            scenes = [s for s in scenes if s.idx <= scene_end]
        filtered.append(ep.model_copy(update={"scenes": scenes}))
    return filtered


def _call_one(
    scene: Scene,
    shots: list[Shot],
    entities_by_id: dict[str, Entity],
    style_contract: str,
    max_seg_dur: float,
    negative_prompt: str,
    source_text: str,
    llm: Any | None,
) -> tuple[str, ScenePromptResult | None, str | None]:
    try:
        result = call_prompt_composer(
            scene, shots, entities_by_id,
            style_contract=style_contract,
            max_segment_duration=max_seg_dur,
            negative_prompt=negative_prompt,
            source_text=source_text,
            llm=llm,
        )
        return (scene.id, result, None)
    except Exception as exc:
        return (scene.id, None, str(exc))


def run_s6(
    work_id: str,
    target_episode_idx: int | None = None,
    *,
    llm: Any | None = None,
    max_workers: int = DEFAULT_WORKERS,
    on_scene_progress: Any | None = None,
    resume: bool = True,
    limit: int | None = None,
    reset: bool = False,
    scene_start: int | None = None,
    scene_end: int | None = None,
) -> S6Result:
    """执行 S6 视频提示词管线。

    Args:
        work_id: 作品 ID
        target_episode_idx: 仅处理某一集（None = 全集）
        llm: mock LLM（测试用）
        max_workers: 集内并发 scene 数量
        on_scene_progress: 进度回调 (done, total, scene_id)
        resume: 断点续跑
    """
    episodes = store.load_episodes(work_id)
    if not episodes:
        raise RuntimeError("no episodes found; run S1 first")

    if target_episode_idx is not None:
        episodes = [ep for ep in episodes if ep.idx == target_episode_idx]
        if not episodes:
            raise RuntimeError(f"episode {target_episode_idx} not found")

    episodes = _filter_episodes_by_scene_range(episodes, scene_start, scene_end)
    if not sum(len(ep.scenes) for ep in episodes):
        raise RuntimeError("no scenes found after applying scene range")

    entities = store.load_entities(work_id)
    entities_by_id: dict[str, Entity] = {e.id: e for e in entities}

    style_contract, max_seg_dur = get_video_prompt_config()
    source = store.get_source_text(work_id)

    # 加载 negative_prompt（直接拼接到每张卡片末尾，不经过 LLM）
    from manga_manager.models import StyleGuide
    _sg = store.read_model(store.work_dir(work_id) / "style_guide.json", StyleGuide)
    negative_prompt: str = _sg.negative_prompt or ""
    root = store.work_dir(work_id)

    # 已完成场景（扫磁盘 + cursor）
    done_ids: set[str] = set()
    if resume and not reset:
        vp_dir = root / "video_prompts"
        if vp_dir.exists():
            for p in vp_dir.glob("*.txt"):
                done_ids.add(p.stem)
        rs = store.read_model(root / "run_state.json", RunState)
        done_ids.update(rs.cursor.get("done_video_prompt_scenes") or [])

    stats = S6Stats(total_scenes=sum(len(ep.scenes) for ep in episodes))
    all_results: list[ScenePromptResult] = []
    scenes_skipped = 0
    scenes_generated = 0

    for ep in sorted(episodes, key=lambda e: e.idx):
        pending = [s for s in ep.scenes if not (resume and s.id in done_ids)]
        if limit is not None:
            remaining = limit - scenes_generated
            if remaining <= 0:
                break
            pending = pending[:remaining]

        if resume:
            skipped = [s for s in ep.scenes if s.id in done_ids]
            scenes_skipped += len(skipped)
            stats.scenes_processed += len(skipped)

        if not pending:
            continue

        # 准备 shots 数据
        shots_map: dict[str, list[Shot]] = {}
        for scene in pending:
            shots_path = root / "shots" / f"{scene.id}.json"
            if shots_path.exists():
                raw = json.loads(shots_path.read_text(encoding="utf-8"))
                shots_map[scene.id] = [Shot.model_validate(s) for s in raw]
            else:
                shots_map[scene.id] = []

        # 批量并发处理
        for batch_start in range(0, len(pending), max_workers):
            batch = pending[batch_start:batch_start + max_workers]

            if max_workers <= 1 or len(batch) == 1:
                batch_results = [
                    _call_one(s, shots_map[s.id], entities_by_id,
                              style_contract, max_seg_dur, negative_prompt,
                              source, llm)
                    for s in batch
                ]
            else:
                with ThreadPoolExecutor(max_workers=len(batch)) as ex:
                    fut_map = {
                        ex.submit(_call_one, s, shots_map[s.id], entities_by_id,
                                  style_contract, max_seg_dur, negative_prompt,
                                  source, llm): s
                        for s in batch
                    }
                    done_map: dict[str, Any] = {}
                    for f in as_completed(fut_map):
                        done_map[fut_map[f].id] = f.result()
                batch_results = [done_map[s.id] for s in batch]

            for scene_id, result, error in batch_results:
                if error:
                    stats.errors.append((scene_id, error))
                    # 失败场景不写入游标，下次 resume 可重试
                else:
                    save_scene_prompt(work_id, scene_id, result.prompt_text)
                    all_results.append(result)
                    stats.total_segments += result.segment_count
                    scenes_generated += 1
                    done_ids.add(scene_id)

                stats.scenes_processed += 1
                if on_scene_progress:
                    on_scene_progress(stats.scenes_processed, stats.total_scenes, scene_id)

        # 每集 checkpoint
        _checkpoint(work_id, done_ids)

    # 最终写 run_state
    rs = store.read_model(root / "run_state.json", RunState)
    rs.stage = "M6"
    rs.status = ArtifactStatus.validated
    rs.cursor["done_video_prompt_scenes"] = sorted(done_ids)
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)

    store.log_operation(
        work_id, "s6.built",
        detail=f"{stats.scenes_processed} scenes, {stats.total_segments} segments, errors={len(stats.errors)}",
    )

    return S6Result(results=all_results, stats=stats, scenes_skipped=scenes_skipped)


def _checkpoint(work_id: str, done_ids: set[str]) -> None:
    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", RunState)
    rs.cursor["done_video_prompt_scenes"] = sorted(done_ids)
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)
