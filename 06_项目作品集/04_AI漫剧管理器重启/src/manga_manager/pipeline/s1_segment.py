"""S1 切分管线：编排 Segmenter 调用、L1 校验、store 写入。

L1 校验规则（确定性，无 LLM）：
  1. 集 span 合法：start >= 0, end <= len(source), end > start
  2. 集覆盖全文：episodes[0].start == 0, episodes[-1].end == len(source)，
     相邻 episodes 无间隙无重叠
  3. 场景 span：scene.start >= ep.start, scene.end <= ep.end
  4. 场景覆盖全集：相邻 scenes 无间隙无重叠（第一场景从集 start 开始，最后到集 end）
  5. 每集至少 1 个场景
  6. idx 连续且有序（集/场景均是）

设计原则：本模块只做校验与编排，不直接调 LLM（由 segmenter 做）。
"""

from __future__ import annotations

from typing import Any

from manga_manager.agents.segmenter import SegmenterError, segment_source
from manga_manager.models import Episode, ValidationIssue, ValidationReport
from manga_manager import store


# ---------------------------------------------------------------------------
# L1 确定性校验
# ---------------------------------------------------------------------------


def validate_segmentation(source: str, episodes: list[Episode]) -> ValidationReport:
    """对切分结果做确定性 L1 校验，返回 ValidationReport。

    work_id 留空，校验结果不写磁盘。
    """
    issues: list[ValidationIssue] = []
    src_len = len(source)

    if not episodes:
        issues.append(ValidationIssue(path="episodes", message="episodes list is empty"))
        return ValidationReport(work_id="", ok=False, issues=issues)

    # ── 集级校验 ──────────────────────────────────────────────────────────
    # idx 连续有序
    for i, ep in enumerate(episodes):
        if ep.idx != i:
            issues.append(
                ValidationIssue(
                    path=f"episodes[{i}].idx",
                    message=f"expected idx={i}, got {ep.idx}",
                )
            )

    # span 合法 + 覆盖
    for ep in episodes:
        if ep.raw_span is None:
            issues.append(
                ValidationIssue(path=f"episode[{ep.idx}].raw_span", message="raw_span is None")
            )
            continue
        s, e = ep.raw_span.start, ep.raw_span.end
        if s < 0 or e > src_len or s >= e:
            issues.append(
                ValidationIssue(
                    path=f"episode[{ep.idx}].raw_span",
                    message=f"invalid span [{s}, {e}) for source len={src_len}",
                )
            )

    valid_eps = [ep for ep in episodes if ep.raw_span is not None]
    if valid_eps:
        if valid_eps[0].raw_span.start != 0:
            issues.append(
                ValidationIssue(
                    path="episodes[0].raw_span.start",
                    message=f"first episode must start at 0, got {valid_eps[0].raw_span.start}",
                )
            )
        if valid_eps[-1].raw_span.end != src_len:
            issues.append(
                ValidationIssue(
                    path=f"episodes[-1].raw_span.end",
                    message=f"last episode must end at {src_len}, got {valid_eps[-1].raw_span.end}",
                )
            )
        for i in range(len(valid_eps) - 1):
            cur_end = valid_eps[i].raw_span.end
            nxt_start = valid_eps[i + 1].raw_span.start
            if cur_end != nxt_start:
                issues.append(
                    ValidationIssue(
                        path=f"episodes[{i}→{i+1}]",
                        message=(
                            f"gap or overlap between episode {i} (end={cur_end}) "
                            f"and episode {i+1} (start={nxt_start})"
                        ),
                    )
                )

    # ── 场景级校验 ────────────────────────────────────────────────────────
    for ep in episodes:
        if ep.raw_span is None:
            continue
        ep_s, ep_e = ep.raw_span.start, ep.raw_span.end

        if not ep.scenes:
            issues.append(
                ValidationIssue(
                    path=f"episode[{ep.idx}].scenes",
                    message=f"episode {ep.idx} has no scenes",
                )
            )
            continue

        # scene idx 连续有序
        for j, sc in enumerate(ep.scenes):
            if sc.idx != j:
                issues.append(
                    ValidationIssue(
                        path=f"episode[{ep.idx}].scenes[{j}].idx",
                        message=f"expected idx={j}, got {sc.idx}",
                    )
                )

        # scene span 合法 + 覆盖全集
        for sc in ep.scenes:
            s, e = sc.raw_span.start, sc.raw_span.end
            if s < ep_s or e > ep_e or s >= e:
                issues.append(
                    ValidationIssue(
                        path=f"episode[{ep.idx}].scene[{sc.idx}].raw_span",
                        message=(
                            f"scene span [{s},{e}) outside episode [{ep_s},{ep_e})"
                        ),
                    )
                )

        valid_scenes = ep.scenes  # 假设 raw_span 始终有值（Scene schema 强制）
        if valid_scenes[0].raw_span.start != ep_s:
            issues.append(
                ValidationIssue(
                    path=f"episode[{ep.idx}].scenes[0].raw_span.start",
                    message=(
                        f"first scene must start at {ep_s}, got {valid_scenes[0].raw_span.start}"
                    ),
                )
            )
        if valid_scenes[-1].raw_span.end != ep_e:
            issues.append(
                ValidationIssue(
                    path=f"episode[{ep.idx}].scenes[-1].raw_span.end",
                    message=(
                        f"last scene must end at {ep_e}, got {valid_scenes[-1].raw_span.end}"
                    ),
                )
            )
        for j in range(len(valid_scenes) - 1):
            cur_end = valid_scenes[j].raw_span.end
            nxt_start = valid_scenes[j + 1].raw_span.start
            if cur_end != nxt_start:
                issues.append(
                    ValidationIssue(
                        path=f"episode[{ep.idx}].scenes[{j}→{j+1}]",
                        message=(
                            f"gap/overlap: scene {j} end={cur_end}, scene {j+1} start={nxt_start}"
                        ),
                    )
                )

    return ValidationReport(work_id="", ok=not issues, issues=issues)


