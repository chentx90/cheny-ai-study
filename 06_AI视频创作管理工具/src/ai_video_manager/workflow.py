from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import Checkpoint, Project, WorkflowState


class WorkflowError(RuntimeError):
    pass


class CheckpointManager:
    checkpoint_states = {
        WorkflowState.DOCUMENT_SPLIT,
        WorkflowState.SCRIPT_CONVERTED,
        WorkflowState.ENTITIES_BOUND,
    }

    def __init__(self, store: Any | None = None) -> None:
        self.store = store
        self._checkpoints: dict[str, list[Checkpoint]] = {}

    def save_checkpoint(self, project: Project, state: WorkflowState) -> Checkpoint:
        checkpoint = Checkpoint(project_id=project.id, state=state, data=asdict(project))
        if self.store is not None:
            self.store.save_checkpoint(checkpoint)
        else:
            self._checkpoints.setdefault(project.id, []).append(checkpoint)
        return checkpoint

    def list_checkpoints(self, project_id: str) -> list[Checkpoint]:
        if self.store is not None:
            return self.store.list_checkpoints(project_id)
        return list(self._checkpoints.get(project_id, []))

    def latest(self, project_id: str, state: WorkflowState | None = None) -> Checkpoint | None:
        if self.store is not None:
            return self.store.latest_checkpoint(project_id, state)
        checkpoints = self._checkpoints.get(project_id, [])
        if state:
            checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint.state == state]
        return checkpoints[-1] if checkpoints else None


class WorkflowEngine:
    transitions = {
        WorkflowState.INITIALIZED: WorkflowState.DOCUMENT_SPLIT,
        WorkflowState.DOCUMENT_SPLIT: WorkflowState.SCRIPT_CONVERTED,
        WorkflowState.SCRIPT_CONVERTED: WorkflowState.ENTITIES_EXTRACTED,
        WorkflowState.ENTITIES_EXTRACTED: WorkflowState.ENTITIES_BOUND,
        WorkflowState.ENTITIES_BOUND: WorkflowState.PROMPTS_GENERATED,
        WorkflowState.PROMPTS_GENERATED: WorkflowState.ASSETS_CONFIRMED,
        WorkflowState.ASSETS_CONFIRMED: WorkflowState.VIDEO_GENERATING,
        WorkflowState.VIDEO_GENERATING: WorkflowState.VIDEO_COMPLETED,
    }

    prerequisites = {
        WorkflowState.DOCUMENT_SPLIT: ("has_document",),
        WorkflowState.SCRIPT_CONVERTED: ("has_segments",),
        WorkflowState.ENTITIES_EXTRACTED: ("has_scripts",),
        WorkflowState.ENTITIES_BOUND: ("has_entities",),
        WorkflowState.PROMPTS_GENERATED: ("has_bindings",),
        WorkflowState.ASSETS_CONFIRMED: ("has_prompts",),
        WorkflowState.VIDEO_GENERATING: ("has_prompts", "assets_confirmed"),
        WorkflowState.VIDEO_COMPLETED: ("has_completed_video",),
    }

    def __init__(self, project: Project, checkpoint_manager: CheckpointManager | None = None) -> None:
        self.project = project
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()

    @property
    def state(self) -> WorkflowState:
        return self.project.current_state

    def advance(self) -> WorkflowState:
        target = self.transitions.get(self.project.current_state)
        if target is None:
            raise WorkflowError(f"Project is already at final state: {self.project.current_state}")
        return self.jump_to(target)

    def jump_to(self, target: WorkflowState) -> WorkflowState:
        if not self.can_jump_to(target):
            missing = self.missing_prerequisites(target)
            raise WorkflowError(f"Cannot jump to {target}; missing prerequisites: {', '.join(missing)}")
        self.project.current_state = target
        if target in CheckpointManager.checkpoint_states:
            self.checkpoint_manager.save_checkpoint(self.project, target)
        return target

    def can_jump_to(self, target: WorkflowState) -> bool:
        return not self.missing_prerequisites(target)

    def missing_prerequisites(self, target: WorkflowState) -> list[str]:
        return [name for name in self.prerequisites.get(target, ()) if not getattr(self.project, name)]
