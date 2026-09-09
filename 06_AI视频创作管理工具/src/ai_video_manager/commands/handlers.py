from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import json

from ai_video_manager.api.app_helpers import normalize_script_format_decision
from ai_video_manager.api.config import _load_api_config, _test_llm_connection, _test_video_connection
from ai_video_manager.api.utils import _strategy
from ai_video_manager.api.schemas import GenerateVideoRequest
from ai_video_manager.api.video_submit import build_video_task_from_generate_request
from ai_video_manager.api.video_tasks import _ensure_video_generation_allowed, _run_and_store_video_task
from ai_video_manager.application.ai_runs import TrackedLLMClient
from ai_video_manager.llm import build_llm_client, llm_use_case_config
from ai_video_manager.models import EntityCard, EntityType, Project, PromptCard, PromptCategory, PromptTemplate
from ai_video_manager.prompt_engine import request_template_for_category, template_context
from ai_video_manager.prompt_pipeline import (
    build_prompt_cards_from_script,
    entity_catalog_json,
    prompt_card_target_json,
    prompt_card_with_inferred_source,
    prompt_cards_context_json,
    rerun_prompt_card_from_script,
)
from ai_video_manager.project_bundle import resolve_project_data_root


def project_list(ctx, args):
    return {"projects": [project for project in ctx.store.list_projects() for project in [_dump(project)]]}


def agent_result_read(ctx, args):
    result_ref = str(args.get("result_ref") or "").strip()
    prefix = "agent-result://"
    if not result_ref.startswith(prefix):
        raise ValueError("result_ref 必须使用 agent-result://run_id/tool_call_id 格式")
    parts = result_ref[len(prefix):].split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("result_ref 缺少 run_id 或 tool_call_id")
    run_id, call_id = parts
    repository = ctx.services.workflow_agent.repository
    call = repository.get_tool_call(call_id)
    if str(call.get("run_id") or "") != run_id:
        raise ValueError("工具结果引用与运行不匹配")
    run = repository.get_run(run_id)
    thread = repository.get_thread(run["thread_id"])
    if str(thread.get("project_id") or "") != str(args["project_id"]):
        raise ValueError("不得跨项目读取 Agent 工具结果")
    try:
        offset = max(0, int(args.get("offset") or 0))
        max_chars = min(12000, max(1, int(args.get("max_chars") or 12000)))
    except (TypeError, ValueError):
        offset, max_chars = 0, 12000
    serialized = json.dumps(call.get("result"), ensure_ascii=False, default=str)
    content = serialized[offset: offset + max_chars]
    next_offset = offset + len(content)
    return {
        "result_ref": result_ref,
        "content": content,
        "offset": offset,
        "next_offset": next_offset if next_offset < len(serialized) else None,
        "total_chars": len(serialized),
    }


def project_show(ctx, args):
    project_id = args["project_id"]
    return {"project": _dump(ctx.store.get_project(project_id)), "workspace": ctx.domain.get_workspace_view(project_id)}


def project_create(ctx, args):
    project = ctx.store.save_project(
        Project(name=str(args["name"]).strip(), category=str(args.get("category") or "active"), description=str(args.get("description") or ""))
    )
    return {"project": _dump(project)}


def project_update(ctx, args):
    project = ctx.store.update_project(
        args["project_id"], name=args.get("name"), category=args.get("category"), description=args.get("description")
    )
    return {"project": _dump(project)}


def project_settings_update(ctx, args):
    project_id = args["project_id"]
    workspace = ctx.domain.update_settings(
        project_id,
        expected_total_duration_seconds=args.get("expected_total_duration_seconds"),
        default_aspect_ratio=args.get("default_aspect_ratio"),
        default_video_duration=args.get("default_video_duration"),
        default_video_model=args.get("default_video_model"),
        default_resolution=args.get("default_resolution"),
        project_style_prompt=args.get("project_style_prompt"),
        output_root=args.get("output_root"),
        source_assets_root=args.get("source_assets_root"),
        data_root=args.get("data_root"),
        revision=args.get("revision"),
    )
    return {"workspace": workspace}


def project_delete(ctx, args):
    return {"project": _dump(ctx.store.delete_project(args["project_id"]))}


def workspace_show(ctx, args):
    return ctx.domain.get_workspace_view(args["project_id"])


