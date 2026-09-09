"""M4 编剧管线单测。"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid

import pytest

from manga_manager import store
from manga_manager.agents.screenwriter import (
    ScreenwriterAgent,
    ScreenwriterError,
    ScreenwritingCritique,
    ScreenwritingResult,
    ExtractedShot,
    VALID_SHOT_TYPES,
    call_screenwriter,
    format_scene_meta,
    format_relevant_entities,
)
from manga_manager.models import (
    ArtifactStatus,
    Entity,
    EntityAttr,
    EntityVariant,
    Episode,
    RawSpan,
    Scene,
    Shot,
    Summary,
)
from manga_manager.pipeline.s4_screenplay import (
    run_s4,
    save_scene_shots,
    S4Stats,
    S4Result,
)


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="manga_m4test_")
    monkeypatch.setenv("MANGA_DATA_DIR", tmp)
    yield
    shutil.rmtree(tmp, ignore_errors=True)


def _setup_work(
    episodes_specs: list[tuple[int, list[tuple[int, str]]]],
) -> tuple[str, str]:
    """创建测试作品，返回 (work_id, full_source)。"""
    meta = store.create_work("测试作品")
    work_id = meta.id
    cursor = 0
    full_parts: list[str] = []
    episodes_out: list[Episode] = []

    for ep_idx, scenes in episodes_specs:
        ep_start = cursor
        scenes_out: list[Scene] = []
        for s_idx, s_text in scenes:
            scene_start = cursor
            scene_end = cursor + len(s_text)
            scenes_out.append(Scene(
                id=f"s{ep_idx:02d}{s_idx:03d}_{uuid.uuid4().hex[:4]}",
                episode_idx=ep_idx, idx=s_idx,
                time="", location="", pov="", summary=s_text[:50],
                raw_span=RawSpan(start=scene_start, end=scene_end),
            ))
            full_parts.append(s_text)
            cursor = scene_end
        ep_end = cursor
        episodes_out.append(Episode(
            id=f"ep{ep_idx:04d}_{uuid.uuid4().hex[:4]}",
            idx=ep_idx, title=f"第{ep_idx+1}集",
            raw_span=RawSpan(start=ep_start, end=ep_end),
            scenes=scenes_out,
        ))

    full_source = "".join(full_parts)
    root = store.work_dir(work_id)
    (root / "source.txt").write_text(full_source, encoding="utf-8")
    store.save_episodes(work_id, episodes_out)
    ## 创建 rolling summary
    store.save_summary(work_id, Summary(
        episode_idx=episodes_out[-1].idx if episodes_out else 0,
        episode_summary="test", rolling_summary="前情提要",
    ))
    return work_id, full_source


class _MockResp:
    def __init__(self, content: str):
        self.content = content


class _MockLLM:
    """返回固定 JSON 的 mock LLM。"""
    def __init__(self, responses: list[dict] | None = None):
        self._responses = responses or []
        self._calls = 0
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        if self._calls < len(self._responses):
            resp = self._responses[self._calls]
        else:
            resp = self._responses[-1] if self._responses else {
                "shots": [{"shot_type": "medium", "action": "测试动作", "duration": 4.0}]
            }
        self._calls += 1
        return _MockResp(json.dumps(resp))


# ───────────────────────────────────────────────────────────────────────────
# ExtractedShot 模型
# ───────────────────────────────────────────────────────────────────────────


def test_extracted_shot_valid():
    s = ExtractedShot(
        shot_type="medium",
        action="哥哥坐在书桌前",
        emotion="平静",
        dialogue="",
        duration=4.0,
        characters=["哥哥"],
    )
    assert s.shot_type == "medium"
    assert s.duration == 4.0


def test_valid_shot_types_cover_expected():
    assert "wide" in VALID_SHOT_TYPES
    assert "close-up" in VALID_SHOT_TYPES
    assert "pov" in VALID_SHOT_TYPES


# ───────────────────────────────────────────────────────────────────────────
# ScreenwritingCritique / Result 模型
# ───────────────────────────────────────────────────────────────────────────


def test_critique_ok():
    c = ScreenwritingCritique(ok=True, severity="none", issues=[])
    assert c.ok
    assert c.severity == "none"


def test_critique_with_issues():
    c = ScreenwritingCritique(
        ok=False, severity="major",
        issues=["遗漏了关键情节", "时间线混乱"],
    )
    assert c.severity == "major"
    assert len(c.issues) == 2


def test_screenwriting_result():
    r = ScreenwritingResult(
        shots=[ExtractedShot(shot_type="wide", action="test")],
        revisions=1, critique_summary="minor issue",
    )
    assert r.revisions == 1
    assert len(r.shots) == 1


# ───────────────────────────────────────────────────────────────────────────
# format_scene_meta / format_relevant_entities
# ───────────────────────────────────────────────────────────────────────────


def test_format_scene_meta_all_fields():
    result = format_scene_meta(0, "s001", "上午", "厨房", "男主")
    assert "场景0" in result
    assert "时间：上午" in result
    assert "地点：厨房" in result
    assert "视角：男主" in result


def test_format_relevant_entities_with_alias():
    ent = Entity(
        id="e001", type="character", name="哥哥",
        aliases=["阿哥"],
        attrs=[EntityAttr(key="appearance", value="黑发，学生制服")],
        variants=[EntityVariant(label="高中哥哥", time_desc="", appearance="")],
    )
    result = format_relevant_entities([ent])
    assert "哥哥" in result
    assert "阿哥" in result
    assert "黑发" in result
    assert "高中哥哥" in result


def test_format_relevant_entities_empty():
    result = format_relevant_entities([])
    assert "无已知实体" in result


# ───────────────────────────────────────────────────────────────────────────
# call_screenwriter(mock LLM)
# ───────────────────────────────────────────────────────────────────────────


def test_call_screenwriter_basic():
    llm = _MockLLM([{
        "shots": [
            {"shot_type": "wide", "action": "兄妹在厨房", "duration": 3.0},
            {"shot_type": "medium", "action": "妹妹递过毛巾", "duration": 2.0},
        ],
    }, {
        "ok": True, "severity": "none", "issues": [],
    }])
    result = call_screenwriter(
        "厨房场景文本", scene_idx=0, scene_id="s001",
        rolling_summary="", llm=llm,
    )
    assert len(result.shots) == 2
    assert result.shots[0].shot_type == "wide"


def test_call_screenwriter_parse_error():
    class BadLLM:
        def invoke(self, messages):
            return _MockResp("INVALID{")

    with pytest.raises(ScreenwriterError):
        call_screenwriter(
            "scene text", scene_idx=0, scene_id="s001",
            rolling_summary="", llm=BadLLM(),
        )


def test_call_screenwriter_revision_on_major_issue():
    """critic 报 major 问题后会修订。"""
    first_resp = {
        "shots": [{"shot_type": "wide", "action": "初始", "duration": 4.0}],
    }
    critique_major = {"ok": False, "severity": "major", "issues": ["重要遗漏！"]}
    revised_resp = {
        "shots": [
            {"shot_type": "wide", "action": "初始", "duration": 4.0},
            {"shot_type": "close-up", "action": "补充细节", "duration": 3.0},
        ],
    }
    critique_ok = {"ok": True, "severity": "none", "issues": []}

    llm = _MockLLM([first_resp, critique_major, revised_resp, critique_ok])

    result = call_screenwriter(
        "original text", scene_idx=0, scene_id="s001", llm=llm,
    )
    assert result.revisions == 1
    assert len(result.shots) == 2


# ───────────────────────────────────────────────────────────────────────────
# save_scene_shots / 文件 roundtrip
# ───────────────────────────────────────────────────────────────────────────


def test_save_and_load_scene_shots():
    work_id, _ = _setup_work([(0, [(0, "场景A" * 30)])])
    scene_id = "test_scene_001"
    shots = [
        Shot(
            id="sh001", scene_id=scene_id, idx=0,
            shot_type="wide", action="测试动作1", status=ArtifactStatus.validated,
        ),
        Shot(
            id="sh002", scene_id=scene_id, idx=1,
            shot_type="medium", action="测试动作2", status=ArtifactStatus.validated,
        ),
    ]
    save_scene_shots(work_id, scene_id, shots)

    loaded = store.load_shots(work_id)
    assert len(loaded) == 2
    assert loaded[0].shot_type == "wide"
    assert loaded[0].action == "测试动作1"


def test_shots_file_naming():
    work_id, _ = _setup_work([(0, [(0, "文本" * 30)])])
    scene_id = "s01005_abc1"
    shots = [Shot(id="sh01", scene_id=scene_id, idx=0, shot_type="pov", action="测试")]
    save_scene_shots(work_id, scene_id, shots)

    path = store.work_dir(work_id) / "shots" / f"{scene_id}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["shot_type"] == "pov"


# ───────────────────────────────────────────────────────────────────────────
# run_s4 管线集成
# ───────────────────────────────────────────────────────────────────────────


def test_run_s4_basic_flow():
    work_id, _ = _setup_work([
        (0, [(0, "场景1原文。" * 20)]),
        (1, [(0, "场景2原文。" * 20)]),
    ])

    llm = _MockLLM([
        {"shots": [{"shot_type": "wide", "action": "动作A"}]},
        {"ok": True, "severity": "none", "issues": []},
        {"shots": [{"shot_type": "medium", "action": "动作B"}]},
        {"ok": True, "severity": "none", "issues": []},
    ])

    result = run_s4(work_id, llm=llm)
    assert result.ok
    assert result.stats.scenes_processed == 2
    assert result.stats.shots_created == 2

    all_shots = store.load_shots(work_id)
    assert len(all_shots) == 2


def test_run_s4_resume_skips_done():
    work_id, _ = _setup_work([
        (0, [(0, "文本1" * 40)]),
        (1, [(0, "文本2" * 40)]),
    ])
    scene_ids = [s.id for ep in store.load_episodes(work_id) for s in ep.scenes]
    ## 预先写入第一个场景的 shots
    existing_shots = [Shot(
        id="sh_existing", scene_id=scene_ids[0], idx=0,
        shot_type="wide", action="已保存",
    )]
    save_scene_shots(work_id, scene_ids[0], existing_shots)

    llm = _MockLLM([
        {"shots": [{"shot_type": "medium", "action": "新场景"}]},
        {"ok": True, "severity": "none", "issues": []},
    ])

    result = run_s4(work_id, llm=llm, resume=True)
    assert result.scenes_skipped == 1
    assert result.stats.scenes_processed == 2
    assert llm._calls == 2  ## 1 call to generate + 1 to critique for the new scene


def test_run_s4_update_run_state():
    work_id, _ = _setup_work([(0, [(0, "文本" * 50)])])
    llm = _MockLLM([
        {"shots": [{"shot_type": "wide", "action": "测试"}]},
        {"ok": True, "severity": "none", "issues": []},
    ])
    run_s4(work_id, llm=llm)

    rs = store.read_model(store.work_dir(work_id) / "run_state.json", store.RunState)
    assert rs.stage == "M4"
    assert rs.status == ArtifactStatus.validated


def test_run_s4_error_doesnt_crash():
    work_id, _ = _setup_work([(0, [(0, "A" * 50)])])

    class ErrorLLM:
        def invoke(self, messages):
            return _MockResp("BAD_JSON")

    result = run_s4(work_id, llm=ErrorLLM())
    assert not result.ok
    assert len(result.stats.errors) == 1


def test_run_s4_operation_logged():
    work_id, _ = _setup_work([(0, [(0, "文本" * 50)])])
    llm = _MockLLM([
        {"shots": [{"shot_type": "wide", "action": "x"}]},
        {"ok": True, "severity": "none", "issues": []},
    ])
    run_s4(work_id, llm=llm)

    ops = store.load_operations(work_id, limit=5)
    assert any(o.command == "s4.built" for o in ops)


# ───────────────────────────────────────────────────────────────────────────
# S4Result 辅助方法
# ───────────────────────────────────────────────────────────────────────────


def test_s4result_summary_lines():
    result = S4Result(
        shots=[],
        stats=S4Stats(total_scenes=10, scenes_processed=8, shots_created=50),
        scenes_skipped=2,
    )
    lines = result.summary_lines()
    assert any("处理场景" in l for l in lines)
    assert any("跳过了 2" in l for l in lines)
    assert any("50" in l for l in lines)
