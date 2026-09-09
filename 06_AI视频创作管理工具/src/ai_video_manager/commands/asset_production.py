from __future__ import annotations


def entity_profile_list(ctx, args):
    return {
        "profiles": ctx.services.asset_production_repository.list_profiles(
            args["project_id"]
        )
    }


def entity_profile_search(ctx, args):
    query = str(args.get("query") or "").strip().casefold()
    entity_type = str(args.get("type") or "").strip()
    try:
        limit = min(50, max(1, int(args.get("limit") or 10)))
    except (TypeError, ValueError):
        limit = 10
    profiles = ctx.services.asset_production_repository.list_profiles(args["project_id"])
    matches = []
    for profile in profiles:
        if entity_type and profile.get("type") != entity_type:
            continue
        name = str(profile.get("canonical_name") or "")
        aliases = [str(value) for value in profile.get("aliases") or []]
        folded_name = name.casefold()
        folded_aliases = [value.casefold() for value in aliases]
        if query:
            if folded_name == query:
                score = 0
            elif query in folded_aliases:
                score = 1
            elif folded_name.startswith(query) or any(
                value.startswith(query) for value in folded_aliases
            ):
                score = 2
            elif query in folded_name or any(query in value for value in folded_aliases):
                score = 3
            else:
                continue
        else:
            score = 4
        matches.append(
            {
                "score": score,
                "id": profile.get("id"),
                "name": name,
                "type": profile.get("type"),
                "aliases": aliases[:10],
                "status": profile.get("status"),
                "has_setting": bool(str(profile.get("setting") or "").strip()),
            }
        )
    matches.sort(key=lambda item: (item["score"], item["name"]))
    return {
        "query": str(args.get("query") or ""),
        "matches": matches[:limit],
        "total": len(matches),
    }


def entity_profile_show(ctx, args):
    project_id = args["project_id"]
    profile_id = args["profile_id"]
    repository = ctx.services.asset_production_repository
    return {
        "profile": repository.get_profile(project_id, profile_id),
        "asset_prompts": repository.list_asset_prompts(project_id, profile_id),
        "visual_styles": repository.list_visual_styles(project_id),
        "presets": repository.list_presets(project_id),
        "image_tasks": [
            task
            for task in repository.list_image_tasks(project_id)
            if str(task.get("profile_id") or "") == profile_id
        ],
    }


def entity_profile_update(ctx, args):
    patch = {
        key: args[key]
        for key in (
            "canonical_name",
            "type",
            "aliases",
            "role",
            "importance",
            "setting",
            "status",
        )
        if key in args and args[key] is not None
    }
    return {
        "profile": ctx.services.asset_production_repository.update_profile(
            args["project_id"], args["profile_id"], patch
        )
    }


def visual_style_list(ctx, args):
    return {
        "styles": ctx.services.asset_production_repository.list_visual_styles(
            args["project_id"]
        )
    }


def visual_style_save(ctx, args):
    name = str(args.get("name") or "").strip()
    if not name:
        raise ValueError("视觉风格名称不能为空")
    reference_asset_ids = args.get("reference_asset_ids") or []
    if isinstance(reference_asset_ids, str):
        reference_asset_ids = [
            item.strip() for item in reference_asset_ids.split(",") if item.strip()
        ]
    style = ctx.services.asset_production_repository.save_visual_style(
        args["project_id"],
        {
            "name": name,
            "prompt": str(args.get("prompt") or ""),
            "negative_prompt": str(args.get("negative_prompt") or ""),
            "reference_asset_ids": list(dict.fromkeys(reference_asset_ids)),
            "is_active": bool(args.get("is_active", True)),
        },
        str(args.get("style_id") or "").strip() or None,
    )
    return {"style": style}


def visual_style_delete(ctx, args):
    ctx.services.asset_production_repository.delete_visual_style(
        args["project_id"], args["style_id"]
    )
    return {"deleted": True, "style_id": args["style_id"]}


def entity_extract(ctx, args):
    segment_ids = args.get("segment_ids") or None
    if isinstance(segment_ids, str):
        segment_ids = [item.strip() for item in segment_ids.split(",") if item.strip()]
    return ctx.services.entity_asset_service.analyze(
        args["project_id"], ctx.user_id or "cli", episode_ids=segment_ids
    )


def entity_generate_setting(ctx, args):
    return ctx.services.entity_asset_service.generate_setting(
        args["project_id"], args["profile_id"], ctx.user_id or "cli"
    )


def entity_generate_asset_prompt(ctx, args):
    return ctx.services.entity_asset_service.generate_asset_prompt(
        args["project_id"],
        args["profile_id"],
        ctx.user_id or "cli",
        variant_id=args.get("variant_id"),
        view_type=str(args.get("view_type") or ""),
    )


def entity_generate_images(ctx, args):
    return ctx.services.entity_asset_service.generate_images(
        args["project_id"], ctx.user_id or "cli", args["asset_prompt_id"]
    )


def entity_adopt_image(ctx, args):
    return ctx.services.entity_asset_service.adopt_output(
        args["project_id"], args["output_id"]
    )
