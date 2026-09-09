from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import json
import uuid
from pathlib import Path

from ..services.ingestion_service import IngestionService, DuplicateDocumentError

router = APIRouter()


def get_ingestion_service(request: Request) -> IngestionService:
    svc = getattr(request.app.state, "ingestion_service", None)
    if svc is None:
        raise HTTPException(503, "Ingestion service not initialized")
    return svc


def _validate_upload_id(upload_id: str) -> None:
    try:
        uuid.UUID(str(upload_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, f"Invalid upload_id: {upload_id!r}. 请先上传文件并使用返回的 upload_id。")


async def _ensure_upload_exists(service: IngestionService, upload_id: str) -> None:
    if not await service.upload_service.get_upload(upload_id):
        raise HTTPException(404, f"Upload not found: {upload_id}. 请先上传文件。")


def _validate_source_type_match(source_type: str) -> None:
    ALLOWED_SOURCE_TYPES = {"pdf", "excel", "markdown", "json", "csv", "txt", "docx", "pptx"}
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise HTTPException(400, f"不支持的 source_type: {source_type}，支持：{sorted(ALLOWED_SOURCE_TYPES)}")


def _source_type_from_name(file_name: str) -> Optional[str]:
    ext = Path(file_name or "").suffix.lstrip(".").lower()
    return FILE_TYPE_TO_SOURCE.get(ext)


FILE_TYPE_TO_SOURCE: dict[str, str] = {
    "pdf": "pdf", "md": "markdown", "markdown": "markdown",
    "xlsx": "excel", "xls": "excel",
    "json": "json", "csv": "csv", "txt": "txt", "docx": "docx", "pptx": "pptx",
}


async def _validate_source_type(service: IngestionService, upload_id: str, source_type: str) -> None:
    upload = await service.upload_service.get_upload(upload_id)
    if not upload:
        raise HTTPException(404, f"Upload not found: {upload_id}")
    ext = Path(upload.get("file_name", "")).suffix.lstrip(".").lower()
    expected = FILE_TYPE_TO_SOURCE.get(ext)
    if expected and source_type != expected and source_type not in (None, ""):
        raise HTTPException(400, f"文件扩展名 .{ext} 与所选 source_type '{source_type}' 不匹配，应为 '{expected}'")


# PreviewRequest 和 IngestRequest 原本10字段完全相同 → 合并为一个
class JobRequest(BaseModel):
    upload_id: str
    source_type: str
    title: Optional[str] = None
    business_domain: Optional[str] = None
    doc_type: Optional[str] = None
    version: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class AssetJobRequest(BaseModel):
    source_type: str
    title: Optional[str] = None
    business_domain: Optional[str] = None
    doc_type: Optional[str] = None
    version: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class BatchAssetJobRequest(BaseModel):
    file_asset_ids: List[str]
    business_domain: Optional[str] = None
    doc_type: Optional[str] = None
    version: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class CommitRequest(BaseModel):
    on_duplicate: str = "block"  # block | replace | new


class BatchImportRequest(BaseModel):
    root_path: str
    business_domain: str = "general"
    batch_name: Optional[str] = None


class ApproveRequest(BaseModel):
    on_duplicate: str = "block"


class RejectRequest(BaseModel):
    reason: str = ""


ALLOWED_EXTENSIONS = {"pdf", "md", "markdown", "xlsx", "xls", "json", "csv", "txt", "docx", "pptx"}
MAX_BYTES = 50 * 1024 * 1024  # 50 MB

@router.post("/ingestion/uploads")
async def upload_file(
    file: UploadFile = File(...),
    business_domain: str = "general",
    service: IngestionService = Depends(get_ingestion_service),
):
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: .{ext}，支持：{sorted(ALLOWED_EXTENSIONS)}")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"文件超过 {MAX_BYTES // 1024 // 1024} MB 限制")
    try:
        return await service.upload_service.save_upload(
            file.filename,
            content,
            file.content_type or "application/octet-stream",
            business_domain=business_domain,
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/file-assets/upload")
async def upload_file_asset(
    file: UploadFile = File(...),
    business_domain: str = "general",
    service: IngestionService = Depends(get_ingestion_service),
):
    return await upload_file(file=file, business_domain=business_domain, service=service)


@router.get("/file-assets")
async def list_file_assets(limit: int = 50, business_domain: Optional[str] = None, service: IngestionService = Depends(get_ingestion_service)):
    return {"file_assets": await service.file_asset_service.list_assets(limit=limit, business_domain=business_domain)}


@router.post("/file-assets/preview-batch")
async def create_preview_jobs_from_assets(req: BatchAssetJobRequest, service: IngestionService = Depends(get_ingestion_service)):
    jobs = []
    failed = []
    for file_asset_id in req.file_asset_ids:
        try:
            asset = await service.file_asset_service.get_asset(str(file_asset_id))
            if not asset:
                failed.append({"file_asset_id": file_asset_id, "error": "File asset not found"})
                continue
            source_type = _source_type_from_name(asset.get("original_filename", ""))
            if not source_type:
                failed.append({"file_asset_id": file_asset_id, "file": asset.get("original_filename"), "error": "Unsupported file extension"})
                continue
            _validate_source_type_match(source_type)
            job = await service.create_preview_job_for_asset(
                file_asset_id=file_asset_id,
                source_type=source_type,
                title=asset.get("original_filename"),
                business_domain=req.business_domain or asset.get("business_domain") or "general",
                doc_type=req.doc_type or source_type,
                version=req.version,
                options=req.options,
            )
            jobs.append({"job_id": job.get("id"), "file_asset_id": file_asset_id, "source_type": source_type, **{k: v for k, v in job.items() if k != "id"}})
        except Exception as exc:
            failed.append({"file_asset_id": file_asset_id, "error": str(exc)})
    return {"jobs": jobs, "failed": failed}


@router.get("/file-assets/{file_asset_id}")
async def get_file_asset(file_asset_id: str, service: IngestionService = Depends(get_ingestion_service)):
    asset = await service.file_asset_service.get_asset(file_asset_id)
    if not asset:
        raise HTTPException(404, "File asset not found")
    return asset


@router.delete("/file-assets/{file_asset_id}")
async def delete_file_asset(file_asset_id: str, service: IngestionService = Depends(get_ingestion_service)):
    try:
        ok = await service.file_asset_service.delete_asset(file_asset_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not ok:
        raise HTTPException(404, "File asset not found")
    return {"deleted": True}


@router.post("/file-assets/import-batch")
async def import_file_batch(req: BatchImportRequest, service: IngestionService = Depends(get_ingestion_service)):
    try:
        return await service.file_asset_service.import_folder(
            req.root_path,
            business_domain=req.business_domain,
            batch_name=req.batch_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/ingestion/uploads")
async def list_uploads(limit: int = 50, service: IngestionService = Depends(get_ingestion_service)):
    return {"uploads": await service.upload_service.list_uploads(limit)}


@router.post("/ingestion/jobs/preview")
async def create_preview_job(req: JobRequest, service: IngestionService = Depends(get_ingestion_service)):
    _validate_upload_id(req.upload_id)
    await _validate_source_type(service, req.upload_id, req.source_type)
    _validate_source_type_match(req.source_type)
    try:
        job = await service.create_preview_job(
            upload_id=req.upload_id, source_type=req.source_type,
            title=req.title, business_domain=req.business_domain,
            doc_type=req.doc_type, version=req.version, options=req.options,
        )
        return {"job_id": job.get("id"), **{k: v for k, v in job.items() if k != "id"}}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/file-assets/{file_asset_id}/preview")
async def create_preview_job_from_asset(file_asset_id: str, req: AssetJobRequest, service: IngestionService = Depends(get_ingestion_service)):
    _validate_source_type_match(req.source_type)
    try:
        job = await service.create_preview_job_for_asset(
            file_asset_id=file_asset_id,
            source_type=req.source_type,
            title=req.title,
            business_domain=req.business_domain,
            doc_type=req.doc_type,
            version=req.version,
            options=req.options,
        )
        return {"job_id": job.get("id"), **{k: v for k, v in job.items() if k != "id"}}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/ingestion/jobs")
async def create_ingest_job(req: JobRequest, service: IngestionService = Depends(get_ingestion_service)):
    _validate_upload_id(req.upload_id)
    await _validate_source_type(service, req.upload_id, req.source_type)
    _validate_source_type_match(req.source_type)
    try:
        job = await service.create_ingest_job(
            upload_id=req.upload_id, source_type=req.source_type,
            title=req.title, business_domain=req.business_domain,
            doc_type=req.doc_type, version=req.version, options=req.options,
        )
        return {"job_id": job.get("id"), **{k: v for k, v in job.items() if k != "id"}}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/ingestion/jobs")
async def list_jobs(status: Optional[str] = None, limit: int = 50, service: IngestionService = Depends(get_ingestion_service)):
    jobs = await service.job_store.list_jobs(status=status, limit=limit)
    return {"jobs": [{**j, "job_id": j.pop("id")} if "id" in j else j for j in jobs]}


@router.get("/ingestion/jobs/{job_id}")
async def get_job(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    job = await service.job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("upload_id"):
        job["upload"] = await service.upload_service.get_upload(job["upload_id"])
    if "id" in job:
        job["job_id"] = job.pop("id")
    return job


@router.get("/ingestion/jobs/{job_id}/preview")
async def get_job_preview(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    job = await service.job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    preview_uri = job.get("preview_uri")
    if not preview_uri:
        return {"job_id": job_id, "document": None, "chunks": [], "data_assets": [], "sheets": [], "errors": [], "stats": {}}
    try:
        with open(preview_uri, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise HTTPException(500, f"Failed to load preview: {exc}")


@router.post("/ingestion/jobs/{job_id}/commit")
async def commit_job(job_id: str, req: CommitRequest, service: IngestionService = Depends(get_ingestion_service)):
    if req.on_duplicate not in ("block", "replace", "new"):
        raise HTTPException(400, f"Invalid on_duplicate: {req.on_duplicate}")
    try:
        return await service.commit_job(job_id, on_duplicate=req.on_duplicate)
    except DuplicateDocumentError as exc:
        raise HTTPException(409, {"message": "文档内容已存在", "existing_id": exc.existing_id, "existing_title": exc.existing_title})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/parsed-documents/{parsed_document_id}/review")
async def get_parsed_document_review(parsed_document_id: str, service: IngestionService = Depends(get_ingestion_service)):
    review = await service.review_service.get_review(parsed_document_id)
    if not review:
        raise HTTPException(404, "Parsed document not found")
    return review


@router.post("/parsed-documents/{parsed_document_id}/approve")
async def approve_parsed_document(parsed_document_id: str, req: ApproveRequest, service: IngestionService = Depends(get_ingestion_service)):
    if req.on_duplicate not in ("block", "replace", "new"):
        raise HTTPException(400, f"Invalid on_duplicate: {req.on_duplicate}")
    try:
        return await service.review_service.approve(parsed_document_id, on_duplicate=req.on_duplicate)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/parsed-documents/{parsed_document_id}/reject")
async def reject_parsed_document(parsed_document_id: str, req: RejectRequest, service: IngestionService = Depends(get_ingestion_service)):
    try:
        return await service.review_service.reject(parsed_document_id, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.delete("/parsed-documents/{parsed_document_id}")
async def delete_parsed_document(parsed_document_id: str, service: IngestionService = Depends(get_ingestion_service)):
    try:
        ok = await service.review_service.delete_draft(parsed_document_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not ok:
        raise HTTPException(404, "Parsed document not found")
    return {"deleted": True}


@router.get("/ingestion/jobs/{job_id}/result")
async def get_job_result(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    job = await service.job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    raw = job.get("result") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    return {
        "job_id": job_id,
        "status": job["status"],
        "inserted": {"documents": raw.get("documents", 0), "chunks": raw.get("chunks", 0), "assets": raw.get("assets", 0), "data_assets": raw.get("data_assets", 0)},
        "failed": raw.get("failed", {}),
    }


@router.get("/ingestion/jobs/{job_id}/errors")
async def get_job_errors(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    if not await service.job_store.get_job(job_id):
        raise HTTPException(404, "Job not found")
    return {"errors": await service.job_store.get_errors(job_id)}


@router.delete("/ingestion/jobs/{job_id}")
async def delete_job(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    try:
        if not await service.job_store.delete_job(job_id):
            raise HTTPException(404, "Job not found")
        return {"deleted": True}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/ingestion/jobs/{job_id}/retry")
async def retry_job(job_id: str, service: IngestionService = Depends(get_ingestion_service)):
    job = await service.job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    # 保持原始 mode：ingest job 重试仍为 ingest，不静默降级为 preview
    mode = job.get("mode", "preview")
    creator = service.create_ingest_job if mode == "ingest" else service.create_preview_job
    job = await creator(
        upload_id=job.get("upload_id"),
        source_type=job.get("source_type", "pdf"),
        title=job.get("title"),
        business_domain=job.get("business_domain"),
        doc_type=job.get("doc_type"),
        version=job.get("version"),
        options=job.get("options"),
    )
    return {"job_id": job.get("id"), **{k: v for k, v in job.items() if k != "id"}}