def document_import(ctx, args):
    project_id = args["project_id"]
    path = Path(args["path"]).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    document = ctx.services.document_processor.load_document(path, project_id)
    relative_path = ctx.store.save_original_file(project_id, path.name, path.read_bytes())
    ctx.store.save_document(document)
    workspace = ctx.domain.reset_on_document_upload(
        project_id,
        document_text=document.content,
        document_file={"path": relative_path, "filename": document.filename, "format": document.format.value},
    )
    return {"document": _dump(document), "path": relative_path, "workspace": workspace}


def preprocess_split(ctx, args):
    project_id = args["project_id"]
    workspace = ctx.domain.get_workspace_view(project_id)
    content = str(args.get("content") or workspace.get("documentText") or "")
    strategy_name = str(args.get("strategy") or workspace.get("splitStrategy") or "chapter")
    llm_client = None
    if strategy_name in {"duration", "duration_2min"}:
        llm_client = ctx.services.duration_split_client(ctx.user_id or "cli", project_id)
    strategy = _strategy(
        strategy_name,
        int(args.get("max_chars") or 1200),
        llm_client=llm_client,
        custom_pattern=args.get("custom_pattern"),
        duration_minutes=float(args.get("duration_minutes") or workspace.get("durationMinutes") or 2),
    )
    document = ctx.services.document_processor.load_document_from_text(content, project_id=project_id)
    segments = ctx.services.document_processor.split_document(document, strategy)
    result = ctx.domain.apply_split_persist(project_id, segments, split_strategy=strategy_name)
    ctx.store.replace_project_document_segments(project_id=project_id, document=document, segments=segments)
    return {"segments": [_dump(segment) for segment in segments], **result}


def segment_list(ctx, args):
    return {"segments": ctx.store.list_project_segments(args["project_id"]), "revision": ctx.domain.get_workspace_view(args["project_id"]).get("revision", 0)}


def segment_show(ctx, args):
    segment_id = args["segment_id"]
    segment = next((item for item in ctx.store.list_project_segments(args["project_id"]) if item["id"] == segment_id), None)
    if segment is None:
        raise KeyError(f"Segment not found: {segment_id}")
    return {"segment": segment, "script": next((item for item in ctx.store.list_project_scripts(args["project_id"]) if item["segment_id"] == segment_id), None)}


def segment_update(ctx, args):
    project_id = args["project_id"]
    segments = ctx.store.list_project_segments(project_id)
    target = next((item for item in segments if item["id"] == args["segment_id"]), None)
    if target is None:
        raise KeyError(f"Segment not found: {args['segment_id']}")
    if "title" in args and args["title"] is not None:
        target["title"] = str(args["title"])
    if "content" in args and args["content"] is not None:
        target["content"] = str(args["content"])
    return {"workspace": ctx.domain.replace_segments(project_id, segments, revision=args.get("revision"))}


def segment_reorder(ctx, args):
    ids = args.get("segment_ids") or args.get("ids") or []
    if isinstance(ids, str):
        ids = [item.strip() for item in ids.split(",") if item.strip()]
    segments = {item["id"]: item for item in ctx.store.list_project_segments(args["project_id"])}
    ordered = [segments[item] for item in ids if item in segments]
    ordered.extend(item for item in segments.values() if item["id"] not in {value["id"] for value in ordered})
    for index, item in enumerate(ordered, 1):
        item["order"] = index
        if not item.get("title") or str(item["title"]).strip() == f"第{index - 1}集":
            item["title"] = f"第{index}集"
    return {"workspace": ctx.domain.replace_segments(args["project_id"], ordered, revision=args.get("revision"))}


def segment_delete(ctx, args):
    project_id = args["project_id"]
    remaining = [item for item in ctx.store.list_project_segments(project_id) if item["id"] != args["segment_id"]]
    return {"workspace": ctx.domain.replace_segments(project_id, remaining, clear_downstream=False, revision=args.get("revision"))}


def script_show(ctx, args):
    scripts = ctx.store.list_project_scripts(args["project_id"])
    segment_id = str(args.get("segment_id") or "").strip()
    if segment_id:
        scripts = [item for item in scripts if str(item.get("segment_id") or "") == segment_id]
    return {"scripts": scripts}


