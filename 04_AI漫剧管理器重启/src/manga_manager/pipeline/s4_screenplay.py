"""S4 编剧管线。

设计要点：
  - 集内场景可并行调 LLM（ThreadPoolExecutor），shots 按场景保存。
  - 每个场景的 shots 写入 shots/{scene_id}.json。
  - 断点续跑：跳过已有 shots 文件的场景。
  - LLM 调用失败不中断其他场景，记 error 并继续。
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from manga_manager.agents.screenwriter import (
    ScreenwriterError,
    call_screenwriter,
)
from manga_manager.models import (
    ArtifactStatus,
    Entity,
    Episode,
    RunState,
    Scene,
    Shot,
    StyleGuide,
)
from manga_manager import store


DEFAULT_WORKERS = 4


@dataclass
class S4Stats:
    total_scenes: int = 0
    scenes_processed: int = 0
    shots_created: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    final_shot_count: int = 0


@dataclass
class S4Result:
    shots: list[Shot]
    stats: S4Stats
    scenes_skipped: int = 0

    @property
    def ok(self) -> bool:
        return not [e for e, _ in self.stats.errors]

    def summary_lines(self) -> list[str]:
        return [
            f"处理场景: {self.stats.scenes_processed}/{self.stats.total_scenes}"
            + (f" (跳过了 {self.scenes_skipped} 个已处理)" if self.scenes_skipped else ""),
            f"生成镜头: {self.stats.shots_created}",
            f"错误: {len(self.stats.errors)}",
            f"最终镜头总数: {self.stats.final_shot_count}",
        ]


def _get_style_guide_text(work_id: str) -> str:
    try:
        style = store.read_model(
            store.work_dir(work_id) / "style_guide.json", StyleGuide
        )
        return style.narrative_style
    except Exception:
        return ""


def _get_relevant_entities(
    work_id: str, scene: Scene
) -> list[Entity]:
    """取场景关联的实体。"""
    index = store.read_model(store.work_dir(work_id) / "index.json", store.WorkIndex)
    entity_ids = set(index.scene_to_entities.get(scene.id, []))

    if not entity_ids:
        return []

    all_entities = store.load_entities(work_id)
    return [e for e in all_entities if e.id in entity_ids]


def _call_scene_llm(
    scene: Scene,
    source: str,
    work_id: str,
    rolling_summary: str,
    style_text: str,
    llm: Any | None,
) -> tuple[str, list[Shot] | None, str | None]:
    scene_text = source[scene.raw_span.start:scene.raw_span.end]
    entities = _get_relevant_entities(work_id, scene)

    try:
        result = call_screenwriter(
            scene_text,
            scene_idx=scene.idx,
            scene_id=scene.id,
            time=scene.time,
            location=scene.location,
            pov=scene.pov,
            relevant_entities=entities,
            rolling_summary=rolling_summary,
            style_guide=style_text,
            llm=llm,
        )

        shots: list[Shot] = []
        for i, es in enumerate(result.shots):
            shots.append(Shot(
                id=f"sh{uuid.uuid4().hex[:10]}",
                scene_id=scene.id,
                idx=i,
                shot_type=es.shot_type,
                action=es.action,
                emotion=es.emotion,
                dialogue=es.dialogue,
                duration=es.duration,
                characters=list(es.characters),
                status=ArtifactStatus.validated,
            ))
        return (scene.id, shots, None)
    except ScreenwriterError as exc:
        return (scene.id, None, str(exc))
    except Exception as exc:
        return (scene.id, None, str(exc))


def save_scene_shots(work_id: str, scene_id: str, shots: list[Shot]) -> None:
    """保存场景的 shots 到 shots/{scene_id}.json。"""
    root = store.work_dir(work_id)
    shots_dir = root / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(shots_dir / f"{scene_id}.json", shots)


def run_s4(
    work_id: str,
    *,
    llm: Any | None = None,
    max_workers: int = DEFAULT_WORKERS,
    on_scene_progress: Any | None = None,
    resume: bool = True,
) -> S4Result:
    """执行 S4 编剧管线。

    Args:
        work_id: 作品 ID
        llm: 可选 LLM mock
        max_workers: 集内并发数
        on_scene_progress: 进度回调
        resume: 断点续跑

    Returns:
        S4Result
    """
    source = store.get_source_text(work_id)
    episodes = store.load_episodes(work_id)
    if not episodes:
        raise ScreenwriterError("no episodes found; run S1 first")

    rolling_summary, _ = store.load_rolling_summary(
        work_id, max(ep.idx for ep in episodes)
    )
    style_text = _get_style_guide_text(work_id)

    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", RunState)
    done_scene_ids: set[str] = set(rs.cursor.get("done_screenplay_scenes") or [])

    shots_dir = root / "shots"
    if resume:
        for p in shots_dir.glob("*.json"):
            scene_id = p.stem
            if scene_id not in done_scene_ids:
                done_scene_ids.add(scene_id)

    stats = S4Stats(total_scenes=sum(len(ep.scenes) for ep in episodes))
    all_shots: list[Shot] = store.load_shots(work_id)
    scenes_skipped = 0

    sorted_eps = sorted(episodes, key=lambda e: e.idx)

    for ep in sorted_eps:
        pending = [s for s in ep.scenes if not (resume and s.id in done_scene_ids)]

        if resume:
            skipped_this_ep = sum(1 for s in ep.scenes if s.id in done_scene_ids)
            scenes_skipped += skipped_this_ep
            stats.scenes_processed += skipped_this_ep

        if not pending:
            continue

        for batch_start in range(0, len(pending), max_workers):
            batch = pending[batch_start:batch_start + max_workers]

            if max_workers <= 1 or len(batch) == 1:
                batch_results = [
                    _call_scene_llm(scene, source, work_id, rolling_summary, style_text, llm)
                    for scene in batch
                ]
            else:
                with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                    future_to_scene = {
                        executor.submit(
                            _call_scene_llm, scene, source, work_id,
                            rolling_summary, style_text, llm
                        ): scene
                        for scene in batch
                    }
                    done_map: dict[str, tuple[str, list[Shot] | None, str | None]] = {}
                    for f in as_completed(future_to_scene):
                        done_map[future_to_scene[f].id] = f.result()
                batch_results = [done_map[scene.id] for scene in batch]

            for scene_id, shots, error in batch_results:
                scene = next(s for s in batch if s.id == scene_id)
                if error:
                    stats.errors.append((scene_id, error))
                    # 失败场景不写入游标，下次 resume 可重试
                else:
                    save_scene_shots(work_id, scene_id, shots)
                    all_shots.extend(shots)
                    stats.shots_created += len(shots)
                    done_scene_ids.add(scene_id)

                stats.scenes_processed += 1
                if on_scene_progress:
                    on_scene_progress(stats.scenes_processed, stats.total_scenes, scene_id)

            _checkpoint(work_id, done_scene_ids, stats)

    rs.stage = "M4"
    rs.status = ArtifactStatus.validated
    rs.cursor["done_screenplay_scenes"] = sorted(done_scene_ids)
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)

    stats.final_shot_count = len(all_shots)

    store.log_operation(
        work_id,
        "s4.built",
        detail=(
            f"{stats.shots_created} shots created from "
            f"{stats.scenes_processed} scenes, errors={len(stats.errors)}"
        ),
    )

    return S4Result(
        shots=all_shots,
        stats=stats,
        scenes_skipped=scenes_skipped,
    )


def _checkpoint(work_id: str, done_scene_ids: set[str], stats: S4Stats) -> None:
    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", RunState)
    rs.cursor["done_screenplay_scenes"] = sorted(done_scene_ids)
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)
