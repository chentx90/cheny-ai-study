from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ..core.registry import registry_service

router = APIRouter()


def _adapter():
    a = registry_service.get_adapter("postgres_pgvector")
    if a is None:
        raise HTTPException(503, "postgres adapter not registered")
    return a


@router.get("/knowledge/documents")
async def list_documents(
    business_domain: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    return {"documents": await _adapter().list_documents(limit, business_domain, keyword)}


@router.get("/knowledge/documents/{doc_id}/chunks")
async def list_chunks(doc_id: str):
    return {"chunks": await _adapter().list_chunks(doc_id)}


@router.delete("/knowledge/documents/{doc_id}")
async def delete_document(doc_id: str):
    ok = await _adapter().delete_document(doc_id)
    if not ok:
        raise HTTPException(404, "Document not found or already archived")
    return {"deleted": True}


@router.get("/knowledge/data-assets")
async def list_data_assets(
    keyword: Optional[str] = None,
    business_domain: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    return {"data_assets": await _adapter().list_data_assets(keyword, business_domain, limit)}


@router.delete("/knowledge/data-assets/{asset_id}")
async def delete_data_asset(asset_id: str):
    ok = await _adapter().delete_data_asset(asset_id)
    if not ok:
        raise HTTPException(404, "Data asset not found or already archived")
    return {"deleted": True}