def file_list(ctx, args):
    project_id = args["project_id"]
    root = _project_data_root(ctx, project_id)
    relative_dir = _clean_project_relative_path(args.get("path") or "")
    target = root if not relative_dir else _resolve_project_file_path(root, relative_dir)
    if not target.exists():
        raise FileNotFoundError(relative_dir or ".")
    if not target.is_dir():
        raise ValueError(f"不是目录：{relative_dir or '.'}")
    try:
        limit = min(1000, max(1, int(args.get("limit") or 200)))
    except (TypeError, ValueError):
        limit = 200
    files = []
    for path in sorted(target.rglob("*")):
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        relative = path.relative_to(root).as_posix()
        files.append({"path": relative, "bytes": path.stat().st_size, "suffix": path.suffix.lower()})
        if len(files) >= limit:
            break
    return {"root": str(root), "path": relative_dir, "files": files, "truncated": len(files) >= limit}


def file_read(ctx, args):
    project_id = args["project_id"]
    root = _project_data_root(ctx, project_id)
    relative_path = _clean_project_relative_path(args.get("path") or "")
    if not relative_path:
        raise ValueError("file.read 需要项目内相对文件路径")
    path = _resolve_project_file_path(root, relative_path)
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    try:
        max_chars = min(100000, max(1, int(args.get("max_chars") or 50000)))
    except (TypeError, ValueError):
        max_chars = 50000
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError(f"只支持读取文本文件：{relative_path}")
    text = raw.decode("utf-8")
    return {"path": relative_path, "bytes": len(raw), "content": text[:max_chars], "truncated": len(text) > max_chars}


def file_write(ctx, args):
    project_id = args["project_id"]
    root = _project_data_root(ctx, project_id)
    relative_path = _clean_project_relative_path(args.get("path") or "")
    if not relative_path:
        raise ValueError("file.write 需要项目内相对文件路径")
    content = str(args.get("content") or "")
    encoded = content.encode("utf-8")
    if len(encoded) > 2 * 1024 * 1024:
        raise ValueError("单次写入最多 2MB")
    path = _resolve_project_file_path(root, relative_path)
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return {"path": relative_path, "bytes": len(encoded), "overwritten": existed}


def script_save(ctx, args):
    validation = ctx.services.document_processor.validate_script(str(args.get("content") or ""))
    return {"workspace": ctx.domain.save_segment_script(args["project_id"], args["segment_id"], content=str(args.get("content") or ""), validation=_dump(validation), revision=args.get("revision"))}


def script_convert(ctx, args):
    project_id = args["project_id"]
    segment_id = args["segment_id"]
    segment = next((item for item in ctx.store.list_project_segments(project_id) if item["id"] == segment_id), None)
    if segment is None:
        raise KeyError(f"Segment not found: {segment_id}")
    decision = normalize_script_format_decision(args.get("source_format"))
    if decision not in {"script", "source_text"}:
        raise ValueError("source_format 必须是 script（直接转存）或 source（LLM 转写）")
    content = str(args.get("content") or segment.get("content") or "")
    if decision == "script":
        script_content = content.strip()
    else:
        config = _load_api_config(ctx.store, user_id=ctx.user_id)
        use_config = llm_use_case_config(config, "script_convert")
        template = request_template_for_category(ctx.services.prompt_engine, "script_convert", args.get("template_id"))
        prompt = ctx.services.prompt_engine.render_prompt(
            template,
            template_context(
                template,
                {
                    "content_type": args.get("content_type") or "分集原文",
                    "content": content,
                    "project_style_prompt": ctx.store.get_project_style_prompt(project_id),
                },
            ),
        )
        client = TrackedLLMClient(
            build_llm_client(config, "script_convert"),
            ctx.services.production_repository,
            "script_convert",
            project_id,
            episode_id=segment_id,
            template_id=template.id,
            template_version=template.version,
        )
        script_content = client.complete(
            prompt,
            temperature=float(use_config.get("temperature") or 0.2),
            max_tokens=int(use_config.get("maxTokens") or 100000),
        )
    validation = ctx.services.document_processor.validate_script(script_content)
    workspace = ctx.domain.save_segment_script(
        project_id,
        segment_id,
        content=script_content,
        validation=_dump(validation),
        revision=args.get("revision"),
    )
    return {"workspace": workspace, "source_format": decision}


def asset_list(ctx, args):
    return {"assets": ctx.store.list_assets(args["project_id"])}


def asset_import(ctx, args):
    project_id = args["project_id"]
    paths = args.get("paths") or args.get("path") or []
    if isinstance(paths, str):
        paths = [paths]
    imported = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if path.is_file():
            imported.append(ctx.store.save_asset(project_id, _asset_type(path), path.name, path.read_bytes()))
    return {"paths": imported, "assets": ctx.store.list_assets(project_id)}


