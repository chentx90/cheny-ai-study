from typing import Optional
from ..core.schemas import ExecutionContext, RetrievalStep


class BaseOperator:
    name: str = "base"

    async def run(
        self,
        step: RetrievalStep,
        context: ExecutionContext,
        adapter_registry,
    ) -> ExecutionContext:
        raise NotImplementedError