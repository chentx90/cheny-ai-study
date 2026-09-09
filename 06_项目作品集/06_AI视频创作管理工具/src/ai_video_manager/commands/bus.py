from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from ai_video_manager.project_domain import ProjectDomainService

if TYPE_CHECKING:
    from ai_video_manager.api.app_services import AppServices


class CommandError(ValueError):
    pass


@dataclass(slots=True)
class CommandContext:
    services: "AppServices"
    user_id: str | None = None
    is_admin: bool = False
    source: str = "api"
    operation_id: str | None = None

    @property
    def store(self):
        return self.services.store

    @property
    def domain(self) -> ProjectDomainService:
        return ProjectDomainService(self.store, self.services.document_processor)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    id: str
    label: str
    handler: Callable[[CommandContext, dict[str, Any]], Any]
    input_schema: dict[str, Any]
    mutation: bool = False
    requires_project: bool = False
    confirmation: str = "none"
    description: str = ""
    effects: tuple[str, ...] = ()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return _jsonable(asdict(value))
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class CommandBus:
    def __init__(self, registry: dict[str, CommandSpec]) -> None:
        self.registry = registry

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": spec.id,
                "label": spec.label,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "mutation": spec.mutation,
                "requires_project": spec.requires_project,
                "confirmation": spec.confirmation,
                "effects": list(spec.effects),
            }
            for spec in self.registry.values()
        ]

    def execute(
        self,
        command_id: str,
        payload: dict[str, Any] | None,
        context: CommandContext,
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        spec = self.registry.get(command_id)
        if spec is None:
            raise CommandError(f"Unknown command: {command_id}")
        data = dict(payload or {})
        project_id = str(data.get("project_id") or "").strip()
        if spec.requires_project and not project_id:
            raise CommandError(f"{command_id} requires project_id")
        if project_id:
            context.store.get_project(project_id)
        operation_id = operation_id or context.operation_id or f"op_{uuid4().hex[:12]}"
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = _jsonable(spec.handler(context, data))
        except Exception as exc:
            self._record(context, operation_id, spec, data, "failed", None, str(exc), started_at)
            raise
        self._record(context, operation_id, spec, data, "succeeded", result, "", started_at)
        revision = None
        if isinstance(result, dict):
            revision = result.get("revision")
            if revision is None and isinstance(result.get("workspace"), dict):
                revision = result["workspace"].get("revision")
        return {
            "ok": True,
            "command": command_id,
            "operation_id": operation_id,
            "project_id": project_id or None,
            "revision": revision,
            "data": result,
            "warnings": [],
            "effects": list(spec.effects),
        }

    @staticmethod
    def _record(
        context: CommandContext,
        operation_id: str,
        spec: CommandSpec,
        arguments: dict[str, Any],
        status: str,
        result: Any,
        error: str,
        started_at: str,
    ) -> None:
        recorder = getattr(context.store, "record_command_operation", None)
        if recorder is None:
            return
        recorder(
            operation_id=operation_id,
            command_id=spec.id,
            source=context.source,
            project_id=str(arguments.get("project_id") or "") or None,
            user_id=context.user_id,
            arguments=_audit_payload(arguments),
            status=status,
            result=_audit_payload(result),
            error_message=error,
            started_at=started_at,
        )


def _audit_payload(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(token in lowered for token in ("password", "secret", "api_key", "apikey", "token")):
        return "***"
    if isinstance(value, dict):
        return {str(item_key): _audit_payload(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_audit_payload(item, key=key) for item in value[:200]]
    if isinstance(value, str) and len(value) > 4000:
        return f"{value[:4000]}...<truncated:{len(value)}>"
    return value
