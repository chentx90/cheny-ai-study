from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ai_video_manager.models import SystemRole, User
from ai_video_manager.storage import SQLiteStore

LOCK_TTL_MINUTES = 30


class SegmentLockError(ValueError):
    def __init__(self, message: str, *, holder: dict | None = None) -> None:
        super().__init__(message)
        self.holder = holder or {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(expires_at: str) -> bool:
    try:
        return datetime.fromisoformat(expires_at) <= _now()
    except ValueError:
        return True


def list_active_locks(store: SQLiteStore, project_id: str) -> list[dict]:
    store.cleanup_expired_segment_locks(project_id)
    return store.list_segment_locks(project_id)


def get_active_lock(store: SQLiteStore, project_id: str, segment_id: str) -> dict | None:
    store.cleanup_expired_segment_locks(project_id)
    lock = store.get_segment_lock(project_id, segment_id)
    if lock is None or _is_expired(lock["expires_at"]):
        return None
    return lock


def acquire_lock(store: SQLiteStore, project_id: str, segment_id: str, user: User) -> dict:
    store.cleanup_expired_segment_locks(project_id)
    current = store.get_segment_lock(project_id, segment_id)
    expires_at = _now() + timedelta(minutes=LOCK_TTL_MINUTES)
    if current is None or _is_expired(current["expires_at"]):
        return store.upsert_segment_lock(
            project_id,
            segment_id,
            user_id=user.id,
            display_name=user.display_name or user.username,
            expires_at=expires_at,
        )
    if current["user_id"] == user.id:
        return store.upsert_segment_lock(
            project_id,
            segment_id,
            user_id=user.id,
            display_name=user.display_name or user.username,
            expires_at=expires_at,
        )
    raise SegmentLockError(
        f"该分集正由 {current.get('display_name') or current.get('user_id')} 编辑中",
        holder=current,
    )


def release_lock(
    store: SQLiteStore,
    project_id: str,
    segment_id: str,
    user: User,
    *,
    force: bool = False,
) -> bool:
    current = get_active_lock(store, project_id, segment_id)
    if current is None:
        return False
    if force and user.role == SystemRole.ADMIN:
        store.delete_segment_lock(project_id, segment_id)
        return True
    if current["user_id"] != user.id:
        raise SegmentLockError(
            f"该分集正由 {current.get('display_name') or current.get('user_id')} 编辑中",
            holder=current,
        )
    store.delete_segment_lock(project_id, segment_id)
    return True


def require_segment_writable(
    store: SQLiteStore,
    project_id: str,
    segment_id: str,
    user: User,
) -> None:
    lock = get_active_lock(store, project_id, segment_id)
    if lock is None:
        return
    if lock["user_id"] == user.id:
        return
    if user.role == SystemRole.ADMIN:
        return
    raise SegmentLockError(
        f"该分集正由 {lock.get('display_name') or lock.get('user_id')} 编辑中",
        holder=lock,
    )


def require_no_foreign_locks(store: SQLiteStore, project_id: str, user: User) -> None:
    for lock in list_active_locks(store, project_id):
        if lock["user_id"] != user.id and user.role != SystemRole.ADMIN:
            raise SegmentLockError(
                f"分集正由 {lock.get('display_name') or lock.get('user_id')} 编辑，暂不可执行全项目操作",
                holder=lock,
            )