def asset_rename(ctx, args):
    return {"asset": ctx.store.rename_asset(args["project_id"], args["asset_path"], args["filename"])}


def asset_delete(ctx, args):
    ctx.store.delete_project_file(args["project_id"], args["asset_path"])
    return {"deleted": True, "asset_path": args["asset_path"]}


def entity_list(ctx, args):
    return {"cards": [_dump(card) for card in ctx.store.list_entity_cards(args["project_id"])]}


def entity_show(ctx, args):
    return {"card": _dump(ctx.store.get_entity_card(args["project_id"], args["entity_id"]))}


def entity_create(ctx, args):
    card = EntityCard(project_id=args["project_id"], entity_name=args["name"], type=EntityType(args["type"]), state=args.get("state") or "", tags=args.get("tags") or [])
    return {"card": _dump(ctx.store.save_entity_card(args["project_id"], card))}


def entity_update(ctx, args):
    existing = ctx.store.get_entity_card(args["project_id"], args["entity_id"])
    existing.entity_name = str(args.get("name") or existing.entity_name)
    if args.get("type"):
        existing.type = EntityType(args["type"])
    if args.get("state") is not None:
        existing.state = str(args["state"])
    if args.get("tags") is not None:
        existing.tags = args["tags"] if isinstance(args["tags"], list) else str(args["tags"]).split(",")
    return {"card": _dump(ctx.store.save_entity_card(args["project_id"], existing))}


def entity_delete(ctx, args):
    ctx.store.remove_entity_card_bindings(args["project_id"], args["entity_id"])
    ctx.store.delete_entity_card(args["project_id"], args["entity_id"])
    return {"deleted": True, "entity_id": args["entity_id"]}


def prompt_template_list(ctx, args):
    return {"templates": [_dump(item) for item in ctx.store.list_prompt_templates()]}


def prompt_template_show(ctx, args):
    return {"template": _dump(ctx.services.prompt_engine.load_template(args["template_id"])), "versions": ctx.store.list_prompt_template_versions(args["template_id"])}


def prompt_template_save(ctx, args):
    category = PromptCategory(str(args["category"]))
    template = PromptTemplate(id=str(args.get("template_id") or ""), name=args["name"], category=category, template=args["template"], variables=[])
    prepared = ctx.services.prompt_engine.prepare_template(template)
    ctx.services.prompt_engine.validate_template(prepared)
    saved = ctx.store.save_prompt_template(prepared)
    ctx.services.prompt_engine.load_template_record(saved)
    return {"template": _dump(saved)}


def prompt_template_delete(ctx, args):
    ctx.store.delete_prompt_template(args["template_id"])
    ctx.services.prompt_engine.delete_template(args["template_id"])
    return {"deleted": True, "template_id": args["template_id"]}


def prompt_template_versions(ctx, args):
    return {"versions": ctx.store.list_prompt_template_versions(args["template_id"])}


def prompt_card_list(ctx, args):
    return {"cards": [_dump(card) for card in ctx.store.list_prompt_cards(args["project_id"], args.get("segment_id"))]}


def prompt_card_show(ctx, args):
    return {"card": _dump(ctx.store.get_prompt_card(args["card_id"])), "versions": ctx.store.list_prompt_card_versions(args["card_id"])}


def prompt_card_update(ctx, args):
    existing = ctx.store.get_prompt_card(args["card_id"])
    if existing.locked:
        raise ValueError("提示词卡片已锁定，请先解锁")
    card = PromptCard(
        id=existing.id,
        project_id=existing.project_id,
        segment_id=existing.segment_id,
        order=existing.order,
        title=str(args.get("title") or existing.title),
        prompt_text=str(args.get("prompt_text") if args.get("prompt_text") is not None else existing.prompt_text),
        anchor_text=str(args.get("anchor_text") if args.get("anchor_text") is not None else existing.anchor_text),
        duration=float(args.get("duration") if args.get("duration") is not None else existing.duration),
        source_text=existing.source_text,
        source_start=existing.source_start,
        source_end=existing.source_end,
        source_hash=existing.source_hash,
        status=str(args.get("status") or existing.status),
        locked=existing.locked,
        created_at=existing.created_at,
    )
    return {"card": _dump(ctx.store.save_prompt_card_with_version(card, "edited"))}


