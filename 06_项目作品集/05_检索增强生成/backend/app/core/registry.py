from typing import Any, Dict, List, Optional
from .schemas import CapabilityRegistry


class CapabilityRegistryService:
    def __init__(self):
        self._backends: Dict[str, CapabilityRegistry] = {}
        self._adapters: Dict[str, Any] = {}

    def register(self, backend: CapabilityRegistry, adapter: Optional[Any] = None):
        self._backends[backend.backend_id] = backend
        if adapter is not None:
            self._adapters[backend.backend_id] = adapter

    def get_adapter(self, backend_id: str):
        return self._adapters.get(backend_id)

    def get(self, backend_id: str):
        return self.get_adapter(backend_id)

    def get_capabilities(self, backend_id: str) -> List[str]:
        backend = self._backends.get(backend_id)
        return backend.capabilities if backend else []

    def list_backends(self) -> List[str]:
        return list(self._backends.keys())

    def get_all_registry(self) -> List[CapabilityRegistry]:
        return list(self._backends.values())

    def has_capability(self, backend_id: str, capability: str) -> bool:
        backend = self._backends.get(backend_id)
        return capability in backend.capabilities if backend else False


registry_service = CapabilityRegistryService()

registry_service.register(
    CapabilityRegistry(
        backend_id="postgres_pgvector",
        capabilities=[
            "vector_search",
            "metadata_filter",
            "chunk_fetch",
            "parent_expand",
            "asset_fetch",
            "data_asset_search",
            "rerank"
        ]
    )
)
