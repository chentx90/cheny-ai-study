"""M3 S3 滚动摘要管线单元测试。

纯 Python 逻辑测试，不调用真实 LLM（用 mock LLM）。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid

import pytest

from manga_manager import store
from manga_manager.agents.summarizer import (
    SummarizerError,
    SummarizerResult,
    call_summarizer,
    format_scene_text,
)
from manga_manager.models import (
    ArtifactStatus,
    Episode,
    RawSpan,
    Scene,
    Summary,
)
from manga_manager.pipeline.s3_summary import run_s3


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="manga_m3test_")
    monkeypatch.setenv("MANGA_DATA_DIR", tmp)
    yield
    shutil.rmtree(tmp, ignore_errors=True)


def _setup_work(
    episodes_specs: list[tuple[int, list[tuple[str | int, str]]]],
) -> tuple[str, str]:
    """创建测试作品并返回 (work_id, full_source)。

    episodes_specs: [(ep_idx, scenes)]
    scenes: [(scene_id_or_idx, scene_text), ...]
    """
    meta = store.create_work("测试作品")
    work_id = meta.id
    cursor = 0
    full_parts: list[str] = []
    episodes_out: list[Episode] = []

    for ep_idx, scenes in episodes_specs:
        ep_start = cursor
        scenes_out: list[Scene] = []
        for s_idx, (sid, stext) in enumerate(scenes):
            scene_start = cursor
            scene_end = cursor + len(stext)
            scenes_out.append(
                Scene(
                    id=f"s{ep_idx:02d}{s_idx:03d}_{uuid.uuid4().hex[:4]}",
                    episode_idx=ep_idx,
                    idx=s_idx,
                    time="",
                    location="",
                    pov="",
                    summary=stext[:50],
                    raw_span=RawSpan(start=scene_start, end=scene_end),
                )
            )
            full_parts.append(stext)
            cursor = scene_end
        ep_end = cursor
        episodes_out.append(
            Episode(
                id=f"ep{ep_idx:04d}_{uuid.uuid4().hex[:4]}",
                idx=ep_idx,
                title=f"第{ep_idx + 1}集",
                raw_span=RawSpan(start=ep_start, end=ep_end),
                scenes=scenes_out,
            )
        )

    full_source = "".join(full_parts)
    root = store.work_dir(work_id)
    (root / "source.txt").write_text(full_source, encoding="utf-8")
    store.save_episodes(work_id, episodes_out)
    return work_id, full_source


# ───────────────────────────────────────────────────────────────────────────
# Summary 模型
# ───────────────────────────────────────────────────────────────────────────


def test_summary_model_with_rolling_fields():
    s = Summary(
        episode_idx=0,
        episode_summary="第1集发生了...",
        rolling_summary="故事开始，第1集...",
        source_scene_ids=["s1", "s2"],
        token_estimate=120,
        status=ArtifactStatus.validated,
    )
    assert s.episode_summary == "第1集发生了..."
    assert s.rolling_summary == "故事开始，第1集..."
    assert s.token_estimate == 120
    assert s.status == ArtifactStatus.validated


def test_summary_model_migration_from_legacy_summary():
    s = Summary.model_validate({
        "episode_idx": 2,
        "summary": "第3集旧摘要",
        "source_scene_ids": ["s1"],
    })
    assert s.episode_summary == "第3集旧摘要"
    assert s.summary == "第3集旧摘要"


def test_summary_model_defaults():
    s = Summary(episode_idx=0)
    assert s.episode_summary == ""
    assert s.rolling_summary == ""
    assert s.summary == ""
    assert s.token_estimate == 0


# ───────────────────────────────────────────────────────────────────────────
# store 层
# ───────────────────────────────────────────────────────────────────────────


def test_save_and_load_single_summary():
    work_id, _ = _setup_work([(0, [("0", "场景A")])])
    s = Summary(
        episode_idx=0,
        episode_summary="本集摘要",
        rolling_summary="滚动摘要",
        token_estimate=50,
    )
    store.save_summary(work_id, s)

    loaded = store.load_summaries(work_id)
    assert len(loaded) == 1
    assert loaded[0].episode_summary == "本集摘要"
    assert loaded[0].rolling_summary == "滚动摘要"
    assert loaded[0].token_estimate == 50


def test_save_multiple_summaries_sorted():
    work_id, _ = _setup_work([
        (0, [("0", "A")]),
        (1, [("0", "B")]),
        (2, [("0", "C")]),
    ])
    for i, rolling in enumerate(["第1集", "第1-2集", "第1-3集"]):
        store.save_summary(work_id, Summary(
            episode_idx=i,
            episode_summary=f"本集{i}",
            rolling_summary=rolling,
            token_estimate=30 + i * 10,
        ))

    loaded = store.load_summaries(work_id)
    assert len(loaded) == 3
    assert [s.episode_idx for s in loaded] == [0, 1, 2]


def test_load_rolling_summary_latest():
    work_id, _ = _setup_work([
        (0, [("0", "text0")]),
        (1, [("0", "text1")]),
        (2, [("0", "text2")]),
        (3, [("0", "text3")]),
    ])
    for i in range(4):
        store.save_summary(work_id, Summary(
            episode_idx=i,
            episode_summary=f"ep{i}",
            rolling_summary=f"rolling_through_{i}",
            token_estimate=100 + i * 20,
        ))

    text, est = store.load_rolling_summary(work_id, 2)
    assert text == "rolling_through_2"
    assert est == 140  # token_estimate=100 + 2*20 for idx=2


def test_load_rolling_summary_empty():
    work_id, _ = _setup_work([(0, [("0", "A")])])
    text, est = store.load_rolling_summary(work_id, 0)
    assert text == ""
    assert est == 0


def test_load_rolling_summary_beyond_last():
    work_id, _ = _setup_work([(0, [("0", "X")])])
    store.save_summary(work_id, Summary(episode_idx=0, episode_summary="x", rolling_summary="roll0"))
    text, est = store.load_rolling_summary(work_id, 999)
    assert text == "roll0"


# ───────────────────────────────────────────────────────────────────────────
# format_scene_text
# ───────────────────────────────────────────────────────────────────────────


def test_format_scene_text_basic():
    source = "AABBCCDD"
    scenes = [
        Scene(id="s1", episode_idx=0, idx=0, raw_span=RawSpan(start=0, end=4)),
        Scene(id="s2", episode_idx=0, idx=1, raw_span=RawSpan(start=4, end=8)),
    ]
    result = format_scene_text(scenes, source)
    assert "[场景 0" in result
    assert "AABB" in result
    assert "CCDD" in result


def test_format_scene_text_truncation():
    source = "A" * 20000
    scenes = [Scene(id="s1", episode_idx=0, idx=0, raw_span=RawSpan(start=0, end=20000))]
    result = format_scene_text(scenes, source, max_chars_per_scene=1000)
    assert "[…… 截断 ……]" in result
    assert len(result) < 12000


def test_format_scene_text_with_meta():
    source = "Hello World"
    scenes = [Scene(
        id="s1", episode_idx=0, idx=0,
        time="上午", location="阳台", pov="男主",
        raw_span=RawSpan(start=0, end=11),
    )]
    result = format_scene_text(scenes, source)
    assert "time=上午" in result
    assert "location=阳台" in result
    assert "pov=男主" in result


# ───────────────────────────────────────────────────────────────────────────
# call_summarizer（mock LLM）
# ───────────────────────────────────────────────────────────────────────────


class _MockResp:
    def __init__(self, content: str):
        self.content = content


class _MockLLM:
    """返回固定 JSON 响应的 mock LLM。"""
    def __init__(self, response_data: dict):
        self._data = response_data
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return _MockResp(json.dumps(self._data))


def test_call_summarizer_basic():
    ep = Episode(id="ep0001_test", idx=0, title="第1集")
    llm = _MockLLM({
        "episode_summary": "这是第1集摘要",
        "rolling_summary": "这是第1集滚动摘要",
    })
    result = call_summarizer(ep, "场景文本", llm=llm)
    assert result.episode_summary == "这是第1集摘要"
    assert result.rolling_summary == "这是第1集滚动摘要"


def test_call_summarizer_includes_previous_rolling():
    ep = Episode(id="ep0002_test", idx=1, title="第2集")
    llm = _MockLLM({
        "episode_summary": "本集摘要",
        "rolling_summary": "合并后的滚动摘要",
    })
    call_summarizer(ep, "文本", previous_rolling_summary="之前的故事", llm=llm)
    assert "之前的故事" in llm.last_messages[1].content


def test_call_summarizer_parse_error():
    ep = Episode(id="ep0001_test", idx=0, title="第1集")

    class _BadLLM:
        def invoke(self, messages):
            return _MockResp("NOT_VALID_JSON{{{{")

    with pytest.raises(Exception):
        call_summarizer(ep, "文本", llm=_BadLLM())


# ───────────────────────────────────────────────────────────────────────────
# run_s3 管线集成（mock LLM）
# ───────────────────────────────────────────────────────────────────────────


def _make_pipeline_llm():
    """根据 episodes_text 里的集号生成摘要的 mock LLM。"""

    class PipelineLLM:
        def __init__(self):
            self.call_count = 0

        def invoke(self, messages):
            self.call_count += 1
            user_msg = messages[1].content
            episode_idx = 0
            for line in user_msg.split("\n"):
                line = line.strip()
                if line.startswith("第 ") and " 集：" in line:
                    try:
                        episode_idx = int(line.split("第 ")[1].split(" 集：")[0])
                    except (ValueError, IndexError):
                        pass
                    break

            ep_summary = f"第{episode_idx+1}集摘要内容"
            rolling = f"滚动摘要截至第{episode_idx+1}集，包含前面所有剧情要点。"
            return _MockResp(json.dumps({
                "episode_summary": ep_summary,
                "rolling_summary": rolling,
            }))

    return PipelineLLM()


def test_run_s3_basic_flow():
    work_id, _ = _setup_work([
        (0, [("0", "场景A文本。" * 20)]),
        (1, [("0", "场景B文本。" * 20)]),
        (2, [("0", "场景C文本。" * 20)]),
    ])

    mock_llm = _make_pipeline_llm()
    result = run_s3(work_id, llm=mock_llm)

    assert result.ok
    assert len(result.summaries) == 3
    assert result.stats.episodes_processed == 3
    assert result.episodes_skipped == 0

    for s in result.summaries:
        assert s.episode_summary != ""
        assert s.rolling_summary != ""
        assert s.token_estimate > 0
        assert s.status == ArtifactStatus.validated


def test_run_s3_resume_skips_done():
    work_id, _ = _setup_work([
        (0, [("0", "A" * 50)]),
        (1, [("0", "B" * 50)]),
        (2, [("0", "C" * 50)]),
    ])

    store.save_summary(work_id, Summary(
        episode_idx=0, episode_summary="ep0", rolling_summary="roll0", token_estimate=10,
    ))
    store.save_summary(work_id, Summary(
        episode_idx=1, episode_summary="ep1", rolling_summary="roll1", token_estimate=20,
    ))

    mock_llm = _make_pipeline_llm()
    result = run_s3(work_id, llm=mock_llm, resume=True)

    assert result.ok
    assert result.episodes_skipped == 2
    assert len(result.summaries) == 3
    assert mock_llm.call_count == 1


def test_run_s3_progress_callback():
    work_id, _ = _setup_work([
        (0, [("0", "A" * 50)]),
        (1, [("0", "B" * 50)]),
    ])
    mock_llm = _make_pipeline_llm()

    progress_log = []

    def cb(done, total, ep_idx):
        progress_log.append((done, total, ep_idx))

    result = run_s3(work_id, llm=mock_llm, on_episode_progress=cb)
    assert result.ok
    assert len(progress_log) == 2


def test_run_s3_handles_llm_error():
    work_id, _ = _setup_work([
        (0, [("0", "A" * 50)]),
        (1, [("0", "B" * 50)]),
    ])

    call_count = [0]

    class FlakeyLLM:
        def invoke(self, messages):
            call_count[0] += 1
            if call_count[0] == 1:
                return _MockResp("INVALID_JSON{{")
            return _MockResp(json.dumps({
                "episode_summary": "ok",
                "rolling_summary": "ok rolling",
            }))

    result = run_s3(work_id, llm=FlakeyLLM())
    assert not result.ok
    assert len(result.stats.errors) == 1
    assert result.stats.errors[0][0] == 0


def test_run_s3_no_episodes():
    meta = store.create_work("空作品")
    work_id = meta.id
    root = store.work_dir(work_id)
    (root / "source.txt").write_text("empty", encoding="utf-8")

    with pytest.raises(Exception, match="no episodes found"):
        run_s3(work_id)


def test_run_s3_update_run_state():
    work_id, _ = _setup_work([(0, [("0", "A" * 50)])])
    mock_llm = _make_pipeline_llm()
    result = run_s3(work_id, llm=mock_llm)

    root = store.work_dir(work_id)
    rs = store.read_model(root / "run_state.json", store.RunState)
    assert rs.stage == "M3"
    assert rs.status == ArtifactStatus.validated
    assert 0 in rs.cursor.get("done_episodes", [])


def test_run_s3_operation_logged():
    work_id, _ = _setup_work([(0, [("0", "A" * 50)])])
    mock_llm = _make_pipeline_llm()
    run_s3(work_id, llm=mock_llm)

    ops = store.load_operations(work_id, limit=5)
    assert any(o.command == "s3.built" for o in ops)


# ───────────────────────────────────────────────────────────────────────────
# S3Result 辅助方法
# ───────────────────────────────────────────────────────────────────────────


def test_s3result_summary_lines():
    from manga_manager.pipeline.s3_summary import S3Result, S3Stats

    result = S3Result(
        summaries=[],
        stats=S3Stats(total_episodes=5, episodes_processed=3, final_token_estimate=250),
        episodes_skipped=2,
    )
    lines = result.summary_lines()
    assert any("处理集数" in l for l in lines)
    assert any("跳过了 2" in l for l in lines)
    assert any("250" in l for l in lines)


# ───────────────────────────────────────────────────────────────────────────
# 文件格式验证
# ───────────────────────────────────────────────────────────────────────────


def test_summary_file_on_disk():
    work_id, _ = _setup_work([(0, [("0", "text")])])
    s = Summary(
        episode_idx=0,
        episode_summary="本集",
        rolling_summary="滚动",
        token_estimate=30,
    )
    store.save_summary(work_id, s)

    path = store.work_dir(work_id) / "summaries" / "0000.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["episode_idx"] == 0
    assert data["episode_summary"] == "本集"
    assert data["rolling_summary"] == "滚动"
    assert data["token_estimate"] == 30
