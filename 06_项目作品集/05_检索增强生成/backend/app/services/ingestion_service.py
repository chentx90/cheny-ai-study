import asyncio
import json
import traceback
from pathlib import Path
from typing import Optional
import asyncpg
import aiofiles

from .upload_service import UploadService
from .ingestion_job_store import IngestionJobStore
from .parse_service import parse
from .commit_service import find_active_doc_by_hash, archive_doc, next_available_title, read_preview_doc
from .db_writer import write_document_with_chunks, write_data_asset
from .file_asset_service import FileAssetService
from .object_storage import ObjectStorageService
from .review_service import ReviewService


class DuplicateDocumentError(Exception):
    def __init__(self, existing_id: str, existing_title: str):
        self.existing_id = existing_id
        self.existing_title = existing_title
        super().__init__(f"Document already exists: {existing_title} ({existing_id})")


class IngestionService:
    """薄编排层：管理任务生命周期，将解析/提交委托给专项服务。"""

    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
        self.object_storage = ObjectStorageService()
        self.file_asset_service = FileAssetService(db_pool, self.object_storage)
        self.upload_service = UploadService(db_pool, self.file_asset_service)
        self.job_store = IngestionJobStore(db_pool)
        self.review_service = ReviewService(db_pool)
        self.output_dir = Path(__file__).parent.parent.parent / "output" / "ingestion"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(__file__).parent.parent.parent / "tmp" / "ingestion"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # ── 公开 API ──────────────────────────────────────────────

    async def create_preview_job(self, upload_id, source_type, title=None, business_domain=None,
                                  doc_type=None, version=None, options=None) -> dict:
        job = await self.job_store.create_job(
            source_type=source_type, title=title, business_domain=business_domain,
            doc_type=doc_type, version=version, mode="preview", options=options, upload_id=upload_id,
        )
        asyncio.create_task(self._run_preview(job["id"]))
        return job

    async def create_preview_job_for_asset(self, file_asset_id, source_type, title=None, business_domain=None,
                                           doc_type=None, version=None, options=None) -> dict:
        file_asset = await self.file_asset_service.get_asset(str(file_asset_id))
        if not file_asset:
            raise FileNotFoundError(f"File asset not found: {file_asset_id}")
        upload = await self.upload_service.ensure_upload_for_asset(file_asset)
        return await self.create_preview_job(
            upload_id=upload["upload_id"],
            source_type=source_type,
            title=title or file_asset.get("original_filename"),
            business_domain=business_domain or file_asset.get("business_domain") or "general",
            doc_type=doc_type,
            version=version,
            options=options,
        )

    async def create_ingest_job(self, upload_id, source_type, title=None, business_domain=None,
                                 doc_type=None, version=None, options=None) -> dict:
        job = await self.job_store.create_job(
            source_type=source_type, title=title, business_domain=business_domain,
            doc_type=doc_type, version=version, mode="ingest", options=options, upload_id=upload_id,
        )
        asyncio.create_task(self._run_ingest(job["id"]))
        return job

    async def commit_job(self, job_id: str, on_duplicate: str = "block") -> dict:
        job = await self.job_store.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        if job["status"] != "completed":
            raise ValueError("Job must be completed before commit")

        result = job.get("result") or {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                result = {}
        parsed_document_id = result.get("parsed_document_id")
        if parsed_document_id:
            return await self.review_service.approve(parsed_document_id, on_duplicate=on_duplicate)

        if job["mode"] != "preview":
            raise ValueError("Legacy commit requires a completed preview job")

        pdoc = await read_preview_doc(job.get("preview_uri"))
        content_hash = (pdoc or {}).get("content_hash")
        domain = (pdoc or {}).get("business_domain") or job.get("business_domain") or "general"
        if content_hash and on_duplicate == "block":
            existing = await find_active_doc_by_hash(self.db_pool, content_hash, domain)
            if existing:
                raise DuplicateDocumentError(existing["id"], existing["title"])

        await self.job_store.update_status(job_id, status="writing", stage="writing", progress=0)
        asyncio.create_task(self._run_commit(job_id, on_duplicate))
        return await self.job_store.get_job(job_id)

    # ── 后台任务 ──────────────────────────────────────────────

    async def _run_preview(self, job_id: str):
        job = await self.job_store.get_job(job_id)
        if not job:
            return
        upload = await self.upload_service.get_upload(job.get("upload_id", ""))
        if not upload:
            await self.job_store.update_status(job_id, status="failed", stage="error", error_count=1)
            await self.job_store.add_error(job_id, "upload", "Upload record not found")
            return
        try:
            await self.job_store.update_status(job_id, status="parsing", stage="parsing", progress=10)
            upload = await self._materialize_upload(upload)
            parsed = await parse(upload, job)
            review = await self.review_service.save_parsed_draft(parsed, job, upload)
            await self.job_store.update_status(job_id, status="review", stage="review", progress=60)
            preview_path = self.output_dir / f"{job_id}_preview.json"
            async with aiofiles.open(preview_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(parsed, ensure_ascii=False, indent=2))
            await self.job_store.update_status(
                job_id, status="completed", stage="preview", progress=100,
                preview_uri=str(preview_path),
                result={
                    **{k: len(parsed.get(k, [])) for k in ("pages", "chunks", "data_assets", "sheets", "errors")},
                    "parsed_document_id": str(review["id"]),
                    "file_asset_id": str(upload.get("file_asset_id")) if upload.get("file_asset_id") else None,
                },
            )
            for err in parsed.get("errors", []):
                await self.job_store.add_error(job_id, err.get("stage", "parse"), err.get("message", ""))
        except Exception as exc:
            await self.job_store.update_status(job_id, status="failed", stage="error", error_count=1)
            await self.job_store.add_error(job_id, "runtime", str(exc), raw_error=traceback.format_exc())

    async def _run_ingest(self, job_id: str):
        job = await self.job_store.get_job(job_id)
        if not job:
            return
        upload = await self.upload_service.get_upload(job.get("upload_id", ""))
        if not upload:
            await self.job_store.update_status(job_id, status="failed", stage="error", error_count=1)
            await self.job_store.add_error(job_id, "upload", "Upload record not found")
            return
        try:
            await self.job_store.update_status(job_id, status="parsing", stage="parsing", progress=10)
            upload = await self._materialize_upload(upload)
            parsed = await parse(upload, job)
            review = await self.review_service.save_parsed_draft(parsed, job, upload)
            preview_path = self.output_dir / f"{job_id}_preview.json"
            async with aiofiles.open(preview_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(parsed, ensure_ascii=False, indent=2))
            await self.job_store.update_status(
                job_id,
                status="completed",
                stage="review",
                progress=100,
                preview_uri=str(preview_path),
                result={
                    **{k: len(parsed.get(k, [])) for k in ("pages", "chunks", "data_assets", "sheets", "errors")},
                    "parsed_document_id": str(review["id"]),
                    "file_asset_id": str(upload.get("file_asset_id")) if upload.get("file_asset_id") else None,
                    "requires_approval": True,
                },
            )
        except Exception as exc:
            await self.job_store.update_status(job_id, status="failed", stage="error", error_count=1)
            await self.job_store.add_error(job_id, "runtime", str(exc), raw_error=traceback.format_exc())

    async def _run_commit(self, job_id: str, on_duplicate: str = "block"):
        job = await self.job_store.get_job(job_id)
        if not job:
            return
        preview_path = job.get("preview_uri")
        if not preview_path or not Path(preview_path).exists():
            await self.job_store.update_status(job_id, status="failed", stage="error", error_count=1)
            await self.job_store.add_error(job_id, "preview", "Preview file not found")
            return
        try:
            async with aiofiles.open(preview_path, "r", encoding="utf-8") as f:
                parsed = json.loads(await f.read())
            pdoc = parsed.get("document") or {}
            content_hash = pdoc.get("content_hash")
            domain = pdoc.get("business_domain") or job.get("business_domain") or "general"

            if content_hash and on_duplicate == "replace":
                existing = await find_active_doc_by_hash(self.db_pool, content_hash, domain)
                if existing:
                    await archive_doc(self.db_pool, existing["id"])

            if pdoc.get("title"):
                pdoc["title"] = await next_available_title(self.db_pool, pdoc["title"], domain)

            inserted = await self._write_to_db(parsed, job)
            await self.job_store.update_status(job_id, status="completed", stage="completed", progress=100, result=inserted)
        except Exception as exc:
            await self.job_store.update_status(job_id, status="failed", stage="error", error_count=1)
            await self.job_store.add_error(job_id, "commit", str(exc), raw_error=traceback.format_exc())

    # ── 写库 ──────────────────────────────────────────────────

    async def _write_to_db(self, parsed: dict, job: dict) -> dict:
        inserted = {"documents": 0, "chunks": 0, "assets": 0, "data_assets": 0,
                    "failed": {"chunks": 0, "assets": 0, "data_assets": 0}}
        if parsed.get("document"):
            pdoc = parsed["document"]
            doc = {
                "title": pdoc.get("title") or job.get("title") or "未命名文档",
                "doc_type": pdoc.get("doc_type") or job.get("doc_type") or "manual",
                "source_uri": pdoc.get("source_uri"),
                "business_domain": pdoc.get("business_domain") or job.get("business_domain") or "general",
                "version": job.get("version") or "1.0",
                "content_hash": pdoc.get("content_hash"),
                "status": "active",
            }
            await write_document_with_chunks(self.db_pool, doc, parsed.get("chunks", []))
            inserted["documents"] += 1
            inserted["chunks"] += len(parsed.get("chunks", []))
        for da in parsed.get("data_assets", []):
            try:
                await write_data_asset(self.db_pool, {
                    "asset_type": da.get("asset_type", ""),
                    "name": da.get("name", ""),
                    "description": da.get("description", ""),
                    "business_domain": da.get("business_domain") or job.get("business_domain") or "general",
                    "parent_name": da.get("parent_name"),
                    "synonyms": da.get("synonyms") if isinstance(da.get("synonyms"), list) else [],
                    "formula": da.get("formula"),
                    "related_table": da.get("related_table"),
                    "related_columns": da.get("related_columns") if isinstance(da.get("related_columns"), list) else [],
                    "example_values": da.get("example_values") if isinstance(da.get("example_values"), dict) else None,
                })
                inserted["data_assets"] += 1
            except Exception:
                inserted["failed"]["data_assets"] += 1
        return inserted

    async def _materialize_upload(self, upload: dict) -> dict:
        file_asset_id = upload.get("file_asset_id")
        if not file_asset_id:
            return upload
        file_asset = await self.file_asset_service.get_asset(str(file_asset_id))
        if not file_asset:
            return upload
        local_path = await self.file_asset_service.materialize_to_temp(file_asset, self.temp_dir)
        result = dict(upload)
        result["storage_uri"] = str(local_path)
        result["file_asset"] = file_asset
        return result
