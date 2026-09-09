"""S3 滚动摘要管线。

设计要点：
  - 按集顺序处理（rolling_summary 依赖上一集结果，不能并行）。
  - 每集完成即 checkpoint 写到 summaries/{idx:04d}.json。
  - 断点续跑：跳过已存在的 summary 文件（按 episode_idx）。
  - LLM 调用失败时记 error 但不中断其他集；run_state 记录 done_episodes。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from manga_manager.agents.summarizer import (
    SummarizerError,
    call_summarizer,
    format_scene_text,
)
from manga_manager.models import (
    ArtifactStatus,
    RunState,
    Summary,
)
from manga_manager import store


@dataclass
class S3Stats:
    total_episodes: int = 0
    episodes_processed: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)
    final_token_estimate: int = 0


@dataclass
class S3Result:
    summaries: list[Summary]
    stats: S3Stats
    episodes_skipped: int = 0

    @property
    def ok(self) -> bool:
        return not self.stats.errors

    def summary_lines(self) -> list[str]:
        return [
            f"处理集数: {self.stats.episodes_processed}/{self.stats.total_episodes}"
            + (f" (跳过了 {self.episodes_skipped} 个已处理集)" if self.episodes_skipped else ""),
            f"错误: {len(self.stats.errors)}",
            f"最终 rolling_summary token 估算: ~{self.stats.final_token_estimate}",
        ]


def run_s3(
    work_id: str,
    *,
    llm: Any | None = None,
    on_episode_progress: Any | None = None,
    resume: bool = True,
) -> S3Result:
    """执行 S3 滚动摘要。

    Args:
        work_id: 作品 ID
        llm: 可选 LLM 实例（测试用 mock）
        on_episode_progress: 回调 (done, total, episode_idx)
        resume: 是否跳过已处理集

    Returns:
        S3Result
    """
    source = store.get_source_text(work_id)
    episodes = store.load_episodes(work_id)
    if not episodes:
        raise SummarizerError("no episodes found; run S1 first")

    sorted_episodes = sorted(episodes, key=lambda ep: ep.idx)
    total = len(sorted_episodes)
    stats = S3Stats(total_episodes=total)
    summaries: list[Summary] = store.load_summaries(work_id)

    done_episode_idxs: set[int] = {s.episode_idx for s in summaries}
    skipped = 0

    for ep in sorted_episodes:
        if resume and ep.idx in done_episode_idxs:
            skipped += 1
            stats.episodes_processed += 1
            if on_episode_progress:
                on_episode_progress(stats.episodes_processed, total, ep.idx)
            continue

        scenes_text = format_scene_text(ep.scenes, source)
        previous_rolling, _ = store.load_rolling_summary(work_id, ep.idx - 1)

        try:
            raw_result, token_est = _call_summarizer_safe(
                ep, scenes_text, previous_rolling, llm
            )
            summary = Summary(
                episode_idx=ep.idx,
                episode_summary=raw_result.episode_summary,
                rolling_summary=raw_result.rolling_summary,
                summary=raw_result.episode_summary,
                source_scene_ids=[s.id for s in ep.scenes],
                token_estimate=token_est,
                status=ArtifactStatus.validated,
            )
            store.save_summary(work_id, summary)
            summaries.append(summary)
            done_episode_idxs.add(ep.idx)
            stats.episodes_processed += 1
            stats.final_token_estimate = token_est
            _update_run_state(work_id, done_episode_idxs, "M3", "draft")

        except SummarizerError as exc:
            stats.errors.append((ep.idx, str(exc)))

        if on_episode_progress:
            on_episode_progress(stats.episodes_processed, total, ep.idx)

    _update_run_state(work_id, done_episode_idxs, "M3", ArtifactStatus.validated)
    store.log_operation(
        work_id,
        "s3.built",
        detail=f"{stats.episodes_processed} episodes, errors={len(stats.errors)}, "
        f"final_token_estimate={stats.final_token_estimate}",
    )

    return S3Result(
        summaries=summaries,
        stats=stats,
        episodes_skipped=skipped,
    )


def _call_summarizer_safe(episode, scenes_text, previous_rolling, llm):
    from manga_manager.agents.summarizer import build_result_with_estimate

    raw = call_summarizer(
        episode,
        scenes_text,
        previous_rolling_summary=previous_rolling,
        llm=llm,
    )
    return build_result_with_estimate(raw)


def _update_run_state(
    work_id: str,
    done_episode_idxs: set[int],
    stage: str,
    status: str | ArtifactStatus,
) -> None:
    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", RunState)
    rs.stage = stage
    rs.status = ArtifactStatus(status) if isinstance(status, str) else status
    rs.cursor["done_episodes"] = sorted(done_episode_idxs)
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)