def prompt_card_lock(ctx, args):
    card = ctx.store.get_prompt_card(args["card_id"])
    card.locked = bool(args.get("locked", True))
    return {"card": _dump(ctx.store.save_prompt_card(card))}


def prompt_card_delete(ctx, args):
    card = ctx.store.get_prompt_card(args["card_id"])
    if card.locked:
        raise ValueError("提示词卡片已锁定，请先解锁")
    ctx.store.delete_prompt_card(args["card_id"])
    return {"deleted": True, "card_id": args["card_id"]}


def prompt_card_generate(ctx, args):
    project_id = args["project_id"]
    segment_id = args["segment_id"]
    workspace = ctx.domain.get_workspace_view(project_id)
    script = str(args.get("script") or workspace.get("scripts", {}).get(segment_id) or "")
    if not script.strip():
        raise ValueError("当前集没有剧本原文，无法生成提示词")
    config = _load_api_config(ctx.store, user_id=ctx.user_id)
    split_config = llm_use_case_config(config, "prompt_split")
    write_config = llm_use_case_config(config, "video_generate")
    split_template = request_template_for_category(ctx.services.prompt_engine, "prompt_split", None)
    write_template = request_template_for_category(ctx.services.prompt_engine, "video_generate", args.get("template_id"))
    entities = ctx.store.list_entity_cards(project_id)
    duration = float(args.get("max_duration_seconds") or 15)
    style = ctx.store.get_project_style_prompt(project_id)
    split_prompt = ctx.services.prompt_engine.render_prompt(
        split_template,
        template_context(split_template, {
            "script": script,
            "entity_catalog": entity_catalog_json(entities),
            "max_duration_seconds": duration,
            "expected_total_duration_seconds": args.get("expected_total_duration_seconds") or "",
            "project_style_prompt": style,
        }),
    )

    def render_write(values):
        return ctx.services.prompt_engine.render_prompt(
            write_template,
            template_context(write_template, {**values, "project_style_prompt": style}),
        )

    cards = build_prompt_cards_from_script(
        project_id=project_id,
        segment_id=segment_id,
        script=script,
        entity_cards=entities,
        split_llm_client=TrackedLLMClient(build_llm_client(config, "prompt_split"), ctx.services.production_repository, "prompt_split", project_id, episode_id=segment_id, template_id=split_template.id, template_version=split_template.version),
        write_llm_client=TrackedLLMClient(build_llm_client(config, "video_generate"), ctx.services.production_repository, "video_generate", project_id, episode_id=segment_id, template_id=write_template.id, template_version=write_template.version),
        split_prompt=split_prompt,
        write_prompt_renderer=render_write,
        max_duration_seconds=duration,
        temperature_split=float(split_config.get("temperature") or 0.3),
        temperature_write=float(write_config.get("temperature") or 0.6),
        max_tokens_split=int(split_config.get("maxTokens") or 100000),
        max_tokens_write=int(write_config.get("maxTokens") or 100000),
    )
    saved = ctx.store.save_prompt_cards(project_id, segment_id, cards, replace=bool(args.get("replace", True)))
    return {"cards": [_dump(card) for card in saved], "total_duration": sum(float(card.duration or 0) for card in saved)}


def prompt_card_rerun(ctx, args):
    card = ctx.store.get_prompt_card(args["card_id"])
    if card.locked:
        raise ValueError("提示词卡片已锁定，请先解锁")
    workspace = ctx.domain.get_workspace_view(card.project_id)
    script = str(args.get("script") or workspace.get("scripts", {}).get(card.segment_id) or "")
    config = _load_api_config(ctx.store, user_id=ctx.user_id)
    use_config = llm_use_case_config(config, "prompt_rerun")
    template = request_template_for_category(ctx.services.prompt_engine, "prompt_rerun", args.get("template_id"))
    cards = ctx.store.list_prompt_cards(card.project_id, card.segment_id)
    target = prompt_card_with_inferred_source(card, script, len(cards))
    duration = float(args.get("max_duration_seconds") or 15)
    rendered = ctx.services.prompt_engine.render_prompt(
        template,
        template_context(template, {
            "script_excerpt": target.source_text,
            "script": script,
            "entity_catalog": entity_catalog_json(ctx.store.list_entity_cards(card.project_id)),
            "max_duration_seconds": duration,
            "target_card": prompt_card_target_json(target),
            "generated_context": prompt_cards_context_json(cards, target_card_id=card.id),
            "project_style_prompt": ctx.store.get_project_style_prompt(card.project_id),
        }),
    )
    updated = rerun_prompt_card_from_script(
        target_card=target,
        script=script,
        entity_cards=ctx.store.list_entity_cards(card.project_id),
        llm_client=TrackedLLMClient(build_llm_client(config, "prompt_rerun"), ctx.services.production_repository, "prompt_rerun", card.project_id, episode_id=card.segment_id, prompt_card_id=card.id, template_id=template.id, template_version=template.version),
        rendered_prompt=rendered,
        max_duration_seconds=duration,
        temperature=float(use_config.get("temperature") or 0.6),
        max_tokens=int(use_config.get("maxTokens") or 100000),
    )
    return {"card": _dump(ctx.store.save_prompt_card_with_version(updated, "rerun"))}


