from __future__ import annotations

from dataclasses import dataclass

from ai_video_manager.infrastructure.db.production_repository import ProductionRepository
from ai_video_manager.llm import LLMClient


@dataclass(slots=True)
class TrackedLLMClient:
    inner: LLMClient
    repository: ProductionRepository
    use_case: str
    project_id: str
    episode_id: str | None = None
    prompt_card_id: str | None = None
    template_id: str | None = None
    template_version: int | None = None

    @property
    def provider(self) -> str:
        return self.inner.provider

    @property
    def model(self) -> str:
        return self.inner.model

    def test_connection(self) -> dict[str, object]:
        return self.inner.test_connection()

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 100000,
        system_prompt: str = "",
        json_mode: bool | None = None,
    ) -> str:
        run_id = self.repository.start_ai_run(
            use_case=self.use_case,
            project_id=self.project_id,
            episode_id=self.episode_id,
            prompt_card_id=self.prompt_card_id,
            provider_profile_id=self.provider,
            model=self.model,
            template_id=self.template_id,
            template_version=self.template_version,
            input_snapshot={
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            },
        )
        try:
            result = self.inner.complete(
                prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                json_mode=json_mode,
            )
        except Exception as exc:
            self.repository.fail_ai_run(run_id, error_code="llm_call_failed", message=str(exc))
            raise
        self.repository.succeed_ai_run(run_id, {"content": result})
        return result

