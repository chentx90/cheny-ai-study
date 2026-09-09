from pathlib import Path

from manga_manager.context import assemble_context
from manga_manager.models import Entity, EntityAttr, EntityVariant, StyleGuide, BindingFile, BindingItem
from manga_manager import store


def test_create_import_validate_and_log(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("测试作品")
    assert work.id.startswith("w")

    source = tmp_path / "source.txt"
    source.write_text("第一章\n少年上山。", encoding="utf-8")
    updated = store.import_source(work.id, source)
    assert updated.source_meta["chars"] == len("第一章\n少年上山。")

    report = store.validate_work(work.id)
    assert report.ok, report.issues
    operations = store.load_operations(work.id)
    assert [op.command for op in operations][:2] == ["source.import", "init"]


def test_validate_detects_index_divergence(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("索引测试")
    root = store.work_dir(work.id)
    (root / "index.json").write_text('{"entity_name_to_id":{"错":"e1"},"alias_to_id":{},"scene_to_entities":{},"shot_to_scene":{}}', encoding="utf-8")
    report = store.validate_work(work.id)
    assert not report.ok
    assert "index.json diverges" in report.issues[0].message
    fixed = store.validate_work(work.id, fix_index=True)
    assert fixed.ok


def test_bind_media_image_audio_video_and_collect_scene_media(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_DATA_DIR", str(tmp_path / "data"))
    work = store.create_work("媒体绑定")
    entity = Entity(
        id="e1",
        type="character",
        name="妹妹",
        variants=[EntityVariant(label="幼年妹妹", time_desc="", appearance="")],
    )
    store.save_entities(work.id, [entity])

    scene_id = "s00000_media"
    binding = BindingFile(
        scene_id=scene_id,
        bindings={"shot1": [BindingItem(entity_id="e1", variant_label="幼年妹妹")]},
    )
    store.write_json_atomic(store.work_dir(work.id) / "bindings" / f"{scene_id}.json", binding)

    image = tmp_path / "sister.png"
    audio = tmp_path / "sister.mp3"
    video = tmp_path / "sister.mp4"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")
    video.write_bytes(b"video")

    store.bind_ref_media(work.id, "e1", "幼年妹妹", image, "image")
    store.bind_ref_media(work.id, "e1", "幼年妹妹", audio, "audio")
    store.bind_ref_media(work.id, "e1", "幼年妹妹", video, "video")

    updated = store.load_entities(work.id)[0]
    variant = updated.variants[0]
    assert variant.ref_images == ["assets/e1/幼年妹妹.png"]
    assert Path(variant.ref_audios[0]).suffix == ".mp3"
    assert Path(variant.ref_videos[0]).suffix == ".mp4"

    bundle = store.collect_scene_media(work.id, scene_id)
    assert bundle.images[0].name == "幼年妹妹.png"
    assert bundle.audios[0].suffix == ".mp3"
    assert bundle.videos[0].suffix == ".mp4"


def test_context_budget_warns_when_oversized(monkeypatch):
    monkeypatch.setenv("MANGA_CONTEXT_MAX_TOKENS", "20")
    style = StyleGuide(narrative_style="叙事", visual_style="视觉")
    entity = Entity(
        id="e1",
        type="character",
        name="少年",
        attrs=[EntityAttr(key="appearance", value="黑发学生装")],
    )
    bundle = assemble_context(
        role_instruction="只做 schema 到 schema 的变换",
        style_guide=style,
        task_input="很长" * 200,
        schema_instruction="返回 JSON",
        entities=[entity],
        rolling_summary="摘要" * 100,
    )
    assert bundle.warnings
