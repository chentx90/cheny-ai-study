from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ai_video_manager.api.config import _load_api_config
from ai_video_manager.application.ai_runs import TrackedLLMClient
from ai_video_manager.image_generation import ImageGenerationError, build_image_client, image_gateway_ready
from ai_video_manager.infrastructure.db.asset_production_repository import AssetProductionRepository
from ai_video_manager.infrastructure.db.production_repository import ProductionRepository
from ai_video_manager.llm import build_llm_client, llm_use_case_config, parse_json_object
from ai_video_manager.models import EntityCard, EntityType
from ai_video_manager.prompt_engine import PromptEngine, template_for_category
from ai_video_manager.storage import SQLiteStore


ASSET_PROMPT_CATEGORY = {
    "character": "character_asset_prompt",
    "scene": "scene_asset_prompt",
    "prop": "prop_asset_prompt",
}


class EntityAssetService:
    def __init__(
        self,
        store: SQLiteStore,
        repository: AssetProductionRepository,
        production_repository: ProductionRepository,
        prompt_engine: PromptEngine,
    ) -> None:
        self.store = store
        self.repository = repository
        self.production_repository = production_repository
        self.prompt_engine = prompt_engine

    def analyze(
        self,
        project_id: str,
        user_id: str,
        episode_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        episodes = [
            episode for episode in self.production_repository.list_episodes(project_id)
            if episode.script_text.strip() and (not episode_ids or episode.id in set(episode_ids))
        ]
        if not episodes:
            raise ValueError("所选范围没有已入库剧本，请先在预处理中保存剧本")
        if episode_ids and len(episodes) != len(set(episode_ids)):
            raise ValueError("所选分集中包含不存在或尚未入库剧本的分集")

        run = self.repository.start_extraction_run(
            project_id, {episode.id: episode.revision for episode in episodes}
        )
        try:
            extracted: list[dict[str, Any]] = []
            for episode in episodes:
                payload = self._complete_json(
                    project_id,
                    user_id,
                    "entity_extract",
                    {
                        "episode_title": episode.title,
                        "episode_order": episode.order,
                        "episode_script": episode.script_text,
                    },
                    episode_id=episode.id,
                )
                entities = payload.get("entities")
                if not isinstance(entities, list):
                    raise ValueError(f"第 {episode.order} 集实体提取结果缺少 entities 数组")
                for item in entities:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("canonical_name") or "").strip()
                    entity_type = str(item.get("type") or "").strip()
                    if not name or entity_type not in ASSET_PROMPT_CATEGORY:
                        continue
                    extracted.append(
                        {
                            **item,
                            "name": name,
                            "type": entity_type,
                            "episode_id": episode.id,
                            "episode_order": episode.order,
                            "episode_title": episode.title,
                            "episode_script": episode.script_text,
                        }
                    )
            if not extracted:
                raise ValueError("LLM 未从所选剧本中返回有效实体")

            catalog = [
                {key: value for key, value in item.items() if key != "episode_script"}
                for item in extracted
            ]
            consolidated = self._complete_json(
                project_id,
                user_id,
                "entity_consolidate",
                {"extraction_catalog": json.dumps(catalog, ensure_ascii=False)},
            )
            groups = consolidated.get("profiles")
            if not isinstance(groups, list) or not groups:
                raise ValueError("实体跨集聚合结果缺少 profiles 数组")
            profiles = self._persist_groups(project_id, run["id"], extracted, groups)
            finished = self.repository.finish_extraction_run(project_id, run["id"])
            self.store.refresh_entity_workflow_flags(project_id)
            return {"run": finished, "profiles": profiles}
        except Exception as exc:
            self.repository.finish_extraction_run(project_id, run["id"], error=str(exc))
            raise

    def generate_setting(self, project_id: str, profile_id: str, user_id: str) -> dict[str, Any]:
        profile = self.repository.get_profile(project_id, profile_id)
        payload = self._complete_json(
            project_id,
            user_id,
            "entity_setting",
            {"entity_profile": json.dumps(profile, ensure_ascii=False)},
        )
        setting = str(payload.get("setting") or "").strip()
        if not setting:
            raise ValueError("LLM 未返回实体 setting")
        updated = self.repository.update_profile(project_id, profile_id, {"setting": setting, "status": "reviewed"})
        variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
        self.repository.replace_variants(project_id, profile_id, variants)
        return self.repository.get_profile(project_id, updated["id"])

    def create_entity_card(self, project_id: str, profile_id: str, variant_id: str | None = None) -> dict[str, Any]:
        profile = self.repository.get_profile(project_id, profile_id)
        variant = next((item for item in profile["variants"] if item["id"] == variant_id), None) if variant_id else None
        existing = None
        if profile.get("linked_entity_card_id"):
            try:
                existing = self.store.get_entity_card(project_id, profile["linked_entity_card_id"])
            except KeyError:
                existing = None
        card = EntityCard(
            id=existing.id if existing else EntityCard(entity_name=profile["canonical_name"], type=EntityType(profile["type"])).id,
            project_id=project_id,
            entity_name=profile["canonical_name"],
            type=EntityType(profile["type"]),
            state=str(variant.get("name") or "") if variant else None,
            tags=[profile["importance"], profile["role"]] if profile.get("role") else [profile["importance"]],
            assets=list(existing.assets) if existing else [],
            created_at=existing.created_at if existing else datetime.now(timezone.utc),
        )
        saved = self.store.save_entity_card(project_id, card)
        self._link_card(project_id, profile_id, saved.id)
        self.store.refresh_entity_workflow_flags(project_id)
        return {"id": saved.id, "entity_name": saved.entity_name, "type": saved.type.value, "state": saved.state}

    def generate_asset_prompt(
        self,
        project_id: str,
        profile_id: str,
        user_id: str,
        *,
        variant_id: str | None = None,
        view_type: str = "",
    ) -> dict[str, Any]:
        profile = self.repository.get_profile(project_id, profile_id)
        preset = self.repository.get_preset(project_id, profile["type"])
        styles = self.repository.list_visual_styles(project_id)
        style = next((item for item in styles if item["is_active"]), None)
        if style is None:
            raise ValueError("请先创建并启用项目视觉风格")
        variant = next((item for item in profile["variants"] if item["id"] == variant_id), None) if variant_id else None
        category = ASSET_PROMPT_CATEGORY[profile["type"]]
        payload, template = self._complete_json_with_template(
            project_id,
            user_id,
            category,
            {
                "entity_name": profile["canonical_name"],
                "entity_setting": profile["setting"],
                "variant_setting": variant["setting"] if variant else "",
                "project_style_prompt": "\n".join(
                    item for item in [self.store.get_project_style_prompt(project_id), style["prompt"]]
                    if str(item or "").strip()
                ),
                "project_negative_prompt": style["negative_prompt"],
                "type_prompt": preset["type_prompt"],
                "type_negative_prompt": preset["type_negative_prompt"],
                "reference_summary": self._reference_summary(project_id, profile),
                "view_type": view_type or next(iter(preset["view_types"]), ""),
            },
        )
        prompt_text = str(payload.get("prompt_text") or "").strip()
        if not prompt_text:
            raise ValueError("LLM 未返回 prompt_text")
        return self.repository.save_asset_prompt(
            project_id,
            {
                "profile_id": profile_id,
                "variant_id": variant_id,
                "style_id": style["id"],
                "style_version": style["version"],
                "view_type": view_type or next(iter(preset["view_types"]), ""),
                "prompt_text": prompt_text,
                "negative_prompt": str(payload.get("negative_prompt") or "").strip(),
                "template_id": template.id,
                "template_version": template.version,
            },
        )

    def generate_images(self, project_id: str, user_id: str, asset_prompt_id: str) -> dict[str, Any]:
        asset_prompt = self.repository.get_asset_prompt(project_id, asset_prompt_id)
        profile = self.repository.get_profile(project_id, asset_prompt["profile_id"])
        preset = self.repository.get_preset(project_id, profile["type"])
        config = _load_api_config(self.store, user_id=user_id)
        if not image_gateway_ready(config):
            raise ImageGenerationError("图片服务未配置：请在设置中填写 OpenAI 兼容 Base URL 和 API Key")
        model = str(preset.get("model") or config.get("imageModel") or "").strip()
        if not model:
            raise ImageGenerationError(f"请先为{profile['type']}配置图片模型")
        request = {
            "profile_id": profile["id"],
            "asset_prompt_id": asset_prompt_id,
            "provider": preset["provider"],
            "model": model,
            "size": preset["size"],
            "aspect_ratio": preset["aspect_ratio"],
            "output_count": preset["output_count"],
            "prompt_text": asset_prompt["prompt_text"],
            "negative_prompt": asset_prompt["negative_prompt"],
            "style_id": asset_prompt["style_id"],
            "style_version": asset_prompt["style_version"],
        }
        task = self.repository.create_image_task(project_id, request)
        self.repository.update_image_task(project_id, task["id"], "processing")
        try:
            prompt = asset_prompt["prompt_text"]
            if asset_prompt["negative_prompt"]:
                prompt = f"{prompt}\n\nNegative prompt: {asset_prompt['negative_prompt']}"
            images = build_image_client(config).generate(
                prompt, n=preset["output_count"], model=model, size=preset["size"]
            )
            outputs = []
            for index, content in enumerate(images, start=1):
                filename = f"{self._slug(profile['canonical_name'])}_{asset_prompt['view_type'] or 'asset'}_{index}.png"
                path = self.store.save_asset(project_id, "image", filename, content)
                asset = self.store.get_project_asset(project_id, path)
                if asset is None:
                    raise RuntimeError(f"生成图片已写入但素材记录缺失: {path}")
                outputs.append(self.repository.add_image_output(project_id, task["id"], asset, {"index": index}))
            self.repository.update_image_task(project_id, task["id"], "succeeded")
            if preset["auto_adopt"] and outputs:
                self.adopt_output(project_id, outputs[0]["id"])
            return self.repository.get_image_task(project_id, task["id"])
        except Exception as exc:
            self.repository.update_image_task(project_id, task["id"], "failed", str(exc))
            raise

    def adopt_output(self, project_id: str, output_id: str) -> dict[str, Any]:
        output = self.repository.get_image_output(project_id, output_id)
        task = self.repository.get_image_task(project_id, output["image_task_id"])
        profile_id = task.get("profile_id")
        if not profile_id:
            raise ValueError("图片任务未关联实体档案")
        profile = self.repository.get_profile(project_id, profile_id)
        asset_prompt = self.repository.get_asset_prompt(project_id, task["asset_prompt_id"])
        card_data = self.create_entity_card(project_id, profile_id, asset_prompt.get("variant_id"))
        card = self.store.get_entity_card(project_id, card_data["id"])
        merged = list(dict.fromkeys([*(card.assets or []), output["storage_path"]]))
        self.store.add_entity_materials(project_id, card.entity_name, card.type, [output["storage_path"]])
        self.store.save_entity_card(
            project_id,
            EntityCard(
                id=card.id, project_id=project_id, entity_name=card.entity_name, type=card.type,
                state=card.state, tags=card.tags, assets=merged, created_at=card.created_at,
            ),
        )
        adopted = self.repository.adopt_image_output(project_id, output_id)
        return {"output": adopted, "entity_card_id": card.id, "profile_id": profile["id"]}

    def _persist_groups(
        self,
        project_id: str,
        run_id: str,
        extracted: list[dict[str, Any]],
        groups: list[object],
    ) -> list[dict[str, Any]]:
        matched_groups = self._match_groups(extracted, groups)
        result = []
        for raw_group, members in matched_groups:
            name = str(raw_group.get("canonical_name") or "").strip()
            entity_type = str(raw_group.get("type") or "").strip()
            aliases = sorted({alias for item in members for alias in [item["name"], *item.get("aliases", [])] if alias and alias != name})
            aliases = sorted(set(aliases) | {str(alias).strip() for alias in raw_group.get("aliases", []) if str(alias).strip() and str(alias).strip() != name})
            episode_orders = sorted({int(item["episode_order"]) for item in members})
            episode_ids = [item["episode_id"] for item in sorted(members, key=lambda row: row["episode_order"])]
            episode_ids = list(dict.fromkeys(episode_ids))
            mentions = []
            mention_total = 0
            scene_total = 0
            search_names = [name, *aliases]
            for item in members:
                count = sum(item["episode_script"].count(alias) for alias in search_names if alias)
                evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
                count = max(count, len(evidence), 1)
                scene_count = max(len(evidence), 1)
                mention_total += count
                scene_total += scene_count
                mentions.append(
                    {
                        "episode_id": item["episode_id"], "episode_order": item["episode_order"],
                        "alias": item["name"], "evidence": "\n".join(str(value) for value in evidence[:5]),
                        "mention_count": count, "scene_count": scene_count,
                    }
                )
            profile = self.repository.upsert_profile(
                project_id,
                {
                    "canonical_name": name, "type": entity_type, "aliases": aliases,
                    "role": str(raw_group.get("role") or members[0].get("role") or ""),
                    "importance": str(raw_group.get("importance") or members[0].get("importance") or "C").upper(),
                    "mention_count": mention_total, "scene_count": scene_total,
                    "episode_ids": episode_ids, "first_episode": episode_orders[0], "last_episode": episode_orders[-1],
                },
            )
            self.repository.replace_mentions(project_id, run_id, profile["id"], mentions)
            variants = raw_group.get("variants") if isinstance(raw_group.get("variants"), list) else []
            if variants:
                self.repository.replace_variants(project_id, profile["id"], variants)
            result.append(self.repository.get_profile(project_id, profile["id"]))
        if not result:
            raise ValueError("实体聚合没有形成有效档案")
        return result

    @staticmethod
    def _match_groups(
        extracted: list[dict[str, Any]], groups: list[object]
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        matched_groups: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        consumed: set[int] = set()
        for raw_group in groups:
            if not isinstance(raw_group, dict):
                continue
            name = str(raw_group.get("canonical_name") or "").strip()
            entity_type = str(raw_group.get("type") or "").strip()
            if not name or entity_type not in ASSET_PROMPT_CATEGORY:
                continue
            member_names = {
                str(item).strip() for item in raw_group.get("member_names", []) if str(item).strip()
            }
            member_names.add(name)
            members = []
            for index, item in enumerate(extracted):
                if index in consumed or item["type"] != entity_type:
                    continue
                item_names = {item["name"], *[str(alias).strip() for alias in item.get("aliases", [])]}
                if item_names & member_names:
                    members.append(item)
                    consumed.add(index)
            if members:
                matched_groups.append((raw_group, members))
        if consumed != set(range(len(extracted))):
            missing = sorted({extracted[index]["name"] for index in set(range(len(extracted))) - consumed})
            raise ValueError(f"实体聚合遗漏候选：{', '.join(missing)}")
        if not matched_groups:
            raise ValueError("实体聚合没有形成有效档案")
        return matched_groups

    def _complete_json(
        self, project_id: str, user_id: str, category: str, values: dict[str, object], episode_id: str | None = None
    ) -> dict[str, object]:
        payload, _ = self._complete_json_with_template(project_id, user_id, category, values, episode_id=episode_id)
        return payload

    def _complete_json_with_template(
        self, project_id: str, user_id: str, category: str, values: dict[str, object], episode_id: str | None = None
    ) -> tuple[dict[str, object], Any]:
        config = _load_api_config(self.store, user_id=user_id)
        use_config = llm_use_case_config(config, category)
        template = template_for_category(self.prompt_engine, category)
        effective_values = {
            "project_style_prompt": self.store.get_project_style_prompt(project_id),
            **values,
        }
        context = {variable: effective_values.get(variable, "") for variable in template.variables}
        prompt = self.prompt_engine.render_prompt(template, context)
        client = TrackedLLMClient(
            build_llm_client(config, category), self.production_repository, category, project_id,
            episode_id=episode_id, template_id=template.id, template_version=template.version,
        )
        raw = client.complete(
            prompt,
            temperature=float(use_config.get("temperature") or 0.2),
            max_tokens=int(use_config.get("maxTokens") or 100000),
            json_mode=True,
        )
        return parse_json_object(raw), template

    def _link_card(self, project_id: str, profile_id: str, card_id: str) -> None:
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE entity_profiles SET linked_entity_card_id = ?, revision = revision + 1, updated_at = ? "
                "WHERE project_id = ? AND id = ?",
                (card_id, datetime.now(timezone.utc).isoformat(), project_id, profile_id),
            )

    def _reference_summary(self, project_id: str, profile: dict[str, Any]) -> str:
        card_id = profile.get("linked_entity_card_id")
        if not card_id:
            return ""
        try:
            card = self.store.get_entity_card(project_id, card_id)
        except KeyError:
            return ""
        assets = [self.store.get_project_asset(project_id, path) for path in card.assets]
        return json.dumps([{"filename": item["filename"], "type": item["asset_type"]} for item in assets if item], ensure_ascii=False)

    @staticmethod
    def _slug(value: str) -> str:
        return "".join(char if char.isalnum() or char in "-_" else "_" for char in value).strip("_")[:48] or "entity"
