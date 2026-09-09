from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ai_video_manager.api.app_services import build_app_services
from ai_video_manager.commands import CommandContext
from ai_video_manager.commands.bus import CommandError
from ai_video_manager.runtime_paths import resolve_runtime_paths


def _build_parser(registry) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-video-manager")
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument("--workspace-root", default=None, help="Workspace root")
    parser.add_argument("--user-id", default=os.environ.get("AVM_CLI_USER_ID") or None)
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON")
    subparsers = parser.add_subparsers(dest="domain", required=True)

    subparsers.add_parser("init", help="Initialize local database")
    subparsers.add_parser("catalog", help="List command catalog")

    run = subparsers.add_parser("run", help="Run a command by id")
    run.add_argument("command_id")
    run.add_argument("--payload", default="{}", help="JSON object")
    run.add_argument("--payload-file", default="")
    run.add_argument("--yes", action="store_true")

    ingest = subparsers.add_parser("ingest", help="Compatibility import and split command")
    ingest.add_argument("path")
    ingest.add_argument("--project-name", default="AI 视频项目")
    ingest.add_argument("--strategy", default="chapter")
    ingest.add_argument("--yes", action="store_true")

    domain_parsers: dict[str, argparse._SubParsersAction] = {}
    for command_id, spec in registry.items():
        domain, action = command_id.split(".", 1)
        if domain not in domain_parsers:
            domain_parser = subparsers.add_parser(domain)
            domain_parsers[domain] = domain_parser.add_subparsers(dest="action", required=True)
        action_parser = domain_parsers[domain].add_parser(action, help=spec.description or spec.label)
        action_parser.set_defaults(command_id=command_id)
        for key, value_type in spec.input_schema.items():
            option = f"--{key.replace('_', '-')}"
            required = not str(value_type).endswith("?") and key not in {"category", "description"}
            action_parser.add_argument(option, dest=key, required=required)
        action_parser.add_argument("--payload", default="{}", help="Additional JSON object")
        action_parser.add_argument("--input-file", default="", help="Read content/template from UTF-8 file")
        action_parser.add_argument("--yes", action="store_true")
    return parser


def _runtime(args):
    if args.workspace_root:
        workspace_root = Path(args.workspace_root).expanduser().resolve()
        db_path = Path(args.db).expanduser().resolve() if args.db else workspace_root / "database" / "app.db"
    else:
        workspace_root, db_path = resolve_runtime_paths(args.db)
    return workspace_root, db_path, build_app_services(db_path=db_path, workspace_root=workspace_root)


def _payload_from_args(args, registry) -> dict[str, Any]:
    payload = json.loads(args.payload or "{}")
    if not isinstance(payload, dict):
        raise ValueError("--payload must be a JSON object")
    spec = registry[args.command_id]
    for key, value_type in spec.input_schema.items():
        value = getattr(args, key, None)
        if value is None:
            continue
        payload[key] = _coerce(value, str(value_type))
    if args.input_file:
        body = Path(args.input_file).expanduser().read_text(encoding="utf-8")
        if "content" in spec.input_schema:
            payload["content"] = body
        elif "template" in spec.input_schema:
            payload["template"] = body
        else:
            loaded = json.loads(body)
            if not isinstance(loaded, dict):
                raise ValueError("--input-file must contain a JSON object for this command")
            payload.update(loaded)
    return payload


def _coerce(value: str, value_type: str) -> Any:
    normalized = value_type.rstrip("?")
    if normalized.endswith("[]"):
        return [item.strip() for item in value.split(",") if item.strip()]
    if normalized in {"number", "number?"}:
        return float(value) if "." in value else int(value)
    if normalized in {"boolean", "bool"}:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value


def _requires_yes(spec) -> bool:
    return spec.confirmation in {"destructive", "overwrite", "llm", "external"}


def _print(value: Any, *, json_output: bool) -> None:
    if json_output or isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    else:
        print(value)


def main(argv: list[str] | None = None) -> int:
    from ai_video_manager.commands import CommandBus, build_command_registry

    registry = build_command_registry()
    parser = _build_parser(registry)
    args = parser.parse_args(argv)
    try:
        workspace_root, db_path, services = _runtime(args)
        bus: CommandBus = services.command_bus
        context = CommandContext(services=services, user_id=args.user_id, is_admin=True, source="cli")

        if args.domain == "init":
            _print({"database": str(db_path), "workspace_root": str(workspace_root), "status": "initialized"}, json_output=True)
            return 0
        if args.domain == "catalog":
            _print({"commands": bus.catalog()}, json_output=True)
            return 0
        if args.domain == "run":
            if args.payload_file:
                payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
            else:
                payload = json.loads(args.payload)
            spec = registry.get(args.command_id)
            if spec is None:
                raise CommandError(f"Unknown command: {args.command_id}")
            if _requires_yes(spec) and not args.yes:
                raise CommandError(f"{args.command_id} requires --yes")
            _print(bus.execute(args.command_id, payload, context), json_output=True)
            return 0
        if args.domain == "ingest":
            created = bus.execute("project.create", {"name": args.project_name}, context)
            project_id = created["data"]["project"]["id"]
            bus.execute("document.import", {"project_id": project_id, "path": args.path}, context)
            if not args.yes:
                raise CommandError("ingest split requires --yes; the project and document were created")
            result = bus.execute("preprocess.split", {"project_id": project_id, "strategy": args.strategy}, context)
            result["warnings"] = ["ingest no longer performs offline script conversion"]
            _print(result, json_output=True)
            return 0

        command_id = args.command_id
        spec = registry[command_id]
        if _requires_yes(spec) and not args.yes:
            raise CommandError(f"{command_id} requires --yes")
        payload = _payload_from_args(args, registry)
        _print(bus.execute(command_id, payload, context), json_output=args.json_output)
        return 0
    except Exception as exc:
        error = {"ok": False, "error": type(exc).__name__, "detail": str(exc)}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
