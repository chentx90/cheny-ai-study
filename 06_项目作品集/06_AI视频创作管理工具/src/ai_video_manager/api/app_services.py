from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ai_video_manager.api.app_helpers import TemplateBackedDurationSplitClient, sync_default_prompt_templates
from ai_video_manager.application.ai_runs import TrackedLLMClient
from ai_video_manager.application.entity_assets import EntityAssetService
from ai_video_manager.api.config import _load_api_config
from ai_video_manager.document_processor import DocumentProcessor
from ai_video_manager.infrastructure.db.production_repository import ProductionRepository
from ai_video_manager.infrastructure.db.asset_production_repository import AssetProductionRepository
from ai_video_manager.llm import build_llm_client, llm_use_case_config
from ai_video_manager.prompt_engine import PromptEngine, template_for_category
from ai_video_manager.project_domain import ProjectDomainService
from ai_video_manager.storage import SQLiteStore
from ai_video_manager.video_archive import resolve_video_archive_path
from ai_video_manager.video_generation import UnconfiguredVideoAPIAdapter, VideoGenerationEngine, build_video_adapter
from ai_video_manager.workflow import CheckpointManager
from ai_video_manager.commands import CommandBus, build_command_registry
from ai_video_manager.agent.service import WorkflowAgentService


@dataclass
class AppServices:
    store: SQLiteStore
    document_processor: DocumentProcessor
    prompt_engine: PromptEngine
    checkpoint_manager: CheckpointManager
    video_engine: VideoGenerationEngine
    refresh_video_engine: Callable[..., dict]
    video_runtime_mode: Callable[[], str]
    duration_split_client: Callable[[str, str | None], TemplateBackedDurationSplitClient]
    production_repository: ProductionRepository
    asset_production_repository: AssetProductionRepository
    entity_asset_service: EntityAssetService
    command_bus: CommandBus
    workflow_agent: WorkflowAgentService


def build_app_services(*, db_path, workspace_root) -> AppServices:
    store = SQLiteStore(db_path, workspace_root=workspace_root)
    legacy_domain = ProjectDomainService(store)
    for project in store.list_projects(include_deleted=True):
        legacy_domain.ensure_migrated(project.id)
    store.drop_legacy_workspace_table()
    production_repository = ProductionRepository(store)
    asset_production_repository = AssetProductionRepository(store)
    asset_production_repository.recover_interrupted_runs()
    document_processor = DocumentProcessor()
    prompt_engine = PromptEngine()
    for stored_template in store.list_prompt_templates():
        prompt_engine.load_template_record(stored_template)
    sync_default_prompt_templates(store, prompt_engine)
    checkpoint_manager = CheckpointManager(store)
    video_engine = VideoGenerationEngine(
        archive_root=store.workspace_root / "projects",
        archive_path_resolver=lambda task: resolve_video_archive_path(store, task),
    )

    def refresh_video_engine(config: dict[str, object] | None = None) -> dict[str, object]:
        active_config = config or _load_api_config(store)
        try:
            video_engine.set_api_client(build_video_adapter(active_config))
        except RuntimeError:
            video_engine.set_api_client(UnconfiguredVideoAPIAdapter())
        return active_config

    def video_runtime_mode() -> str:
        return "real" if video_engine.provider not in {"unconfigured", "mock"} else "unconfigured"

    refresh_video_engine()

    def duration_split_client(user_id: str, project_id: str | None = None) -> TemplateBackedDurationSplitClient:
        config = _load_api_config(store, user_id=user_id)
        use_config = llm_use_case_config(config, "split_planning")
        template = template_for_category(prompt_engine, "split_planning")
        client = build_llm_client(config, "split_planning")
        if project_id:
            client = TrackedLLMClient(
                client,
                production_repository,
                "duration_split",
                project_id,
                template_id=template.id,
                template_version=template.version,
            )
        return TemplateBackedDurationSplitClient(
            llm_client=client,
            prompt_engine=prompt_engine,
            template=template,
            temperature=float(use_config.get("temperature") or 0.2),
            max_tokens=int(use_config.get("maxTokens") or 100000),
            project_style_prompt=store.get_project_style_prompt(project_id) if project_id else "",
        )

    services = AppServices(
        store=store,
        document_processor=document_processor,
        prompt_engine=prompt_engine,
        checkpoint_manager=checkpoint_manager,
        video_engine=video_engine,
        refresh_video_engine=refresh_video_engine,
        video_runtime_mode=video_runtime_mode,
        duration_split_client=duration_split_client,
        production_repository=production_repository,
        asset_production_repository=asset_production_repository,
        entity_asset_service=EntityAssetService(
            store, asset_production_repository, production_repository, prompt_engine
        ),
        command_bus=CommandBus(build_command_registry()),
        workflow_agent=None,  # assigned after the complete service graph exists
    )
    services.workflow_agent = WorkflowAgentService(services)
    return services
