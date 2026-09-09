#!/usr/bin/env python3
"""Functional smoke tests for AI Video Manager (run inside container or with AVM_DB_PATH)."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# Allow running from repo root or container site-packages context
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_video_manager.auth.password import hash_password
from ai_video_manager.models import EntityCard, EntityType, Project, ProjectRole, PromptCard
from ai_video_manager.project_bundle import (
    ENTITY_CARDS_FILE,
    MANIFEST_FILE,
    PROMPT_CARDS_FILE,
    export_project_zip,
    import_project_zip,
    resolve_project_data_root,
    sync_cards_to_files,
)
from ai_video_manager.project_domain import ProjectDomainService
from ai_video_manager.storage import SQLiteStore

PASS = 0
FAIL = 0
SKIP = 0


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [PASS] {name}{suffix}")


def fail(name: str, detail: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {name}: {detail}")


def skip(name: str, reason: str) -> None:
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}: {reason}")


def make_store(*, isolated: bool = False) -> SQLiteStore:
    if isolated:
        tmp = Path(tempfile.mkdtemp(prefix="avm_smoke_"))
        db_path = tmp / "database" / "app.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        workspace = tmp
    else:
        db_path = Path(os.environ.get("AVM_DB_PATH", str(ROOT / "database" / "app.db")))
        workspace = Path(os.environ.get("AVM_WORKSPACE_ROOT", str(db_path.parent.parent)))
    store = SQLiteStore(db_path, workspace_root=workspace)
    store.init_schema()
    return store


def test_bundle_sync_and_files(store: SQLiteStore) -> str | None:
    """Create project, save cards, verify JSON files on disk. Returns project_id."""
    project = Project(name="功能测试项目", category="draft", description="smoke test")
    project = store.save_project(project)

    domain = ProjectDomainService(store)
    domain.import_workspace_dict(
        project.id,
        {
            "documentText": "第一章 测试\n\n第二章 结尾",
            "splitStrategy": "chapter",
            "segments": [
                {"id": "seg_test1", "order": 1, "title": "第1集", "content": "第一章 测试"},
            ],
            "activeSegmentId": "seg_test1",
            "scripts": {"seg_test1": "场景：室内"},
            "dataRoot": "",
        },
    )

    card = EntityCard(
        entity_name="测试角色",
        type=EntityType.CHARACTER,
        project_id=project.id,
        state="青年",
        tags=["主角"],
    )
    store.save_entity_card(project.id, card)

    prompt = PromptCard(
        project_id=project.id,
        segment_id="seg_test1",
        order=1,
        title="开场",
        prompt_text="镜头推进",
        anchor_text="",
    )
    store.save_prompt_card(prompt)

    root = sync_cards_to_files(store, project.id)
    manifest = root / MANIFEST_FILE
    entity_json = root / ENTITY_CARDS_FILE
    prompt_json = root / PROMPT_CARDS_FILE

    if not manifest.is_file():
        fail("bundle manifest", f"missing {manifest}")
    else:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("bundle_version") != 1:
            fail("bundle manifest", f"bad version {data.get('bundle_version')}")
        elif data.get("project", {}).get("name") != "功能测试项目":
            fail("bundle manifest", "project name mismatch")
        else:
            ok("bundle manifest", str(manifest))

    if not entity_json.is_file():
        fail("entity_cards.json", "missing")
    else:
        cards = json.loads(entity_json.read_text(encoding="utf-8")).get("cards", [])
        if len(cards) != 1 or cards[0].get("entity_name") != "测试角色":
            fail("entity_cards.json", f"unexpected content: {cards}")
        else:
            ok("entity_cards.json", "1 card")

    if not prompt_json.is_file():
        fail("prompt_cards.json", "missing")
    else:
        cards = json.loads(prompt_json.read_text(encoding="utf-8")).get("cards", [])
        if len(cards) != 1 or cards[0].get("prompt_text") != "镜头推进":
            fail("prompt_cards.json", f"unexpected content: {cards}")
        else:
            ok("prompt_cards.json", "1 card")

    resolved = resolve_project_data_root(store, project.id)
    if resolved != root:
        fail("resolve_project_data_root", f"{resolved} != {root}")
    else:
        ok("default data_root", str(resolved))

    return project.id


def test_custom_data_root(store: SQLiteStore, project_id: str) -> None:
    custom_rel = f"projects/custom_{project_id[:8]}"
    domain = ProjectDomainService(store)
    view = domain.update_settings(project_id, data_root=custom_rel)
    if view.get("dataRoot") != custom_rel:
        fail("update_settings dataRoot", f"got {view.get('dataRoot')}")
    else:
        ok("update_settings dataRoot", custom_rel)

    root = resolve_project_data_root(store, project_id)
    expected = (store.workspace_root / custom_rel).resolve()
    if root != expected:
        fail("custom data_root resolve", f"{root} != {expected}")
    else:
        ok("custom data_root resolve", str(root))

    sync_cards_to_files(store, project_id)
    if not (root / MANIFEST_FILE).is_file():
        fail("sync to custom root", "manifest missing")
    else:
        ok("sync to custom root", str(root / MANIFEST_FILE))


def test_export_import_roundtrip(store: SQLiteStore, project_id: str) -> None:
    payload, filename = export_project_zip(store, project_id)
    if not filename.endswith(".zip"):
        fail("export filename", filename)
    else:
        ok("export zip", filename)

    if len(payload) < 100:
        fail("export zip size", f"too small: {len(payload)}")
    else:
        ok("export zip size", f"{len(payload)} bytes")

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        if not any(n.endswith(MANIFEST_FILE) for n in names):
            fail("zip contents", f"no manifest in {names[:5]}")
        else:
            ok("zip contains manifest", str(sum(1 for n in names if n.endswith(MANIFEST_FILE))))

    owner_id = ""
    imported = import_project_zip(
        store,
        payload,
        owner_id=owner_id,
        name_override="导入副本",
    )
    if imported.name != "导入副本":
        fail("import project name", imported.name)
    else:
        ok("import project", imported.id)

    imported_root = resolve_project_data_root(store, imported.id)
    if not (imported_root / MANIFEST_FILE).is_file():
        fail("imported bundle layout", "manifest missing")
    else:
        ok("imported bundle layout", str(imported_root))

    cards = store.list_entity_cards(imported.id)
    if not any(c.entity_name == "测试角色" for c in cards):
        fail("imported entity cards", str(cards))
    else:
        ok("imported entity cards", f"{len(cards)} cards")
        first_import_card_id = cards[0].id

    prompts = store.list_prompt_cards(imported.id)
    if not any(p.prompt_text == "镜头推进" for p in prompts):
        fail("imported prompt cards", str(prompts))
    else:
        ok("imported prompt cards", f"{len(prompts)} cards")

    imported2 = import_project_zip(store, payload, owner_id="", name_override="导入副本2")
    second_cards = store.list_entity_cards(imported2.id)
    if not second_cards or second_cards[0].id == first_import_card_id:
        fail("double import id collision", str(second_cards))
    else:
        ok("double import unique ids")

    source_cards = store.list_entity_cards(project_id)
    if len(source_cards) != 1 or source_cards[0].entity_name != "测试角色":
        fail("source preserved after double import", str(source_cards))
    else:
        ok("source preserved after double import")

    store.delete_project(imported.id)
    store.delete_project(imported2.id)


def test_api_http() -> None:
    try:
        import urllib.error
        import urllib.request
    except ImportError:
        skip("HTTP API", "urllib unavailable")
        return

    base = os.environ.get("AVM_TEST_BASE_URL", "http://127.0.0.1:8000")

    def get(path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base}{path}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"raw": body}

    status, body = get("/api/health")
    if status == 200 and body.get("status") == "ok":
        ok("HTTP /api/health")
    else:
        fail("HTTP /api/health", f"{status} {body}")

    status, body = get("/api/auth/setup-status")
    if status == 200 and "needs_setup" in body:
        ok(
            "HTTP /api/auth/setup-status",
            f"needs_setup={body['needs_setup']} auth_disabled={body.get('auth_disabled', False)}",
        )
    else:
        fail("HTTP /api/auth/setup-status", f"{status} {body}")

    status, _ = get("/api/projects")
    if body.get("auth_disabled"):
        if status == 200:
            ok("HTTP /api/projects auth disabled", "200")
        else:
            fail("HTTP /api/projects auth disabled", f"expected 200 got {status}")
    elif status == 401:
        ok("HTTP /api/projects requires auth", "401")
    else:
        fail("HTTP /api/projects auth guard", f"expected 401 got {status}")


def cleanup_project(store: SQLiteStore, project_id: str) -> None:
    try:
        store.delete_project(project_id)
    except Exception:
        pass
    custom = store.workspace_root / f"projects/custom_{project_id[:8]}"
    if custom.is_dir():
        import shutil
        shutil.rmtree(custom, ignore_errors=True)


def main() -> int:
    print("=== AI Video Manager Functional Smoke Tests ===\n")
    store = make_store()
    print(f"DB: {store.db_path}")
    print(f"Workspace: {store.workspace_root}\n")

    print("-- Module tests (project_bundle) --")
    module_store = make_store(isolated=True)
    print(f"  isolated workspace: {module_store.workspace_root}")
    project_id = None
    try:
        project_id = test_bundle_sync_and_files(module_store)
        if project_id:
            test_custom_data_root(module_store, project_id)
            test_export_import_roundtrip(module_store, project_id)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail("module tests", str(exc))
    finally:
        if project_id:
            cleanup_project(module_store, project_id)

    print("\n-- HTTP API tests --")
    test_api_http()

    print(f"\n=== Results: {PASS} passed, {FAIL} failed, {SKIP} skipped ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
