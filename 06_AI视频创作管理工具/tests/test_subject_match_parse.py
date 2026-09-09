import pytest

from ai_video_manager.api.video_assets import matched_prompt_card_entities
from ai_video_manager.llm import parse_json_list_payload
from ai_video_manager.models import EntityCard, EntityType, Project, PromptCard
from ai_video_manager.storage import SQLiteStore


def test_parse_json_list_payload_accepts_wrapper_object():
    raw = '{"matches":[{"entity_card_id":"card_abc123456789","reason":"主角"}]}'
    rows = parse_json_list_payload(raw)
    assert len(rows) == 1
    assert rows[0]["entity_card_id"] == "card_abc123456789"


def test_parse_json_list_payload_accepts_empty_wrapper():
    rows = parse_json_list_payload('{"matches":[]}')
    assert rows == []


def test_parse_json_list_payload_accepts_plain_array():
    raw = '[{"entity_card_id":"card_abc123456789","reason":"场景"}]'
    rows = parse_json_list_payload(raw)
    assert len(rows) == 1


def test_parse_json_list_payload_rejects_invalid_object():
    with pytest.raises(RuntimeError, match="LLM 返回格式无效"):
        parse_json_list_payload('{"status":"ok"}')


def test_prompt_card_entity_links_are_the_matching_source(tmp_path):
    store = SQLiteStore(tmp_path / "database" / "app.db", workspace_root=tmp_path)
    project = store.save_project(Project(name="match-links"))
    card = store.save_entity_card(
        project.id,
        EntityCard(project_id=project.id, entity_name="主角", type=EntityType.CHARACTER),
    )
    prompt_card = store.save_prompt_card(
        PromptCard(
            project_id=project.id,
            segment_id="ep_1",
            order=1,
            title="镜头1",
            prompt_text="主角入场",
            anchor_text="",
        )
    )
    store.replace_prompt_card_entity_links(
        project.id, prompt_card.id, [card.id], source="manual", confirmed=True
    )

    assert [item.id for item in matched_prompt_card_entities(store, prompt_card)] == [card.id]
    link = store.list_prompt_card_entity_links(project.id, prompt_card.id)[0]
    assert link["source"] == "manual"
    assert link["confirmed"] == 1
