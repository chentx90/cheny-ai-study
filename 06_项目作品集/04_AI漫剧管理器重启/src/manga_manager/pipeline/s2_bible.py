"""S2 设定库管线。

设计要点：
  - LLM 调用（I/O 密集）与状态合并（CPU 密集/确定性）分离。
  - 集内场景可并行调 LLM（ThreadPoolExecutor），合并阶段串行执行。
  - 并行调用时，LLM 拿到的是当前 entity list 的快照；合并前通过
    _reassign_existing_ids 修正，保证串行合并的正确性。
  - 每集完成即 checkpoint 写磁盘；断点续跑读 run_state.cursor["done_scenes"]。
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from manga_manager.agents.bible_builder import (
    BibleBuilderError,
    BibleExtraction,
    ExtractedEntity,
    ExtractedRelation,
    ExtractedVariant,
    call_bible_builder,
)
from manga_manager.models import (
    ArtifactStatus,
    Entity,
    EntityAttr,
    EntityVariant,
    Importance,
    Relation,
    RunState,
    Scene,
    WorkIndex,
)
from manga_manager import store


DEFAULT_WORKERS = 4


@dataclass
class S2Stats:
    total_scenes: int = 0
    scenes_processed: int = 0
    entities_created: int = 0
    entities_merged: int = 0
    relations_created: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    final_count: int = 0
    final_major_count: int = 0


def _resolve_name(
    name: str,
    entity_name_to_id: dict[str, str],
    alias_to_id: dict[str, str],
) -> str | None:
    if not name:
        return None
    found = entity_name_to_id.get(name)
    if found:
        return found
    return alias_to_id.get(name)


def _add_to_scene(index: WorkIndex, scene_id: str, entity_id: str) -> None:
    present = set(index.scene_to_entities.get(scene_id, []))
    present.add(entity_id)
    index.scene_to_entities[scene_id] = sorted(present)


def _apply_extraction(
    extraction: BibleExtraction,
    scene: Scene,
    entities: list[Entity],
    relations: list[Relation],
    index: WorkIndex,
    stats: S2Stats,
) -> None:
    id_to_entity: dict[str, Entity] = {e.id: e for e in entities}
    scene_id = scene.id

    for ext in extraction.entities:
        if ext.existing_id and ext.existing_id in id_to_entity:
            target = id_to_entity[ext.existing_id]
            merged = False

            target.appearance_count += 1

            if ext.name and ext.name != target.name and ext.name not in target.aliases:
                target.aliases.append(ext.name)
                index.alias_to_id[ext.name] = target.id
                merged = True

            for alias in ext.aliases:
                if alias and alias != target.name and alias not in target.aliases:
                    target.aliases.append(alias)
                    index.alias_to_id[alias] = target.id
                    merged = True

            if ext.importance == "major" and target.importance != Importance.major:
                target.importance = Importance.major
                merged = True

            existing_pair_keys = {(a.key, a.value[:30]) for a in target.attrs}
            for ea in ext.attrs:
                if not ea.key or not ea.value:
                    continue
                pair = (ea.key, ea.value[:30])
                if pair not in existing_pair_keys:
                    target.attrs.append(
                        EntityAttr(
                            key=ea.key,
                            value=ea.value,
                            source_scene=scene_id,
                            confidence=ea.confidence,
                        )
                    )
                    existing_pair_keys.add(pair)
                    merged = True

            existing_variant_labels = {v.label for v in target.variants}
            for ev in ext.variants:
                if ev.label and ev.label not in existing_variant_labels:
                    target.variants.append(
                        EntityVariant(
                            label=ev.label,
                            time_desc=ev.time_desc,
                            appearance=ev.appearance,
                        )
                    )
                    existing_variant_labels.add(ev.label)
                    merged = True

            _add_to_scene(index, scene_id, target.id)
            if merged:
                stats.entities_merged += 1
        else:
            entity_id = f"e{uuid.uuid4().hex[:8]}"
            valid_attrs = [
                EntityAttr(
                    key=ea.key,
                    value=ea.value,
                    source_scene=scene_id,
                    confidence=ea.confidence,
                )
                for ea in ext.attrs
                if ea.key and ea.value
            ]
            valid_variants = [
                EntityVariant(
                    label=ev.label,
                    time_desc=ev.time_desc,
                    appearance=ev.appearance,
                )
                for ev in ext.variants
                if ev.label and ev.appearance
            ]
            new_entity = Entity(
                id=entity_id,
                type=ext.type,
                name=ext.name,
                aliases=[a for a in ext.aliases if a and a != ext.name],
                importance=ext.importance,
                attrs=valid_attrs,
                variants=valid_variants,
                appearance_count=1,
            )
            entities.append(new_entity)
            id_to_entity[entity_id] = new_entity
            index.entity_name_to_id[ext.name] = entity_id
            for alias in ext.aliases:
                if alias and alias != ext.name:
                    index.alias_to_id[alias] = entity_id
            _add_to_scene(index, scene_id, entity_id)
            stats.entities_created += 1

    for ext_rel in extraction.relations:
        subj_id = _resolve_name(ext_rel.subject_name, index.entity_name_to_id, index.alias_to_id)
        obj_id = _resolve_name(ext_rel.object_name, index.entity_name_to_id, index.alias_to_id)
        if not subj_id or not obj_id or subj_id == obj_id:
            continue

        already = any(
            r.subject_id == subj_id and r.object_id == obj_id and r.relation == ext_rel.relation
            for r in relations
        )
        if not already:
            relations.append(
                Relation(
                    id=f"r{uuid.uuid4().hex[:8]}",
                    subject_id=subj_id,
                    object_id=obj_id,
                    relation=ext_rel.relation,
                    source_scene=scene_id,
                )
            )
            stats.relations_created += 1

        _add_to_scene(index, scene_id, subj_id)
        _add_to_scene(index, scene_id, obj_id)


def _call_scene_llm(
    scene: Scene,
    source: str,
    base_entities: list[Entity],
    llm: Any | None,
) -> tuple[str, BibleExtraction | None, str | None]:
    scene_text = source[scene.raw_span.start:scene.raw_span.end]
    scene_meta = {
        "time": scene.time,
        "location": scene.location,
        "pov": scene.pov,
        "summary": scene.summary,
    }
    try:
        extraction = call_bible_builder(
            scene_text,
            scene_meta=scene_meta,
            existing_entities=base_entities,
            llm=llm,
        )
        return (scene.id, extraction, None)
    except BibleBuilderError as exc:
        return (scene.id, None, str(exc))


def _reassign_existing_ids(
    extraction: BibleExtraction,
    index: WorkIndex,
) -> None:
    for ext in extraction.entities:
        if ext.existing_id is None:
            found = _resolve_name(ext.name, index.entity_name_to_id, index.alias_to_id)
            if found:
                ext.existing_id = found


def _postprocess_entities(entities: list[Entity]) -> int:
    """后处理：过滤一次性实体。

    规则：
    - major 实体保留（不降级）
    - 出场 ≥ 2 的实体保留
    - 出场 < 2 的非 major 实体降为 minor（不删除，保留信息）

    Returns:
        被降级的实体数。
    """
    demoted = 0
    for ent in entities:
        if ent.importance == "major":
            continue
        if ent.appearance_count < 2 and ent.importance != "minor":
            ent.importance = "minor"
            demoted += 1
    return demoted


@dataclass
class S2Result:
    entities: list[Entity]
    relations: list[Relation]
    stats: S2Stats
    scenes_skipped: int = 0

    @property
    def ok(self) -> bool:
        return not [e for e, _ in self.stats.errors]

    def summary_lines(self) -> list[str]:
        return [
            f"处理场景: {self.stats.scenes_processed}/{self.stats.total_scenes}"
            + (f" (跳过了 {self.scenes_skipped} 个已处理)" if self.scenes_skipped else ""),
            f"新建实体: {self.stats.entities_created}",
            f"合并属性: {self.stats.entities_merged}",
            f"新建关系: {self.stats.relations_created}",
            f"错误: {len(self.stats.errors)}",
            f"最终实体总数: {len(self.entities)}",
            f"最终关系总数: {len(self.relations)}",
        ]


def run_s2(
    work_id: str,
    *,
    llm: Any | None = None,
    max_workers: int = DEFAULT_WORKERS,
    on_scene_progress: Any | None = None,
    resume: bool = True,
) -> S2Result:
    source = store.get_source_text(work_id)
    episodes = store.load_episodes(work_id)
    if not episodes:
        raise BibleBuilderError("no episodes found; run S1 first")

    root = store.work_dir(work_id)
    entities: list[Entity] = store.load_entities(work_id)
    relations: list[Relation] = store.load_relations(work_id)
    index = store.read_model(root / "index.json", WorkIndex)

    rs = store.read_model(root / "run_state.json", RunState)
    done_scene_ids: set[str] = set(rs.cursor.get("done_scenes") or [])

    stats = S2Stats(total_scenes=sum(len(ep.scenes) for ep in episodes))
    scenes_skipped = 0

    for ep in episodes:
        pending = [s for s in ep.scenes if not (resume and s.id in done_scene_ids)]

        if resume:
            skipped_this_ep = sum(1 for s in ep.scenes if s.id in done_scene_ids)
            scenes_skipped += skipped_this_ep
            stats.scenes_processed += skipped_this_ep
            if skipped_this_ep and on_scene_progress:
                on_scene_progress(stats.scenes_processed, stats.total_scenes, ep.scenes[-1].id if ep.scenes else "")

        if not pending:
            continue

        for batch_start in range(0, len(pending), max_workers):
            batch = pending[batch_start:batch_start + max_workers]
            base_snapshot = list(entities)

            if max_workers <= 1 or len(batch) == 1:
                batch_results = [
                    _call_scene_llm(scene, source, base_snapshot, llm) for scene in batch
                ]
            else:
                with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                    future_to_scene = {
                        executor.submit(_call_scene_llm, scene, source, base_snapshot, llm): scene
                        for scene in batch
                    }
                    done_map: dict[str, tuple[str, BibleExtraction | None, str | None]] = {}
                    for f in as_completed(future_to_scene):
                        done_map[future_to_scene[f].id] = f.result()

                batch_results = [done_map[scene.id] for scene in batch]

            for scene_id, extraction, error in batch_results:
                scene = next(s for s in batch if s.id == scene_id)
                if error:
                    stats.errors.append((scene_id, error))
                else:
                    _reassign_existing_ids(extraction, index)
                    _apply_extraction(extraction, scene, entities, relations, index, stats)

                done_scene_ids.add(scene_id)
                stats.scenes_processed += 1
                if on_scene_progress:
                    on_scene_progress(stats.scenes_processed, stats.total_scenes, scene_id)

        rs.cursor["done_scenes"] = sorted(done_scene_ids)
        rs.updated_at = datetime.now().isoformat(timespec="seconds")
        store.write_json_atomic(root / "run_state.json", rs)
        store.save_entities(work_id, entities)
        store.save_relations(work_id, relations)
        store.write_json_atomic(root / "index.json", index)

    rs.stage = "M2"
    rs.status = ArtifactStatus.validated
    rs.updated_at = datetime.now().isoformat(timespec="seconds")
    store.write_json_atomic(root / "run_state.json", rs)

    demoted = _postprocess_entities(entities)
    store.save_entities(work_id, entities)
    store.save_relations(work_id, relations)
    store.write_json_atomic(root / "index.json", index)

    stats.final_count = len(entities)
    stats.final_major_count = sum(1 for e in entities if e.importance == "major")

    store.log_operation(
        work_id,
        "s2.built",
        detail=(
            f"{stats.entities_created} new, {stats.entities_merged} merged, "
            f"{stats.relations_created} relations, errors={len(stats.errors)}, "
            f"final={stats.final_count} (major={stats.final_major_count}, demoted={demoted})"
        ),
    )

    return S2Result(
        entities=entities, relations=relations, stats=stats, scenes_skipped=scenes_skipped
    )
