import uuid
from .schemas import Document, Chunk, Asset, DataAsset


async def ingest_document(document: Document, adapter):
    """将 ``Document`` 及其所有 Chunk 写入存储。

    调用流程：

    1. 通过 ``adapter`` 将文档元信息写入数据库，获取 ``doc_id``。
    2. 遍历 ``document.chunks``，对每个 Chunk 调用 ``adapter.create_chunk``。

    Args:
        document: 待入库的 ``Document`` 对象。
        adapter: 实现了 ``create_document`` 和 ``create_chunk`` 接口的适配器。

    Returns:
        新文档的 ID（由 ``adapter.create_document`` 返回）。
    """
    doc_id = await adapter.create_document(document)

    for chunk in document.chunks:
        chunk_id = await adapter.create_chunk(doc_id, chunk)

    return doc_id


async def ingest_data_asset(asset: DataAsset, adapter):
    """将 ``DataAsset`` 写入存储。

    Args:
        asset: 待入库的 ``DataAsset``。
        adapter: 实现了 ``create_data_asset`` 接口的适配器。

    Returns:
        新数据资产的 ID（由 ``adapter.create_data_asset`` 返回）。
    """
    return await adapter.create_data_asset(asset)