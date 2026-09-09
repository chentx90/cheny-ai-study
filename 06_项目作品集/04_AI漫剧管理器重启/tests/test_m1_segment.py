"""M1 S1 切分管线单测。

所有测试均为纯 Python 逻辑，不调用 LLM：
  - resolve_anchors_to_spans（offset 解析）
  - validate_segmentation（L1 确定性校验）
  - save_episodes / get_source_text（store Round-trip）
"""

from __future__ import annotations

import uuid

import pytest

from manga_manager.agents.segmenter import SegmenterError, resolve_anchors_to_spans
from manga_manager.models import Episode, RawSpan, Scene, ValidationIssue
from manga_manager.pipeline.s1_segment import validate_segmentation
from manga_manager import store


SOURCE = "AAABBBCCC第一章少年上山。少年逃上山。天已黑。第二章少年遇险。悬崖边。星光下。第三章少年归来。风归家。"


# ───────────────────────────────────────────────────────────────────────────
# resolve_anchors_to_spans
# ───────────────────────────────────────────────────────────────────────────


def test_resolve_two_anchors():
    text = "AABBCC"
    spans = resolve_anchors_to_spans(text, ["AA", "CC"])
    assert spans == [(0, 4), (4, 6)]


def test_resolve_single_anchor():
    text = "HELLO WORLD"
    spans = resolve_anchors_to_spans(text, ["HELLO"])
    assert spans == [(0, len(text))]


def test_resolve_with_offset():
    text = "XY第一章"
    spans = resolve_anchors_to_spans(text, ["第一章"], text_start_offset=10)
    assert spans[0] == (10 + 2, 10 + len(text))


def test_resolve_anchor_not_found():
    with pytest.raises(SegmenterError, match="Anchor not found"):
        resolve_anchors_to_spans("ABCDEF", ["ZZZ"])


def test_resolve_monotonic_search():
    # 'AA' 在文本中出现两次，第一次 idx=0，第二次 idx=4
    text = "AABBAABB"
    # 两个 anchor 都是 'AA'，必须单调向前搜索
    spans = resolve_anchors_to_spans(text, ["AA", "AA"])
    assert spans[0][0] == 0
    assert spans[1][0] == 4


def test_resolve_three_anchors_full_coverage():
    text = "---ABC===DEF+++GHI"
    spans = resolve_anchors_to_spans(text, ["---", "===", "+++"])
    # 覆盖全文
    assert spans[0] == (0, 6)
    assert spans[1] == (6, 12)
    assert spans[2] == (12, len(text))


# ───────────────────────────────────────────────────────────────────────────
# validate_segmentation — L1 校验
# ───────────────────────────────────────────────────────────────────────────


def _make_episode(idx: int, start: int, end: int, scenes: list[Scene]) -> Episode:
    return Episode(
        id=f"ep{idx:04d}_{uuid.uuid4().hex[:4]}",
        idx=idx,
        title=f"第{idx+1}集",
        raw_span=RawSpan(start=start, end=end),
        scenes=scenes,
    )


def _make_scene(ep_idx: int, idx: int, start: int, end: int) -> Scene:
    return Scene(
        id=f"s{ep_idx:02d}{idx:03d}_{uuid.uuid4().hex[:4]}",
        episode_idx=ep_idx,
        idx=idx,
        raw_span=RawSpan(start=start, end=end),
    )


def test_validate_good_segmentation():
    src = "AABBCCDD"  # len=8
    ep0 = _make_episode(0, 0, 4, [_make_scene(0, 0, 0, 2), _make_scene(0, 1, 2, 4)])
    ep1 = _make_episode(1, 4, 8, [_make_scene(1, 0, 4, 8)])
    report = validate_segmentation(src, [ep0, ep1])
    assert report.ok, [i.message for i in report.issues]


def test_validate_empty_episodes():
    report = validate_segmentation("ABC", [])
    assert not report.ok
    assert any("empty" in i.message for i in report.issues)


def test_validate_first_ep_not_start_at_0():
    src = "ABCDEFGH"
    ep0 = _make_episode(0, 2, 8, [_make_scene(0, 0, 2, 8)])
    report = validate_segmentation(src, [ep0])
    assert not report.ok
    assert any("start at 0" in i.message for i in report.issues)