def video_task_list(ctx, args):
    return {"tasks": [_dump(task) for task in ctx.store.list_video_tasks(args["project_id"], segment_id=args.get("segment_id"))]}


def video_task_show(ctx, args):
    return {"task": _dump(ctx.store.get_video_task(args["task_id"]))}


def video_task_delete(ctx, args):
    ctx.store.delete_video_task(args["task_id"])
    return {"deleted": True, "task_id": args["task_id"]}


def video_request(ctx, args):
    config = _load_api_config(ctx.store, user_id=ctx.user_id)
    ctx.services.refresh_video_engine(config)
    body = GenerateVideoRequest(
        project_id=args["project_id"],
        segment_id=args["segment_id"],
        prompt=str(args.get("prompt") or ""),
        prompt_card_id=args.get("card_id"),
        model=args.get("model"),
        aspect_ratio=args.get("aspect_ratio"),
        resolution=args.get("resolution"),
        duration=int(args["duration"]) if args.get("duration") is not None else None,
        preview=bool(args.get("preview", False)),
    )
    card = ctx.store.get_prompt_card(body.prompt_card_id) if body.prompt_card_id else None
    prompt = card.prompt_text if card else body.prompt
    project = ctx.store.get_project(body.project_id)
    _ensure_video_generation_allowed(project, prompt, body.preview, ctx.services.checkpoint_manager)
    task = build_video_task_from_generate_request(
        ctx.store,
        body,
        provider=ctx.services.video_engine.provider,
        prompt=prompt,
        source_prompt_hash=card.source_hash if card else "",
        prompt_version=max(1, ctx.store.count_prompt_card_versions(card.id)) if card else 1,
        prompt_card=card,
    )
    result = asyncio.run(_run_and_store_video_task(task, body.preview, ctx.store, ctx.services.video_engine))
    return {"task": _dump(result)}


def config_show(ctx, args):
    config = _load_api_config(ctx.store, user_id=ctx.user_id)
    masked = dict(config)
    for key in ("llmApiKey", "videoApiKey", "imageApiKey"):
        masked[key] = "***" if masked.get(key) else ""
    return masked


def config_llm_test(ctx, args):
    return _test_llm_connection(ctx.store, str(args.get("use_case") or "script_convert"), user_id=ctx.user_id)


def config_video_test(ctx, args):
    return _test_video_connection(ctx.store, user_id=ctx.user_id)


def workflow_status(ctx, args):
    project_id = args["project_id"]
    project = ctx.store.get_project(project_id)
    workspace = ctx.domain.get_workspace_view(project_id)
    return {"project": _dump(project), "workflow": ctx.domain.workflow_ui(project_id, ctx.services.checkpoint_manager), "workspace": workspace}


def _project_data_root(ctx, project_id: str) -> Path:
    ctx.store.get_project(project_id)
    ctx.store.ensure_project_layout(project_id)
    return resolve_project_data_root(ctx.store, project_id).resolve()


def _clean_project_relative_path(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if raw in {"", "."}:
        return ""
    if raw.startswith("/") or Path(raw).is_absolute():
        raise ValueError("文件工具只接受当前项目数据目录内的相对路径")
    return raw.strip("/")


def _resolve_project_file_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise ValueError(f"路径越出当前项目数据目录：{relative_path}")
    return candidate


def _asset_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm", ".mkv"}:
        return "video"
    if suffix in {".mp3", ".wav", ".m4a", ".flac"}:
        return "audio"
    return "file"


def _dump(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return _dump(asdict(value))
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
