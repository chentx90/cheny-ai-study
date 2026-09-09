import time
import asyncio
from typing import Optional
from .schemas import (
    ExecutionContext,
    RetrievalMethod,
    RetrievalStep,
    TraceStep,
)


class ExecutionEngine:
    def __init__(self, operator_registry, adapter_registry):
        self.operator_registry = operator_registry
        self.adapter_registry = adapter_registry

    async def execute(self, method: RetrievalMethod, context: ExecutionContext) -> ExecutionContext:
        start_time = time.time()
        
        for step in method.steps:
            step_start = time.time()
            input_count = max(len(context.evidence), len(context.data_assets), len(context.assets))
            
            try:
                operator = self.operator_registry.get(step.operator)
                if operator is None:
                    context.trace_steps.append(
                        TraceStep(
                            name=step.name,
                            operator=step.operator,
                            backend=step.backend,
                            status="error",
                            latency_ms=int((time.time() - step_start) * 1000),
                            input_count=input_count,
                            output_count=0,
                            error=f"Operator not found: {step.operator}"
                        )
                    )
                    continue
                
                context = await operator.run(step, context, self.adapter_registry)
                status = "ok"
                error = None
                output_count = max(len(context.evidence), len(context.data_assets), len(context.assets))
            except Exception as exc:
                status = "error"
                error = str(exc)
                output_count = input_count
            
            context.trace_steps.append(
                TraceStep(
                    name=step.name,
                    operator=step.operator,
                    backend=step.backend,
                    status=status,
                    latency_ms=int((time.time() - step_start) * 1000),
                    input_count=input_count,
                    output_count=output_count,
                    error=error
                )
            )
        
        context.trace_steps.insert(0, TraceStep(
            name="total",
            operator="execution_engine",
            backend="local",
            status="ok",
            latency_ms=int((time.time() - start_time) * 1000),
            input_count=1,
            output_count=max(len(context.evidence), len(context.data_assets), len(context.assets))
        ))
        
        return context