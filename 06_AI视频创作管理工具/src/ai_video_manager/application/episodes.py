from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ai_video_manager.domain import Episode
from ai_video_manager.infrastructure.db.production_repository import ProductionRepository


class RevisionConflict(ValueError):
    pass


class EpisodeService:
    def __init__(self, repository: ProductionRepository) -> None:
        self.repository = repository

    def list(self, project_id: str) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.repository.list_episodes(project_id)]

    def create(
        self,
        project_id: str,
        *,
        order: int,
        title: str,
        source_text: str,
        script_text: str = "",
    ) -> dict[str, Any]:
        episode = Episode(
            project_id=project_id,
            order=order,
            title=title.strip() or f"第{order}集",
            source_text=source_text,
        )
        if script_text.strip():
            episode.save_script(script_text)
        return asdict(self.repository.save_episode(episode))

    def update(
        self,
        project_id: str,
        episode_id: str,
        *,
        revision: int,
        title: str | None = None,
        source_text: str | None = None,
        script_text: str | None = None,
    ) -> dict[str, Any]:
        episode = self.repository.get_episode(project_id, episode_id)
        if episode.revision != revision:
            raise RevisionConflict(
                f"Episode revision conflict: expected {revision}, current {episode.revision}"
            )
        if title is not None:
            episode.title = title.strip() or episode.title
        if source_text is not None:
            episode.source_text = source_text
            episode.source_end = len(source_text)
        if script_text is not None:
            episode.save_script(script_text)
        else:
            episode.revision += 1
        return asdict(self.repository.save_episode(episode, expected_revision=revision))

    def reorder(self, project_id: str, episode_ids: list[str]) -> list[dict[str, Any]]:
        if len(episode_ids) != len(set(episode_ids)):
            raise ValueError("episode_ids contains duplicates")
        self.repository.reorder_episodes(project_id, episode_ids)
        return self.list(project_id)

    def delete(self, project_id: str, episode_id: str) -> None:
        self.repository.delete_episode(project_id, episode_id)

