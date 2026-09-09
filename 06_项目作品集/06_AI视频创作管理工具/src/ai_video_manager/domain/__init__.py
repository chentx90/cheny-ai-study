"""V2 domain contracts.

The legacy ``ai_video_manager.models`` module remains available during the
additive migration. New application code should import production concepts
from this package.
"""

from .production import (
    AIRunStatus,
    AIRunUseCase,
    Episode,
    EpisodeStatus,
    MatchSource,
    PromptCardEntityLink,
    VideoOutput,
)

__all__ = [
    "AIRunStatus",
    "AIRunUseCase",
    "Episode",
    "EpisodeStatus",
    "MatchSource",
    "PromptCardEntityLink",
    "VideoOutput",
]