def test_validate_last_ep_not_end():
    src = "ABCDEFGH"
    ep0 = _make_episode(0, 0, 6, [_make_scene(0, 0, 0, 6)])
    report = validate_segmentation(src, [ep0])
    assert not report.ok
    assert any(str(len(src)) in i.message for i in report.issues)


def test_validate_gap_between_episodes():
    src = "AABBCCDD"
    ep0 = _make_episode(0, 0, 3, [_make_scene(0, 0, 0, 3)])
    ep1 = _make_episode(1, 5, 8, [_make_scene(1, 0, 5, 8)])
    report = validate_segmentation(src, [ep0, ep1])
    assert not report.ok
    assert any("gap or overlap" in i.message for i in report.issues)


def test_validate_scene_outside_episode():
    src = "ABCDEFGH"
    bad_scene = _make_scene(0, 0, 0, 10)  # end=10 > ep.end=8
    ep0 = _make_episode(0, 0, 8, [bad_scene])
    report = validate_segmentation(src, [ep0])
    assert not report.ok
    assert any("outside episode" in i.message for i in report.issues)


def test_validate_scene_gap():
    src = "ABCDEFGH"
    s0 = _make_scene(0, 0, 0, 3)
    s1 = _make_scene(0, 1, 5, 8)  # gap 3→5
    ep0 = _make_episode(0, 0, 8, [s0, s1])
    report = validate_segmentation(src, [ep0])
    assert not report.ok
    assert any("gap/overlap" in i.message for i in report.issues)


def test_validate_no_scenes():
    src = "ABCDEFGH"
    ep0 = Episode(
        id="ep_x",
        idx=0,
        title="无场景集",
        raw_span=RawSpan(start=0, end=8),
        scenes=[],
    )
    report = validate_segmentation(src, [ep0])
    assert not report.ok
    assert any("no scenes" in i.message for i in report.issues)


def test_validate_wrong_idx():
    src = "ABCDEF"
    ep0 = _make_episode(0, 0, 3, [_make_scene(0, 0, 0, 3)])
    ep_bad = Episode(
        id="ep_bad",
        idx=5,  # should be 1
        title="错误idx",
        raw_span=RawSpan(start=3, end=6),
        scenes=[_make_scene(5, 0, 3, 6)],
    )
    report = validate_segmentation(src, [ep0, ep_bad])
    assert not report.ok
    assert any("expected idx=1" in i.message for i in report.issues)


# ───────────────────────────────────────────────────────────────────────────
# store.save_episodes + get_source_text round-trip
# ───────────────────────────────────────────────────────────────────────────


def test_save_and_reload_episodes(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("切分测试")
    src = "第一章开始。故事由此展开。第二章发展。情节递进。"
    (store.work_dir(work.id) / "source.txt").write_text(src, encoding="utf-8")

    ep0 = _make_episode(0, 0, len(src) // 2, [_make_scene(0, 0, 0, len(src) // 2)])
    ep1 = _make_episode(1, len(src) // 2, len(src), [_make_scene(1, 0, len(src) // 2, len(src))])
    store.save_episodes(work.id, [ep0, ep1])

    loaded = store.load_episodes(work.id)
    assert len(loaded) == 2
    assert loaded[0].idx == 0
    assert loaded[1].idx == 1
    assert len(loaded[0].scenes) == 1


def test_get_source_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("原文读取测试")
    content = "测试原文内容，共三十字，用于验证 get_source_text 函数正常工作。"
    (store.work_dir(work.id) / "source.txt").write_text(content, encoding="utf-8")
    assert store.get_source_text(work.id) == content


def test_save_episodes_clears_old(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("覆盖测试")
    src = "AB"
    (store.work_dir(work.id) / "source.txt").write_text(src, encoding="utf-8")

    ep_old = _make_episode(0, 0, 2, [_make_scene(0, 0, 0, 2)])
    store.save_episodes(work.id, [ep_old])

    # 重新切（只有一集，旧的另一集应被清除）
    ep_new = _make_episode(0, 0, 2, [_make_scene(0, 0, 0, 2)])
    store.save_episodes(work.id, [ep_new])

    loaded = store.load_episodes(work.id)
    assert len(loaded) == 1
