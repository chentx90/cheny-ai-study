from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.config import _load_api_config
from ai_video_manager.api.schemas import CreatePromptTemplateRequest, GeneratePromptRequest, RenderPromptRequest
from ai_video_manager.api.utils import _dump
from ai_video_manager.llm import build_llm_client, llm_use_case_config
from ai_video_manager.models import PromptTemplate
from ai_video_manager.prompt_engine import PromptTemplateError, template_context, template_for_category


def register_prompt_routes(app: FastAPI, services: AppServices) -> None:
    store = services.store
    prompt_engine = services.prompt_engine

    @app.get("/api/prompts/templates")
    def list_prompt_templates() -> dict:
        return {"templates": [_dump(template) for template in prompt_engine.list_templates()]}

    @app.post("/api/prompts/templates")
    def create_prompt_template(request: CreatePromptTemplateRequest) -> dict:
        try:
            template = prompt_engine.add_template(
                PromptTemplate(
                    name=request.name,
                    category=request.category,
                    template=request.template,
                    variables=request.variables,
                )
            )
        except PromptTemplateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.save_prompt_template(template)
        return _dump(template)

    @app.get("/api/prompts/templates/{template_id}/versions")
    def list_prompt_template_versions(template_id: str) -> dict:
        try:
            return {"versions": store.list_prompt_template_versions(template_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/prompts/templates/{template_id}/versions/{version}/restore")
    def restore_prompt_template_version(template_id: str, version: int) -> dict:
        try:
            restored = store.restore_prompt_template_version(template_id, version)
            return _dump(prompt_engine.load_template_record(restored))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/prompts/templates/{template_id}")
    def update_prompt_template(template_id: str, request: CreatePromptTemplateRequest) -> dict:
        try:
            existing = prompt_engine.load_template(template_id)
            if existing.id.startswith("tpl_example_"):
                raise HTTPException(status_code=400, detail="Example prompt templates cannot be edited; duplicate first")
            template = prompt_engine.add_template(
                PromptTemplate(
                    id=existing.id,
                    name=request.name,
                    category=request.category,
                    template=request.template,
                    variables=request.variables,
                    examples=existing.examples,
                    is_default=existing.is_default,
                )
            )
        except HTTPException:
            raise
        except (KeyError, PromptTemplateError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.save_prompt_template(template)
        return _dump(template)

    @app.delete("/api/prompts/templates/{template_id}")
    def delete_prompt_template(template_id: str) -> dict:
        try:
            template = prompt_engine.load_template(template_id)
            if template.is_default:
                raise HTTPException(status_code=400, detail="Default prompt templates cannot be deleted")
            if template.id.startswith("tpl_example_"):
                raise HTTPException(status_code=400, detail="Example prompt templates cannot be deleted; duplicate first")
            prompt_engine.delete_template(template_id)
            store.delete_prompt_template(template_id)
            return {"deleted": True, "template_id": template_id}
        except HTTPException:
            raise
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/prompts/render")
    def render_prompt(request: RenderPromptRequest) -> dict:
        try:
            template = prompt_engine.load_template(request.template_name_or_id)
            return {"prompt": prompt_engine.render_prompt(template, request.context)}
        except (KeyError, PromptTemplateError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/generate")
    def generate_prompt(body: GeneratePromptRequest, request: Request) -> dict:
        try:
            config = _load_api_config(store, user_id=request.state.user.id)
            use_config = llm_use_case_config(config, "video_generate")
            template = (
                prompt_engine.load_template(body.template_name_or_id)
                if body.template_name_or_id
                else template_for_category(prompt_engine, "video_generate")
            )
            seed_prompt = prompt_engine.render_prompt(template, template_context(template, body.context))
            prompt = build_llm_client(config, "video_generate").complete(
                seed_prompt,
                temperature=float(use_config.get("temperature") or 0.6),
                max_tokens=int(use_config.get("maxTokens") or 100000),
            )
            return {"prompt": prompt, "template_id": template.id, "model": use_config.get("model")}
        except (KeyError, PromptTemplateError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
