"""M2 S2 设定库管线单测。

所有测试均为纯 Python 逻辑，不调用 LLM：
  - _resolve_name 名称解析
  - _apply_extraction 去重合并逻辑
  - save_entities / save_relations store round-trip
  - scene_to_entities 倒排索引
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from manga_manager.agents.bible_builder import (
    BibleExtraction,
    ExtractedAttr,
    ExtractedEntity,
    ExtractedRelation,
    format_known_entities,
)
from manga_manager.models import (
    Entity,
    EntityAttr,
    Importance,
    RawSpan,
    Relation,
    Scene,
    WorkIndex,
)
from manga_manager.pipeline.s2_bible import S2Stats, _apply_extraction, _resolve_name


# ───────────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────────


def _make_scene(idx: int = 0, episode_idx: int = 0) -> Scene:
    return Scene(
        id=f"s{episode_idx:02d}{idx:03d}_{uuid.uuid4().hex[:4]}",
        episode_idx=episode_idx,
        idx=idx,
        time="白天",
        location="教室",
        pov="哥哥",
        summary="兄妹对话",
        raw_span=RawSpan(start=0, end=100),
    )


def _make_entity(
    name: str = "哥哥",
    entity_type: str = "character",
    entity_id: str | None = None,
    aliases: list[str] | None = None,
    importance: str = "major",
    attrs: list[EntityAttr] | None = None,
) -> Entity:
    return Entity(
        id=entity_id or f"e{uuid.uuid4().hex[:8]}",
        type=entity_type,
        name=name,
        aliases=aliases or [],
        importance=importance,
        attrs=attrs or [],
    )


def _make_index(*entities: Entity) -> WorkIndex:
    idx = WorkIndex()
    for ent in entities:
        idx.entity_name_to_id[ent.name] = ent.id
        for alias in ent.aliases:
            idx.alias_to_id[alias] = ent.id
    return idx


# ───────────────────────────────────────────────────────────────────────────────
# _resolve_name
# ───────────────────────────────────────────────────────────────────────────────


def test_resolve_name_by_name():
    ent = _make_entity("哥哥", entity_id="e1")
    idx = _make_index(ent)
    assert _resolve_name("哥哥", idx.entity_name_to_id, idx.alias_to_id) == "e1"


def test_resolve_name_by_alias():
    ent = _make_entity("哥哥", entity_id="e1", aliases=["我", "阿刘"])
    idx = _make_index(ent)
    assert _resolve_name("我", idx.entity_name_to_id, idx.alias_to_id) == "e1"
    assert _resolve_name("阿刘", idx.entity_name_to_id, idx.alias_to_id) == "e1"


def test_resolve_name_not_found():
    idx = WorkIndex()
    assert _resolve_name("张三", idx.entity_name_to_id, idx.alias_to_id) is None


def test_resolve_name_empty():
    idx = WorkIndex()
    assert _resolve_name("", idx.entity_name_to_id, idx.alias_to_id) is None


# ───────────────────────────────────────────────────────────────────────────────
# _apply_extraction — 新实体创建
# ───────────────────────────────────────────────────────────────────────────────


def test_apply_new_entity():
    scene = _make_scene()
    entities: list[Entity] = []
    relations: list[Relation] = []
    index = WorkIndex()
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[
            ExtractedEntity(
                existing_id=None,
                name="哥哥",
                type="character",
                importance="major",
                aliases=["我"],
                attrs=[ExtractedAttr(key="age", value="20", confidence=0.9)],
            )
        ],
        relations=[],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(entities) == 1
    assert entities[0].name == "哥哥"
    assert entities[0].aliases == ["我"]
    assert entities[0].importance == "major"
    assert entities[0].attrs[0].key == "age"
    assert stats.entities_created == 1

    assert index.entity_name_to_id["哥哥"] == entities[0].id
    assert index.alias_to_id["我"] == entities[0].id
    assert entities[0].id in index.scene_to_entities[scene.id]


def test_apply_multiple_new_entities():
    scene = _make_scene()
    entities: list[Entity] = []
    relations: list[Relation] = []
    index = WorkIndex()
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[
            ExtractedEntity(existing_id=None, name="哥哥", type="character", importance="major", aliases=[]),
            ExtractedEntity(existing_id=None, name="妹妹", type="character", importance="major", aliases=[]),
            ExtractedEntity(existing_id=None, name="教室", type="location", importance="minor", aliases=[]),
        ],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(entities) == 3
    assert stats.entities_created == 3
    assert len([e for e in entities if e.type == "character"]) == 2
    assert len([e for e in entities if e.type == "location"]) == 1


# ───────────────────────────────────────────────────────────────────────────────
# _apply_extraction — 已有实体合并
# ───────────────────────────────────────────────────────────────────────────────


def test_apply_merge_existing():
    scene = _make_scene()
    ent = _make_entity("哥哥", entity_id="e_brother", importance="minor")
    entities: list[Entity] = [ent]
    relations: list[Relation] = []
    index = _make_index(ent)
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[
            ExtractedEntity(
                existing_id="e_brother",
                name="哥哥",
                type="character",
                importance="major",
                aliases=["我"],
                attrs=[ExtractedAttr(key="age", value="20", confidence=0.9)],
            )
        ],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(entities) == 1
    assert stats.entities_merged == 1
    assert ent.importance == "major"
    assert "我" in ent.aliases
    assert index.alias_to_id["我"] == "e_brother"
    assert len(ent.attrs) == 1
    assert ent.attrs[0].key == "age"


def test_apply_merge_alias_only():
    scene = _make_scene()
    ent = _make_entity("刘同学", entity_id="e_liu", aliases=["刘某"])
    entities: list[Entity] = [ent]
    relations: list[Relation] = []
    index = _make_index(ent)
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[
            ExtractedEntity(
                existing_id="e_liu",
                name="同学A",
                type="character",
                importance="minor",
                aliases=[],
            )
        ],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(entities) == 1
    assert "同学A" in ent.aliases
    assert index.alias_to_id["同学A"] == "e_liu"
    assert stats.entities_merged == 1


def test_apply_attr_dedup():
    scene1 = _make_scene(idx=0)
    scene2 = _make_scene(idx=1)
    ent = _make_entity("哥哥", entity_id="e_bro")
    ent.attrs.append(EntityAttr(key="age", value="20", source_scene=scene1.id))
    entities: list[Entity] = [ent]
    relations: list[Relation] = []
    index = _make_index(ent)
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[
            ExtractedEntity(
                existing_id="e_bro",
                name="哥哥",
                type="character",
                importance="major",
                aliases=[],
                attrs=[ExtractedAttr(key="age", value="20", confidence=0.8)],
            )
        ],
    )

    _apply_extraction(extraction, scene2, entities, relations, index, stats)

    assert len(ent.attrs) == 1


def test_apply_attr_new_key():
    scene1 = _make_scene(idx=0)
    scene2 = _make_scene(idx=1)
    ent = _make_entity("哥哥", entity_id="e_bro")
    ent.attrs.append(EntityAttr(key="age", value="20", source_scene=scene1.id))
    entities: list[Entity] = [ent]
    relations: list[Relation] = []
    index = _make_index(ent)
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[
            ExtractedEntity(
                existing_id="e_bro",
                name="哥哥",
                type="character",
                importance="major",
                aliases=[],
                attrs=[ExtractedAttr(key="hair", value="黑发", confidence=0.7)],
            )
        ],
    )

    _apply_extraction(extraction, scene2, entities, relations, index, stats)

    assert len(ent.attrs) == 2
    assert any(a.key == "hair" for a in ent.attrs)


def test_apply_existing_id_not_found_fallback_to_new():
    scene = _make_scene()
    entities: list[Entity] = []
    relations: list[Relation] = []
    index = WorkIndex()
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[
            ExtractedEntity(
                existing_id="e_nonexistent",
                name="新角色",
                type="character",
                importance="minor",
            )
        ],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(entities) == 1
    assert entities[0].name == "新角色"
    assert stats.entities_created == 1
    assert index.entity_name_to_id["新角色"] == entities[0].id


# ───────────────────────────────────────────────────────────────────────────────
# _apply_extraction — 关系
# ───────────────────────────────────────────────────────────────────────────────


def test_apply_relation_basic():
    scene = _make_scene()
    ent1 = _make_entity("哥哥", entity_id="e1")
    ent2 = _make_entity("妹妹", entity_id="e2")
    entities: list[Entity] = [ent1, ent2]
    relations: list[Relation] = []
    index = _make_index(ent1, ent2)
    stats = S2Stats()

    extraction = BibleExtraction(
        entities=[],
        relations=[ExtractedRelation(subject_name="哥哥", object_name="妹妹", relation="兄妹")],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(relations) == 1
    assert relations[0].subject_id == "e1"
    assert relations[0].object_id == "e2"
    assert relations[0].relation == "兄妹"
    assert stats.relations_created == 1
    assert "e1" in index.scene_to_entities[scene.id]
    assert "e2" in index.scene_to_entities[scene.id]


def test_apply_relation_by_alias():
    scene = _make_scene()
    ent1 = _make_entity("哥哥", entity_id="e1", aliases=["我"])
    ent2 = _make_entity("妹妹", entity_id="e2")
    entities: list[Entity] = [ent1, ent2]
    relations: list[Relation] = []
    index = _make_index(ent1, ent2)
    stats = S2Stats()

    extraction = BibleExtraction(
        relations=[ExtractedRelation(subject_name="我", object_name="妹妹", relation="保护")],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(relations) == 1
    assert relations[0].subject_id == "e1"


def test_apply_relation_self_rejected():
    scene = _make_scene()
    ent1 = _make_entity("哥哥", entity_id="e1")
    entities: list[Entity] = [ent1]
    relations: list[Relation] = []
    index = _make_index(ent1)
    stats = S2Stats()

    extraction = BibleExtraction(
        relations=[ExtractedRelation(subject_name="哥哥", object_name="哥哥", relation="思考")],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(relations) == 0


def test_apply_relation_unknown_name_skipped():
    scene = _make_scene()
    ent1 = _make_entity("哥哥", entity_id="e1")
    entities: list[Entity] = [ent1]
    relations: list[Relation] = []
    index = _make_index(ent1)
    stats = S2Stats()

    extraction = BibleExtraction(
        relations=[ExtractedRelation(subject_name="哥哥", object_name="神秘人", relation="未知")],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(relations) == 0


def test_apply_relation_dedup():
    scene1 = _make_scene(idx=0)
    scene2 = _make_scene(idx=1)
    ent1 = _make_entity("哥哥", entity_id="e1")
    ent2 = _make_entity("妹妹", entity_id="e2")
    entities: list[Entity] = [ent1, ent2]

    existing_rel = Relation(id="r0", subject_id="e1", object_id="e2", relation="兄妹")
    relations: list[Relation] = [existing_rel]
    index = _make_index(ent1, ent2)
    stats = S2Stats()

    extraction = BibleExtraction(
        relations=[ExtractedRelation(subject_name="哥哥", object_name="妹妹", relation="兄妹")],
    )

    _apply_extraction(extraction, scene2, entities, relations, index, stats)

    assert len(relations) == 1
    assert stats.relations_created == 0


def test_apply_different_relation_types():
    scene = _make_scene()
    ent1 = _make_entity("哥哥", entity_id="e1")
    ent2 = _make_entity("妹妹", entity_id="e2")
    entities: list[Entity] = [ent1, ent2]
    relations: list[Relation] = []
    index = _make_index(ent1, ent2)
    stats = S2Stats()

    extraction = BibleExtraction(
        relations=[
            ExtractedRelation(subject_name="哥哥", object_name="妹妹", relation="兄妹"),
            ExtractedRelation(subject_name="哥哥", object_name="妹妹", relation="保护"),
        ],
    )

    _apply_extraction(extraction, scene, entities, relations, index, stats)

    assert len(relations) == 2
    assert stats.relations_created == 2


# ───────────────────────────────────────────────────────────────────────────────
# format_known_entities
# ───────────────────────────────────────────────────────────────────────────────


def test_format_known_empty():
    result = format_known_entities([])
    assert "空" in result


def test_format_known_major_first():
    ent_majoror = _make_entity("哥哥", entity_id="e1", importance="major")
    ent_minor = _make_entity("路人", entity_id="e2", importance="minor")
    result = format_known_entities([ent_minor, ent_majoror])
    lines = result.strip().split("\n")
    assert "哥哥" in lines[0]


def test_format_known_truncation():
    entities = [_make_entity(f"角色{i}", entity_id=f"e{i}", importance="minor") for i in range(250)]
    result = format_known_entities(entities, max_display=100)
    assert "250" in result
    assert "仅展示" in result


# ───────────────────────────────────────────────────────────────────────────────
# scene_to_entities tracking（跨场景）
# ───────────────────────────────────────────────────────────────────────────────


def test_scene_to_entities_tracking():
    scene1 = _make_scene(idx=0)
    scene2 = _make_scene(idx=1)
    ent = _make_entity("哥哥", entity_id="e1")
    entities: list[Entity] = [ent]
    relations: list[Relation] = []
    index = _make_index(ent)
    stats = S2Stats()

    extraction1 = BibleExtraction(
        entities=[ExtractedEntity(existing_id="e1", name="哥哥", type="character")],
    )
    extraction2 = BibleExtraction(
        entities=[ExtractedEntity(existing_id="e1", name="我", type="character")],
    )

    _apply_extraction(extraction1, scene1, entities, relations, index, stats)
    _apply_extraction(extraction2, scene2, entities, relations, index, stats)

    assert ent.id in index.scene_to_entities[scene1.id]
    assert ent.id in index.scene_to_entities[scene2.id]
    assert "我" in ent.aliases


# ───────────────────────────────────────────────────────────────────────────────
# store round-trip: save_entities / save_relations
# ───────────────────────────────────────────────────────────────────────────────


def test_save_entities_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from manga_manager import config, store

    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path))
    work = store.create_work("测试作品")
    wid = work.id

    ent1 = _make_entity("哥哥", entity_id="e1", entity_type="character")
    ent2 = _make_entity("学校", entity_id="e2", entity_type="location")
    ent3 = _make_entity("手机", entity_id="e3", entity_type="prop")

    store.save_entities(wid, [ent1, ent2, ent3])

    chars = store.read_model_list(store.work_dir(wid) / "entities" / "characters.json", Entity)
    locs = store.read_model_list(store.work_dir(wid) / "entities" / "locations.json", Entity)
    props = store.read_model_list(store.work_dir(wid) / "entities" / "props.json", Entity)

    assert len(chars) == 1 and chars[0].name == "哥哥"
    assert len(locs) == 1 and locs[0].name == "学校"
    assert len(props) == 1 and props[0].name == "手机"


def test_save_relations_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from manga_manager import config, store

    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path))
    work = store.create_work("测试关系")
    wid = work.id

    rel = Relation(id="r0", subject_id="e1", object_id="e2", relation="兄妹")
    store.save_relations(wid, [rel])

    loaded = store.load_relations(wid)
    assert len(loaded) == 1
    assert loaded[0].relation == "兄妹"