# ---------------------------------------------------------------------------
# 管线编排：run_s1
# ---------------------------------------------------------------------------


class S1Result:
    """S1 管线运行结果。"""

    def __init__(
        self,
        episodes: list[Episode],
        report: ValidationReport,
        source_len: int,
    ) -> None:
        self.episodes = episodes
        self.report = report
        self.source_len = source_len

    @property
    def ok(self) -> bool:
        return self.report.ok

    def summary_lines(self) -> list[str]:
        """生成人类可读的摘要（用于 CLI 预览）。"""
        lines = [
            f"原文总长: {self.source_len} 字",
            f"集数: {len(self.episodes)}",
            f"场景总数: {sum(len(ep.scenes) for ep in self.episodes)}",
        ]
        for ep in self.episodes:
            ep_chars = (ep.raw_span.end - ep.raw_span.start) if ep.raw_span else 0
            lines.append(
                f"  [{ep.idx:02d}] {ep.title!r}  {ep_chars} 字  {len(ep.scenes)} 场"
            )
            for sc in ep.scenes:
                sc_chars = sc.raw_span.end - sc.raw_span.start
                loc = f"{sc.time}/{sc.location}" if sc.time or sc.location else "—"
                lines.append(
                    f"       场景{sc.idx:02d} [{loc}] {sc.summary[:30]!r}  {sc_chars} 字"
                )
        return lines


def run_s1(
    work_id: str,
    *,
    target_episodes: int = 12,
    llm: Any | None = None,
) -> S1Result:
    """运行 S1 切分管线（不写磁盘，供 CLI 人工检查点前调用）。

    流程：
      1. 读 source.txt
      2. 调用 segmenter.segment_source（LLM → anchor → Python 切分）
      3. L1 确定性校验
      4. 返回 S1Result（episodes, report, source_len）

    调用方在人工确认后调用 store.save_episodes()。
    """
    source = store.get_source_text(work_id)
    episodes = segment_source(source, work_id=work_id, target_episodes=target_episodes, llm=llm)
    report = validate_segmentation(source, episodes)
    return S1Result(episodes=episodes, report=report, source_len=len(source))
