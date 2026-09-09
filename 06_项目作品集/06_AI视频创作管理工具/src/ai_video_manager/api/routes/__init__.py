from __future__ import annotations

from fastapi import FastAPI

from ai_video_manager.api.app_services import AppServices
from ai_video_manager.api.routes.asset_routes import register_asset_routes
from ai_video_manager.api.routes.auth_routes import register_auth_routes
from ai_video_manager.api.routes.config_routes import register_config_routes
from ai_video_manager.api.routes.document_routes import register_document_routes
from ai_video_manager.api.routes.entity_routes import register_entity_routes
from ai_video_manager.api.routes.domain_routes import register_domain_routes
from ai_video_manager.api.routes.image_routes import register_image_routes
from ai_video_manager.api.routes.project_routes import register_project_routes
from ai_video_manager.api.routes.prompt_routes import register_prompt_routes
from ai_video_manager.api.routes.video_routes import register_video_routes
from ai_video_manager.api.routes.workflow_routes import register_workflow_routes
from ai_video_manager.api.routes.v2_routes import register_v2_routes
from ai_video_manager.api.routes.asset_production_routes import register_asset_production_routes
from ai_video_manager.api.routes.agent_routes import register_agent_routes


def register_all_routes(app: FastAPI, services: AppServices) -> None:
    register_config_routes(app, services)
    register_auth_routes(app, services)
    register_project_routes(app, services)
    register_domain_routes(app, services)
    register_document_routes(app, services)
    register_entity_routes(app, services)
    register_asset_routes(app, services)
    register_image_routes(app, services)
    register_prompt_routes(app, services)
    register_workflow_routes(app, services)
    register_video_routes(app, services)
    register_v2_routes(app, services)
    register_asset_production_routes(app, services)
    register_agent_routes(app, services)
