#!/usr/bin/env python3
"""API-level verification for manual checklist items (P-PATH-02, PRE-DOC-01)."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE = os.environ.get("AVM_TEST_BASE", "http://127.0.0.1:8010").rstrip("/")
TEST_USER = os.environ.get("AVM_TEST_USER", "admin")
TEST_PASSWORD = os.environ.get("AVM_TEST_PASS", "admin")
DOC_TEXT = "手册验证原文：第一章。\n第二章。"
OUTPUT_ROOT = "projects/api_verify_out"
SOURCE_ROOT = "projects/api_verify_src"


class Client:
    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    return resp.status, json.loads(raw)
                except json.JSONDecodeError:
                    return resp.status, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw


def main() -> int:
    client = Client(BASE)
    fails = 0

    status, health = client.request("GET", "/api/health")
    if status != 200:
        print(f"[FAIL] health status={status}")
        return 1
    print("[PASS] health")

    status, setup = client.request("GET", "/api/auth/setup-status")
    user = f"api_verify_{int(time.time())}"
    password = "verify123456"
    if status == 200 and setup.get("needs_setup"):
        status, _ = client.request(
            "POST",
            "/api/auth/setup",
            {"username": user, "password": password, "display_name": "API Verify"},
        )
        if status != 200:
            print(f"[FAIL] setup status={status} body={_}")
            return 1
        print("[PASS] setup admin")
    else:
        status, _ = client.request(
            "POST",
            "/api/auth/login",
            {"username": TEST_USER, "password": TEST_PASSWORD},
        )
        if status != 200:
            print(f"[FAIL] login status={status} — set AVM_TEST_USER/PASS or bootstrap admin")
            return 1
        print("[PASS] login")

    name = f"API手册验证_{int(time.time())}"
    status, created = client.request(
        "POST",
        "/api/projects",
        {"name": name, "category": "active", "description": "路径与原文测试"},
    )
    if status != 200:
        print(f"[FAIL] create project status={status} body={created}")
        return 1
    project_id = created["id"]
    print(f"[PASS] P-PATH-01 create project {project_id}")

    status, _ = client.request(
        "PUT",
        f"/api/projects/{project_id}/settings",
        {
            "output_root": OUTPUT_ROOT,
            "source_assets_root": SOURCE_ROOT,
        },
    )
    if status != 200:
        print(f"[FAIL] P-PATH-02 save settings status={status} body={_}")
        fails += 1
    else:
        ws = _["data"]
        ok = ws.get("outputRoot") == OUTPUT_ROOT and ws.get("sourceAssetsRoot") == SOURCE_ROOT
        print(f"[{'PASS' if ok else 'FAIL'}] P-PATH-02 settings persisted out={ws.get('outputRoot')} src={ws.get('sourceAssetsRoot')}")
        fails += 0 if ok else 1

    status, _ = client.request(
        "PUT",
        f"/api/projects/{project_id}/document",
        {"document_text": DOC_TEXT, "split_strategy": "chapter"},
    )
    if status != 200:
        print(f"[FAIL] PRE-DOC-01 save document status={status} body={_}")
        fails += 1
    else:
        saved = _["data"].get("documentText", "")
        ok = DOC_TEXT in saved
        print(f"[{'PASS' if ok else 'FAIL'}] PRE-DOC-01 document saved len={len(saved)}")
        fails += 0 if ok else 1

    status, _ = client.request(
        "POST",
        f"/api/projects/{project_id}/documents/upload",
        {
            "filename": "readme-test.md",
            "content_base64": __import__("base64").b64encode(b"# Title\n\nUpload test body.").decode(),
        },
    )
    if status != 200:
        print(f"[FAIL] PRE-DOC-02 upload status={status} body={_}")
        fails += 1
    else:
        ws = _["workspace"]
        ok = "Upload test body" in ws.get("documentText", "")
        print(f"[{'PASS' if ok else 'FAIL'}] PRE-DOC-02 upload document len={len(ws.get('documentText', ''))}")
        fails += 0 if ok else 1

    status, reloaded = client.request("GET", f"/api/projects/{project_id}/session")
    if status != 200:
        print(f"[FAIL] reload session status={status}")
        fails += 1
    else:
        data = reloaded.get("data", {})
        ok = "Upload test body" in str(data.get("documentText", "")) and data.get("outputRoot") == OUTPUT_ROOT
        print(f"[{'PASS' if ok else 'FAIL'}] reload session document+paths")
        fails += 0 if ok else 1

    print(f"\nDone. failures={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
