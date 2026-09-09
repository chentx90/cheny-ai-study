"""M5 角色绑定管线单测。"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid

import pytest

from manga_manager import store
from manga_manager.agents.continuity import (
    ContinueResult,
    bind_scene,
    build_appearance_snapshot,
    check_cross_scene_consistency,
    extract_ages,
    match_variant_for_age,
    resolve_character_key,
)
from manga_manager.models import (
    ArtifactStatus,
    BindingFile,
    BindingItem,
    Entity,
    EntityAttr,
    EntityVariant,
    Episode,
    RawSpan,
    Scene,
    Shot,
    ShotEntityBinding,
    WorkIndex,
)
from manga_manager.pipeline.s5_continuity import (
    run_s5,
    save_scene_binding,
    save_updated_shots,
)


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="manga_m5test_")
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
    return work_id, full_source


def _make_shot(
    shot_id: str, scene_id: str, idx: int,
    characters: list[str], action: str = "test",
) -> Shot:
    return Shot(
        id=shot_id, scene_id=scene_id, idx=idx,
        shot_type="medium", action=action,
        characters=characters, status=ArtifactStatus.draft,
    )


def _make_entities() -> list[Entity]:
    return [
        Entity(
            id="e001", type="character", name="哥哥",
            aliases=["阿哥"],
            attrs=[
                EntityAttr(key="appearance", value="黑发，温和"),
                EntityAttr(key="hair", value="黑发"),
            ],
            variants=[
                EntityVariant(label="幼年哥哥", time_desc="3岁", appearance="短发，穿蓝衣服"),
                EntityVariant(label="童年哥哥", time_desc="6岁", appearance="戴眼镜"),
                EntityVariant(label="高中哥哥", time_desc="15-18岁", appearance="学生制服"),
                EntityVariant(label="成年哥哥", time_desc="25岁", appearance="上班族"),
            ],
        ),
        Entity(
            id="e002", type="character", name="妹妹",
            aliases=["阿妹"],
            attrs=[EntityAttr(key="appearance", value="长发")],
            variants=[
                EntityVariant(label="幼年妹妹", time_desc="3-10岁", appearance="圆脸"),
                EntityVariant(label="高中妹妹", time_desc="15-18岁", appearance="长发及肩"),
            ],
        ),
        Entity(
            id="e003", type="location", name="厨房",
            attrs=[],
            variants=[],
        ),
    ]


def _make_index(entities: list[Entity]) -> WorkIndex:
    index = WorkIndex()
    for ent in entities:
        if ent.type != "location":
            index.entity_name_to_id[ent.name] = ent.id
            for alias in ent.aliases:
                index.alias_to_id[alias] = ent.id
    return index


# ───────────────────────────────────────────────────────────────────────────
# 模型测试
# ───────────────────────────────────────────────────────────────────────────


def test_shot_entity_binding_model():
    b = ShotEntityBinding(
        character_key="哥哥", entity_id="e001",
        variant_label="高中哥哥", confidence=0.9,
    )
    assert b.variant_label == "高中哥哥"
    assert b.confidence == 0.9


def test_binding_item_new_fields():
    item = BindingItem(
        entity_id="e001", role="present",
        variant_label="高中哥哥",
        appearance_snapshot="[高中哥哥] 学生制服",
        confidence=0.95,
    )
    assert item.variant_label == "高中哥哥"
    assert item.confidence == 0.95


def test_binding_file_includes_issues():
    bf = BindingFile(
        scene_id="s1", bindings={"sh1": []},
        issues=["角色'小明'无法解析"],
    )
    assert len(bf.issues) == 1


# ───────────────────────────────────────────────────────────────────────────
# extract_ages / match_variant_for_age
# ───────────────────────────────────────────────────────────────────────────


def test_extract_ages_arabic():
    assert extract_ages("10岁夏天") == [10]
    assert extract_ages("3-6岁期间") == [6]


def test_extract_ages_chinese():
    assert extract_ages("十五岁") == [15]
    assert extract_ages("三岁") == [3]


def test_extract_ages_empty():
    assert extract_ages("") == []
    assert extract_ages("无年龄") == []


def test_match_variant_exact_age():
    entities = _make_entities()
    brother = entities[0]
    label, conf = match_variant_for_age(brother, 6)
    assert label == "童年哥哥"
    assert conf == 1.0


def test_match_variant_age_range():
    entities = _make_entities()
    brother = entities[0]
    label, conf = match_variant_for_age(brother, 16)
    assert label == "高中哥哥"
    assert conf == 1.0


def test_match_variant_no_age_fallback():
    entities = _make_entities()
    brother = entities[0]
    label, conf = match_variant_for_age(brother)
    assert label == "幼年哥哥"  # 第一个
    assert conf == 0.3


def test_match_variant_no_variants():
    loc = Entity(id="e003", type="location", name="厨房")
    label, conf = match_variant_for_age(loc, 10)
    assert label == ""
    assert conf == 0.0


def test_match_variant_age_out_of_range():
    entities = _make_entities()
    brother = entities[0]
    label, conf = match_variant_for_age(brother, 100)
    assert label == "幼年哥哥"  # 兜底
    assert conf == 0.3


# ───────────────────────────────────────────────────────────────────────────
# resolve_character_key
# ───────────────────────────────────────────────────────────────────────────


def test_resolve_by_name():
    entities = _make_entities()
    index = _make_index(entities)
    assert resolve_character_key("哥哥", index) == "e001"


def test_resolve_by_alias():
    entities = _make_entities()
    index = _make_index(entities)
    assert resolve_character_key("阿妹", index) == "e002"


def test_resolve_unknown():
    entities = _make_entities()
    index = _make_index(entities)
    assert resolve_character_key("陌生人", index) is None


def test_resolve_empty():
    entities = _make_entities()
    index = _make_index(entities)
    assert resolve_character_key("", index) is None
    assert resolve_character_key("  ", index) is None


# ───────────────────────────────────────────────────────────────────────────
# build_appearance_snapshot
# ───────────────────────────────────────────────────────────────────────────


def test_build_snapshot_no_variant():
    entities = _make_entities()
    brother = entities[0]
    snap = build_appearance_snapshot(brother, "")
    assert "黑发" in snap
    assert "温和" in snap


def test_build_snapshot_with_variant():
    entities = _make_entities()
    brother = entities[0]
    snap = build_appearance_snapshot(brother, "高中哥哥")
    assert "[高中哥哥]" in snap
    assert "学生制服" in snap


# ───────────────────────────────────────────────────────────────────────────
# bind_scene
# ───────────────────────────────────────────────────────────────────────────


def test_bind_scene_basic():
    entities = _make_entities()
    index = _make_index(entities)

    scene = Scene(
        id="s1", episode_idx=0, idx=0,
        time="16岁夏天", location="学校",
        raw_span=RawSpan(start=0, end=10),
    )
    shots = [
        _make_shot("sh1", "s1", 0, ["哥哥", "妹妹"]),
        _make_shot("sh2", "s1", 1, ["妹妹"]),
    ]

    result = bind_scene(scene, shots, entities, index)

    assert result.scene_id == "s1"
    assert len(result.bindings) == 2
    assert len(result.bindings["sh1"]) == 2  # 哥哥+妹妹
    assert len(result.bindings["sh2"]) == 1  # 妹妹

    brother_item = next(i for i in result.bindings["sh1"] if i.entity_id == "e001")
    assert brother_item.variant_label == "高中哥哥"
    assert brother_item.confidence == 1.0

    sister_item = next(i for i in result.bindings["sh2"] if i.entity_id == "e002")
    assert sister_item.variant_label == "高中妹妹"


def test_bind_scene_unknown_character_issue():
    entities = _make_entities()
    index = _make_index(entities)
    scene = Scene(
        id="s1", episode_idx=0, idx=0,
        raw_span=RawSpan(start=0, end=10),
    )
    shots = [_make_shot("sh1", "s1", 0, ["陌生人"])]

    result = bind_scene(scene, shots, entities, index)

    assert len(result.bindings["sh1"]) == 0
    assert any("无法解析" in i for i in result.issues)


def test_bind_scene_dedup_in_same_shot():
    """同一 shot 内重复角色只绑定一次。"""
    entities = _make_entities()
    index = _make_index(entities)
    scene = Scene(
        id="s1", episode_idx=0, idx=0,
        raw_span=RawSpan(start=0, end=10),
    )
    shots = [_make_shot("sh1", "s1", 0, ["哥哥", "哥哥", "阿哥"])]

    result = bind_scene(scene, shots, entities, index)
    assert len(result.bindings["sh1"]) == 1  # 哥哥+阿哥指向同一实体


def test_bind_scene_skip_scene_mismatch():
    """shots 里 scene_id 不匹配应该跳过。"""
    entities = _make_entities()
    index = _make_index(entities)
    scene = Scene(
        id="s1", episode_idx=0, idx=0,
        raw_span=RawSpan(start=0, end=10),
    )
    shots = [_make_shot("sh_wrong_scene", "s99", 0, ["哥哥"])]

    result = bind_scene(scene, shots, entities, index)
    assert len(result.bindings) == 0


def test_bind_scene_no_characters():
    entities = _make_entities()
    index = _make_index(entities)
    scene = Scene(
        id="s1", episode_idx=0, idx=0,
        raw_span=RawSpan(start=0, end=10),
    )
    shots = [_make_shot("sh1", "s1", 0, [])]

    result = bind_scene(scene, shots, entities, index)
    assert result.bindings["sh1"] == []


def test_bind_scene_updates_matched_entities():
    entities = _make_entities()
    index = _make_index(entities)
    scene = Scene(
        id="s1", episode_idx=0, idx=0,
        time="16岁",
        raw_span=RawSpan(start=0, end=10),
    )
    shots = [_make_shot("sh1", "s1", 0, ["哥哥"])]

    result = bind_scene(scene, shots, entities, index)
    updated = result.updated_shots[0]
    assert len(updated.matched_entities) == 1
    assert updated.matched_entities[0].character_key == "哥哥"
    assert updated.matched_entities[0].variant_label == "高中哥哥"


# ───────────────────────────────────────────────────────────────────────────
# check_cross_scene_consistency
# ───────────────────────────────────────────────────────────────────────────


def test_cross_scene_consistent():
    r1 = ContinueResult(
        scene_id="s1",
        bindings={"sh1": [BindingItem(entity_id="e001", variant_label="高中哥哥")]},
        updated_shots=[],
    )
    r2 = ContinueResult(
        scene_id="s2",
        bindings={"sh2": [BindingItem(entity_id="e001", variant_label="高中哥哥")]},
        updated_shots=[],
    )
    issues = check_cross_scene_consistency([r1, r2])
    assert issues == []


def test_cross_scene_inconsistent():
    r1 = ContinueResult(
        scene_id="s1",
        bindings={"sh1": [BindingItem(entity_id="e001", variant_label="幼年哥哥")]},
        updated_shots=[],
    )
    r2 = ContinueResult(
        scene_id="s2",
        bindings={"sh2": [BindingItem(entity_id="e001", variant_label="成年哥哥")]},
        updated_shots=[],
    )
    issues = check_cross_scene_consistency([r1, r2])
    assert len(issues) == 1
    assert "多个变体" in issues[0]


def test_cross_scene_no_variant_no_issue():
    r1 = ContinueResult(
        scene_id="s1",
        bindings={"sh1": [BindingItem(entity_id="e001", variant_label="")]},
        updated_shots=[],
    )
    issues = check_cross_scene_consistency([r1])
    assert issues == []


# ───────────────────────────────────────────────────────────────────────────
# save_scene_binding / save_updated_shots（文件 roundtrip）
# ───────────────────────────────────────────────────────────────────────────


def test_save_and_load_binding():
    work_id, _ = _setup_work([(0, [(0, "场景")])])
    ep = store.load_episodes(work_id)[0]
    scene = ep.scenes[0]
    binding_file = BindingFile(
        scene_id=scene.id,
        bindings={
            "sh1": [BindingItem(
                entity_id="e001", variant_label="高中哥哥",
                appearance_snapshot="学生制服",
            )],
        },
        issues=[],
    )
    root = store.work_dir(work_id)
    bindings_dir = root / "bindings"
    bindings_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(bindings_dir / f"{scene.id}.json", binding_file)

    raw = json.loads((bindings_dir / f"{scene.id}.json").read_text(encoding="utf-8"))
    loaded = BindingFile.model_validate(raw)
    assert "sh1" in loaded.bindings
    assert loaded.scene_id == scene.id


# ───────────────────────────────────────────────────────────────────────────
# run_s5 管线集成
# ───────────────────────────────────────────────────────────────────────────


def test_run_s5_basic_flow():
    work_id, _ = _setup_work([
        (0, [(0, "A"), (1, "B")]),
    ])

    entities = _make_entities()
    store.save_entities(work_id, entities)

    # 写 shots
    ep = store.load_episodes(work_id)[0]
    index = _make_index(entities)
    for scene in ep.scenes:
        shots = [_make_shot(f"sh_{scene.id}", scene.id, 0, ["哥哥", "妹妹"])]
        shots_path = store.work_dir(work_id) / "shots"
        shots_path.mkdir(parents=True, exist_ok=True)
        store.write_json_atomic(shots_path / f"{scene.id}.json", shots)

    result = run_s5(work_id)
    assert result.stats.scenes_processed == 2
    assert result.stats.total_bindings == 2
    assert result.ok


def test_run_s5_resume_skips_done():
    work_id, _ = _setup_work([(0, [(0, "A")])])
    entities = _make_entities()
    store.save_entities(work_id, entities)

    # 写 shots 和 binding
    ep = store.load_episodes(work_id)[0]
    scene = ep.scenes[0]
    shots = [_make_shot(f"sh_{scene.id}", scene.id, 0, ["哥哥"])]
    shots_dir = store.work_dir(work_id) / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(shots_dir / f"{scene.id}.json", shots)

    bindings_dir = store.work_dir(work_id) / "bindings"
    bindings_dir.mkdir(parents=True, exist_ok=True)
    binding_file = BindingFile(scene_id=scene.id, bindings={})
    store.write_json_atomic(bindings_dir / f"{scene.id}.json", binding_file)

    result = run_s5(work_id, resume=True)
    assert result.scenes_skipped == 1


def test_run_s5_missing_shots_file():
    work_id, _ = _setup_work([(0, [(0, "A")])])

    result = run_s5(work_id)
    assert len(result.stats.errors) == 1
    assert "shots 文件不存在" in result.stats.errors[0][1]


def test_run_s5_update_run_state():
    work_id, _ = _setup_work([(0, [(0, "A")])])
    entities = _make_entities()
    store.save_entities(work_id, entities)

    ep = store.load_episodes(work_id)[0]
    scene = ep.scenes[0]
    shots = [_make_shot(f"sh_{scene.id}", scene.id, 0, ["哥哥"])]
    shots_dir = store.work_dir(work_id) / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(shots_dir / f"{scene.id}.json", shots)

    run_s5(work_id)

    rs = store.read_model(store.work_dir(work_id) / "run_state.json", store.RunState)
    assert rs.stage == "M5"
    assert rs.status == ArtifactStatus.validated


def test_run_s5_operation_logged():
    work_id, _ = _setup_work([(0, [(0, "A")])])
    entities = _make_entities()
    store.save_entities(work_id, entities)

    ep = store.load_episodes(work_id)[0]
    shots = [_make_shot(f"sh_{ep.scenes[0].id}", ep.scenes[0].id, 0, ["哥哥"])]
    shots_dir = store.work_dir(work_id) / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(shots_dir / f"{ep.scenes[0].id}.json", shots)

    run_s5(work_id)

    ops = store.load_operations(work_id, limit=5)
    assert any(o.command == "s5.built" for o in ops)


def test_run_s5_progress_callback():
    work_id, _ = _setup_work([(0, [(0, "A")])])
    entities = _make_entities()
    store.save_entities(work_id, entities)

    ep = store.load_episodes(work_id)[0]
    scene = ep.scenes[0]
    shots = [_make_shot(f"sh_{scene.id}", scene.id, 0, ["哥哥"])]
    shots_dir = store.work_dir(work_id) / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(shots_dir / f"{scene.id}.json", shots)

    progress = []

    def cb(done, total, scene_id):
        progress.append((done, total, scene_id))

    run_s5(work_id, on_scene_progress=cb)
    assert len(progress) == 1


def test_run_s5_no_episodes():
    meta = store.create_work("空作品")
    work_id = meta.id

    with pytest.raises(Exception, match="no episodes found"):
        run_s5(work_id)
