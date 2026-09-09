from .base import BaseOperator
from .vector_search import VectorSearchOperator
from .parent_expand import ParentExpandOperator
from .asset_fetch import AssetFetchOperator
from .data_asset_search import DataAssetSearchOperator
from .rerank import RerankOperator


operator_registry = {
    "vector_search": VectorSearchOperator(),
    "parent_expand": ParentExpandOperator(),
    "asset_fetch": AssetFetchOperator(),
    "data_asset_search": DataAssetSearchOperator(),
    "rerank": RerankOperator(),
}


def get(operator_name: str):
    return operator_registry.get(operator_name)
