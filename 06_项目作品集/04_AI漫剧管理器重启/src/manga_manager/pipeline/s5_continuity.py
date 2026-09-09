"""S5 Continuity/绑定管线。

设计要点：
  - 纯确定性流程，无 LLM 调用
  - 逐场景处理：读 shots/{scene_id}.json → 绑定 → 写回 → 写 bindings/{scene_id}.json
  - 每批处理完即 checkpoint 到 run_state.cursor["done_binding_scenes"]
  - 断点续跑：跳过已有 bindings/{scene_id}.json 的场景
  - 最后收集跨场景一致性 issues
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from manga_manager.agents.continuity import (
    ContinueResult,
    bind_scene,
    check_cross_scene_consistency,
)
from manga_manager.models import (
    ArtifactStatus,
    Entity,
    RunState,
    Scene,
    Shot,
    WorkIndex,
)
from manga_manager import store


@dataclass
class S5Stats:
    total_scenes: int = 0
    scenes_processed: int = 0
    total_bindings: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    consistency_issues: list[str] = field(default_factory=list)
    final_binding_scenes: int = 0


@dataclass
class S5Result:
    all_bindings: list[ContinueResult]
    stats: S5Stats
    scenes_skipped: int = 0

    @property
    def ok(self) -> bool:
        return not [e for e, _ in self.stats.errors]

    def summary_lines(self) -> list[str]:
        return [
            f"处理场景: {self.stats.scenes_processed}/{self.stats.total_scenes}"
            + (f" (跳过了 {self.scenes_skipped} 个已处理)" if self.scenes_skipped else ""),
            f"绑定镜头: {self.stats.total_bindings}",
            f"解析失败: {len(self.stats.errors)}",
            f"一致性 issues: {len(self.stats.consistency_issues)}",
        ]


def save_scene_binding(work_id: str, result: ContinueResult) -> None:
    """保存场景的绑定到 bindings/{scene_id}.json。"""
    from manga_manager.models import BindingFile
    binding_file = BindingFile(
        scene_id=result.scene_id,
        bindings=result.bindings,
        issues=result.issues,
    )
    root = store.work_dir(work_id)
    bindings_dir = root / "bindings"
    bindings_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(
        bindings_dir / f"{result.scene_id}.json", binding_file
    )


def save_updated_shots(work_id: str, scene_id: str, shots: list[Shot]) -> None:
    """把更新后的 shots 写回 shots/{scene_id}.json。"""
    root = store.work_dir(work_id)
    shots_dir = root / "shots"
    store.write_json_atomic(shots_dir / f"{scene_id}.json", shots)


def run_s5(
    work_id: str,
    *,
    on_scene_progress: Any | None = None,
    resume: bool = True,
) -> S5Result:
    """执行 S5 角色绑定管线。

    Args:
        work_id: 作品 ID
        on_scene_progress: 进度回调 (done, total, scene_id)
        resume: 断点续跑

    Returns:
        S5Result
    """
    episodes = store.load_episodes(work_id)
    if not episodes:
        raise RuntimeError("no episodes found; run S1 first")

    entities = store.load_entities(work_id)
    index = store.read_model(store.work_dir(work_id) / "index.json", WorkIndex)

    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", RunState)
    done_scene_ids: set[str] = set(rs.cursor.get("done_binding_scenes") or [])

    # 扫描已有 bindings 做兜底
    if resume:
        bindings_dir = root / "bindings"
        if bindings_dir.exists():
            for p in bindings_dir.glob("*.json"):
                scene_id = p.stem
                if scene_id not in done_scene_ids:
                    done_scene_ids.add(scene_id)

    stats = S5Stats(total_scenes=sum(len(ep.scenes) for ep in episodes))
    all_bindings: list[ContinueResult] = []
    scenes_skipped = 0

    for ep in sorted(episodes, key=lambda e: e.idx):
        for scene in ep.scenes:
            if resume and scene.id in done_scene_ids:
                scenes_skipped += 1
                stats.scenes_processed += 1
                if on_scene_progress:
                    on_scene_progress(stats.scenes_processed, stats.total_scenes, scene.id)
                continue

            shots_path = root / "shots" / f"{scene.id}.json"
            if not shots_path.exists():
                stats.errors.append((scene.id, "shots 文件不存在，S4 未完成"))
                stats.scenes_processed += 1
                continue

            try:
                shots_data = store.read_json(shots_path, [])
                shots = [Shot.model_validate(s) for s in shots_data]
            except Exception as exc:
                stats.errors.append((scene.id, f"shots 解析失败: {exc}"))
                stats.scenes_processed += 1
                continue

            try:
                result = bind_scene(scene, shots, entities, index)
                save_scene_binding(work_id, result)
                save_updated_shots(work_id, scene.id, result.updated_shots)
                all_bindings.append(result)

                stats.total_bindings += len(result.bindings)
                stats.scenes_processed += 1
                done_scene_ids.add(scene.id)

                # 定期 checkpoint
                if stats.scenes_processed % 10 == 0:
                    _checkpoint(work_id, done_scene_ids, stats)

            except Exception as exc:
                stats.errors.append((scene.id, f"绑定失败: {exc}"))
                stats.scenes_processed += 1

            if on_scene_progress:
                on_scene_progress(stats.scenes_processed, stats.total_scenes, scene.id)

    # 跨场景一致性检查
    stats.consistency_issues = check_cross_scene_consistency(all_bindings)

    stats.final_binding_scenes = len(all_bindings)

    _update_run_state(work_id, done_scene_ids, "M5", ArtifactStatus.validated)
    store.log_operation(
        work_id,
        "s5.built",
        detail=(
            f"{stats.total_bindings} bindings from {stats.scenes_processed} scenes, "
            f"errors={len(stats.errors)}, issues={len(stats.consistency_issues)}"
        ),
    )

    return S5Result(
        all_bindings=all_bindings,
        stats=stats,
        scenes_skipped=scenes_skipped,
    )


def _checkpoint(work_id: str, done_scene_ids: set[str], stats: S5Stats) -> None:
    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", RunState)
    rs.cursor["done_binding_scenes"] = sorted(done_scene_ids)
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)


def _update_run_state(
    work_id: str, done_scene_ids: set[str], stage: str, status: Any
) -> None:
    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", RunState)
    rs.stage = stage
    rs.status = ArtifactStatus(status) if isinstance(status, str) else status
    rs.cursor["done_binding_scenes"] = sorted(done_scene_ids)
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)
