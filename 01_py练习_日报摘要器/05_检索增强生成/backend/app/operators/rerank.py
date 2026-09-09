from ..core.schemas import ExecutionContext, RetrievalStep
from ..services.reranker_client import reranker_service


class RerankOperator:
    name = "rerank"

    async def run(
        self,
        step: RetrievalStep,
        context: ExecutionContext,
        adapter_registry,
    ) -> ExecutionContext:
        if not context.evidence:
            return context

        params = step.params or {}
        top_k = params.get("top_k") or len(context.evidence)
        max_chars = params.get("max_chars", 2000)
        required = bool(params.get("required", False))

        if not reranker_service.is_available():
            if required:
                raise RuntimeError("Reranker API is not configured. Set RERANKER_BASE_URL, RERANKER_API_KEY and RERANKER_MODEL.")
            context.evidence = context.evidence[:top_k]
            return context

        documents = [
            f"{item.title_context or item.section_path}\n{item.content}"[:max_chars]
            for item in context.evidence
        ]
        results = await reranker_service.rerank(context.query, documents, top_k=top_k)

        reranked = []
        for result in results[:top_k]:
            item = context.evidence[result.index]
            physical_context = dict(item.physical_context or {})
            physical_context["vector_score"] = item.score
            physical_context["rerank_score"] = result.score
            item.physical_context = physical_context
            item.score = result.score
            reranked.append(item)

        context.evidence = reranked
        return context
