"""端到端接入流程测试：模拟用户 上传→预览→入库→查结果→检索→重试→删除 全链路。

需要本地 Postgres（docker compose up -d）。用 TestClient 上下文管理触发 lifespan，
使 postgres 适配器与 ingestion_service 真正初始化。每个用例自带清理，避免污染库。
"""
import time
import asyncio
import pytest
from fastapi.testclient import TestClient

from app.main import app

MD_CONTENT = (
    "# 液压系统维护手册\n\n"
    "当液压泵压力不足时，应优先检查过滤器是否堵塞。过滤器堵塞会导致油液无法循环。\n\n"
    "液压系统维护周期一般为3个月一次常规检查，6个月一次深度维护。\n\n"
    "质量异常需按规范流程上报并处理。\n"
)

TEST_TITLE = "E2E_液压维护手册"
TEST_FILE = "e2e_pipeline.md"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _wait_status(client, job_id, targets, timeout=15.0):
    """轮询 job 状态直到进入目标集合或超时。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/api/ingestion/jobs/{job_id}")
        last = r.json()
        if last.get("status") in targets:
            return last
        time.sleep(0.3)
    return last


def _cleanup(client):
    """按外键顺序清理本测试产生的数据。"""
    import asyncpg

    async def run():
        pool = await asyncpg.create_pool(
            "postgresql://rag_user:rag_pass@localhost:5433/rag_db", min_size=1, max_size=2
        )
        await pool.execute(
            "DELETE FROM kb_chunks WHERE document_id IN (SELECT id FROM kb_documents WHERE title=$1)",
            TEST_TITLE,
        )
        await pool.execute("DELETE FROM kb_documents WHERE title=$1", TEST_TITLE)
        await pool.execute(
            "DELETE FROM ingestion_job_errors WHERE job_id IN (SELECT id FROM ingestion_jobs WHERE title=$1)",
            TEST_TITLE,
        )
        await pool.execute("DELETE FROM ingestion_jobs WHERE title=$1", TEST_TITLE)
        await pool.execute("DELETE FROM ingestion_uploads WHERE file_name=$1", TEST_FILE)
        await pool.close()

    asyncio.run(run())


DEDUP_TITLE = "E2E_DEDUP_文档"


def _cleanup_like(prefix: str):
    import asyncpg

    async def run():
        pool = await asyncpg.create_pool(
            "postgresql://rag_user:rag_pass@localhost:5433/rag_db", min_size=1, max_size=2
        )
        cond = "title = $1 OR title LIKE $1 || ' (%'"
        await pool.execute(f"DELETE FROM kb_chunks WHERE document_id IN (SELECT id FROM kb_documents WHERE {cond})", prefix)
        await pool.execute(f"DELETE FROM kb_documents WHERE {cond}", prefix)
        await pool.execute("DELETE FROM ingestion_job_errors WHERE job_id IN (SELECT id FROM ingestion_jobs WHERE title=$1)", prefix)
        await pool.execute("DELETE FROM ingestion_jobs WHERE title=$1", prefix)
        await pool.execute("DELETE FROM ingestion_uploads WHERE file_name LIKE 'e2e_dedup%'")
        await pool.close()

    asyncio.run(run())


def _ingest_to_completed(client, content: bytes, title: str, on_duplicate="block", fname="e2e_dedup.md"):
    """上传→预览完成→commit，返回 (job_id, commit_response)。等待 commit 落库完成。"""
    up = client.post("/api/ingestion/uploads", files={"file": (fname, content, "text/markdown")}).json()
    j = client.post(
        "/api/ingestion/jobs/preview",
        json={"upload_id": up["upload_id"], "source_type": "markdown", "title": title, "business_domain": "equipment"},
    ).json()
    jid = j.get("id") or j.get("job_id")
    _wait_status(client, jid, {"completed", "failed"})
    resp = client.post(f"/api/ingestion/jobs/{jid}/commit", json={"on_duplicate": on_duplicate})
    if resp.status_code == 200:
        _wait_status(client, jid, {"completed", "failed"})
    return jid, resp


def test_duplicate_block_then_new_and_replace(client):
    md = b"# DEDUP\n\nfingerprint content one two three.\n\nsection two."
    try:
        # 第一次入库成功
        jid1, r1 = _ingest_to_completed(client, md, DEDUP_TITLE)
        assert r1.status_code == 200
        # 第二次同内容 block → 409
        jid2, r2 = _ingest_to_completed(client, md, DEDUP_TITLE, on_duplicate="block", fname="e2e_dedup2.md")
        assert r2.status_code == 409, r2.text
        assert r2.json()["detail"]["existing_title"].startswith(DEDUP_TITLE)
        # 同 job 改 new → 成功，标题自动加序号
        r3 = client.post(f"/api/ingestion/jobs/{jid2}/commit", json={"on_duplicate": "new"})
        assert r3.status_code == 200
        _wait_status(client, jid2, {"completed", "failed"})
        docs = client.get("/api/knowledge/documents").json()["documents"]
        titles = [d["title"] for d in docs if d["title"].startswith(DEDUP_TITLE)]
        assert any("(2)" in t for t in titles), f"应有加序号标题: {titles}"
    finally:
        _cleanup_like(DEDUP_TITLE)


def test_same_title_different_content_gets_sequence(client):
    try:
        jid1, r1 = _ingest_to_completed(client, b"# A\n\ncontent alpha unique.", DEDUP_TITLE, fname="e2e_dedup.md")
        assert r1.status_code == 200
        # 不同内容、同标题 → 指纹不同，不触发 409，但标题加序号
        jid2, r2 = _ingest_to_completed(client, b"# B\n\ncontent beta different.", DEDUP_TITLE, fname="e2e_dedup2.md")
        assert r2.status_code == 200
        docs = client.get("/api/knowledge/documents").json()["documents"]
        titles = sorted(d["title"] for d in docs if d["title"].startswith(DEDUP_TITLE))
        assert any("(2)" in t for t in titles), f"同名不同内容应加序号: {titles}"
    finally:
        _cleanup_like(DEDUP_TITLE)


def test_doc_identity_unit():
    from app.services.doc_identity import normalize_text, compute_content_hash, derive_title

    # 归一化：不同排版同内容 → 同指纹
    h1 = compute_content_hash("第一行\n\n\n第二行", "equipment")
    h2 = compute_content_hash("第一行   第二行", "equipment")
    assert h1 == h2
    # 业务域不同 → 指纹不同
    assert compute_content_hash("x", "a") != compute_content_hash("x", "b")
    # 标题优先级
    assert derive_title("# 正文标题\n内容", manual="手动", filename_stem="文件") == "手动"
    assert derive_title("# 正文标题\n内容", manual=None, llm_title="LLM标题", filename_stem="文件") == "LLM标题"
    assert derive_title("# 正文标题\n内容", manual=None, filename_stem="文件") == "正文标题"
    assert derive_title("", manual=None, filename_stem="文件名兜底") == "文件名兜底"



def test_full_ingestion_pipeline(client):
    try:
        # STEP1 上传
        files = {"file": (TEST_FILE, MD_CONTENT.encode("utf-8"), "text/markdown")}
        r = client.post("/api/ingestion/uploads", files=files)
        assert r.status_code == 200, r.text
        upload = r.json()
        upload_id = upload["upload_id"]
        assert len(upload_id) >= 32  # 合法 UUID

        # STEP2 创建预览任务
        r = client.post(
            "/api/ingestion/jobs/preview",
            json={
                "upload_id": upload_id,
                "source_type": "markdown",
                "title": TEST_TITLE,
                "business_domain": "equipment",
                "doc_type": "manual",
                "options": {"chunk_size": 600, "chunk_overlap": 80},
            },
        )
        assert r.status_code == 200, r.text
        job = r.json()
        job_id = job.get("id") or job.get("job_id")
        assert job_id

        # STEP3 解析完成，chunks > 0（验证 F1）
        done = _wait_status(client, job_id, {"completed", "failed"})
        assert done["status"] == "completed", f"preview failed: {done}"

        # STEP4 读预览，chunks 非空
        r = client.get(f"/api/ingestion/jobs/{job_id}/preview")
        assert r.status_code == 200
        preview = r.json()
        assert preview["stats"]["chunks"] > 0, f"chunks should be > 0, got {preview['stats']}"
        assert len(preview["chunks"]) > 0

        # STEP5 入库
        r = client.post(f"/api/ingestion/jobs/{job_id}/commit", json={"replace": False})
        assert r.status_code == 200, r.text
        committed = _wait_status(client, job_id, {"completed", "failed"})
        assert committed["status"] == "completed", f"commit failed: {committed}"

        # STEP6 查结果，inserted.documents=1 且 chunks>0（验证 F2）
        r = client.get(f"/api/ingestion/jobs/{job_id}/result")
        assert r.status_code == 200
        result = r.json()
        assert "inserted" in result, f"result must contain inserted: {result}"
        assert result["inserted"]["documents"] == 1
        assert result["inserted"]["chunks"] > 0

        # STEP7 知识库闭环：/knowledge/documents 能查到新入库文档（验证 F5）
        r = client.get("/api/knowledge/documents")
        assert r.status_code == 200
        docs = r.json()["documents"]
        assert any(d["title"] == TEST_TITLE for d in docs), "新文档应出现在知识库"

        # STEP9 删除（含可能的错误记录）
        r = client.delete(f"/api/ingestion/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
    finally:
        _cleanup(client)


def test_create_preview_invalid_upload_id_returns_400(client):
    # STEP10 边界：upload_id 传文件名 → 400
    r = client.post(
        "/api/ingestion/jobs/preview",
        json={"upload_id": "README.md", "source_type": "markdown"},
    )
    assert r.status_code == 400
    assert "upload_id" in r.json()["detail"]


def test_create_preview_nonexistent_upload_returns_404(client):
    # 合法 UUID 但不存在的 upload → 404（而非外键 500）
    import uuid

    r = client.post(
        "/api/ingestion/jobs/preview",
        json={"upload_id": str(uuid.uuid4()), "source_type": "markdown"},
    )
    assert r.status_code == 404
    assert "Upload not found" in r.json()["detail"]


def test_retry_job_creates_new_job(client):
    # STEP8 重试：用真实上传创建预览任务，retry 应生成新的 job
    try:
        files = {"file": (TEST_FILE, MD_CONTENT.encode("utf-8"), "text/markdown")}
        up = client.post("/api/ingestion/uploads", files=files).json()
        r = client.post(
            "/api/ingestion/jobs/preview",
            json={"upload_id": up["upload_id"], "source_type": "markdown", "title": TEST_TITLE},
        )
        assert r.status_code == 200
        job_id = r.json().get("id") or r.json().get("job_id")
        _wait_status(client, job_id, {"completed", "failed"})
        r = client.post(f"/api/ingestion/jobs/{job_id}/retry")
        assert r.status_code == 200, r.text
        new_id = r.json().get("id") or r.json().get("job_id")
        assert new_id and new_id != job_id
        client.delete(f"/api/ingestion/jobs/{new_id}")
        client.delete(f"/api/ingestion/jobs/{job_id}")
    finally:
        _cleanup(client)


def test_llm_enrich_unavailable_is_graceful():
    # 无 LLM key 时：is_available False，enrich_chunks 原样返回，不阻断
    import os
    from app.services import llm_enrich

    old = os.environ.pop("LLM_API_KEY", None)
    try:
        assert llm_enrich.is_available() is False
        chunks = [{"content": "测试内容", "summary": "", "preset_questions": []}]
        out = asyncio.run(
            llm_enrich.enrich_chunks(chunks, gen_summary=True, gen_questions=True)
        )
        assert out[0]["summary"] == ""
        assert out[0]["preset_questions"] == []
    finally:
        if old is not None:
            os.environ["LLM_API_KEY"] = old


def test_pipeline_with_llm_flags_still_ingests(client):
    # 勾选 LLM 开关但无 key：应正常入库（chunks>0），预设问题为空
    try:
        files = {"file": (TEST_FILE, MD_CONTENT.encode("utf-8"), "text/markdown")}
        up = client.post("/api/ingestion/uploads", files=files).json()
        r = client.post(
            "/api/ingestion/jobs/preview",
            json={
                "upload_id": up["upload_id"],
                "source_type": "markdown",
                "title": TEST_TITLE,
                "options": {"generate_summary": True, "generate_questions": True},
            },
        )
        assert r.status_code == 200
        job_id = r.json().get("id") or r.json().get("job_id")
        done = _wait_status(client, job_id, {"completed", "failed"})
        assert done["status"] == "completed", f"preview failed: {done}"
        pv = client.get(f"/api/ingestion/jobs/{job_id}/preview").json()
        assert pv["stats"]["chunks"] > 0
        # 无 LLM 时预设问题应为空（不再走规则关键词）
        assert all(len(c.get("preset_questions", [])) == 0 for c in pv["chunks"])
        client.delete(f"/api/ingestion/jobs/{job_id}")
    finally:
        _cleanup(client)


