import { useCallback, useEffect, useRef, useState } from 'react';

import { acquireSegmentLock, fetchSegmentLocks, releaseSegmentLock } from '../api/segmentLocks';
import { isTransientNetworkError } from '../api/client';

const HEARTBEAT_MS = 2 * 60 * 1000;
const POLL_MS = 20 * 1000;

export function useSegmentLocks({ selectedProject, activeSegment, user, canWriteProject, notify }) {
  const [locks, setLocks] = useState([]);
  const [segmentLockError, setSegmentLockError] = useState('');
  const heldSegmentIdRef = useRef('');
  const locksRef = useRef([]);
  const userIdRef = useRef(user?.id || '');
  const projectId = selectedProject?.id || '';

  useEffect(() => {
    locksRef.current = locks;
  }, [locks]);

  useEffect(() => {
    userIdRef.current = user?.id || '';
  }, [user?.id]);

  const refreshLocks = useCallback(async () => {
    if (!projectId) {
      setLocks([]);
      locksRef.current = [];
      return [];
    }
    const data = await fetchSegmentLocks(projectId);
    const nextLocks = data.locks || [];
    locksRef.current = nextLocks;
    setLocks(nextLocks);
    return nextLocks;
  }, [projectId]);

  const releaseHeldLock = useCallback(
    async (segmentId = heldSegmentIdRef.current) => {
      if (!projectId || !segmentId) return;
      try {
        await releaseSegmentLock(projectId, segmentId);
      } catch (_error) {
        // best-effort
      }
      if (heldSegmentIdRef.current === segmentId) {
        heldSegmentIdRef.current = '';
      }
    },
    [projectId],
  );

  const tryAcquire = useCallback(
    async (segmentId) => {
      if (!projectId || !segmentId || !canWriteProject) return false;
      try {
        await acquireSegmentLock(projectId, segmentId);
        heldSegmentIdRef.current = segmentId;
        setSegmentLockError('');
        await refreshLocks();
        return true;
      } catch (error) {
        setSegmentLockError(error.message || '无法占用该分集编辑锁');
        if (!isTransientNetworkError(error)) {
          notify?.(error.message || '该分集已被他人占用', 'error');
        }
        return false;
      }
    },
    [canWriteProject, notify, projectId, refreshLocks],
  );

  const lockForSegment = useCallback(
    (segmentId) => locks.find((item) => item.segment_id === segmentId) || null,
    [locks],
  );

  const isLockedByOther = useCallback(
    (segmentId) => {
      const lock = lockForSegment(segmentId);
      return Boolean(lock && lock.user_id && lock.user_id !== user?.id);
    },
    [lockForSegment, user?.id],
  );

  const canEditSegment = useCallback(
    (segmentId) => {
      if (!canWriteProject) return false;
      return !isLockedByOther(segmentId);
    },
    [canWriteProject, isLockedByOther],
  );

  const selectSegment = useCallback(
    async (segment, onApplied) => {
      if (!segment?.id) return;
      if (!canWriteProject) {
        onApplied?.(segment.id);
        return;
      }
      if (heldSegmentIdRef.current && heldSegmentIdRef.current !== segment.id) {
        await releaseHeldLock(heldSegmentIdRef.current);
      }
      const acquired = await tryAcquire(segment.id);
      if (!acquired && isLockedByOther(segment.id)) {
        onApplied?.(segment.id);
        return;
      }
      onApplied?.(segment.id);
    },
    [canWriteProject, isLockedByOther, releaseHeldLock, tryAcquire],
  );

  useEffect(() => {
    refreshLocks().catch(() => {});
    if (!projectId) return undefined;
    const timer = window.setInterval(() => {
      refreshLocks().catch(() => {});
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [projectId, refreshLocks]);

  // Acquire + heartbeat only when project/segment/writeability changes.
  // Do NOT depend on locks / isLockedByOther / tryAcquire — that caused a
  // refresh→reacquire loop that flooded the API and froze the UI.
  useEffect(() => {
    if (!projectId || !activeSegment?.id || !canWriteProject) return undefined;
    const segmentId = activeSegment.id;
    let cancelled = false;

    const lock = locksRef.current.find((item) => item.segment_id === segmentId);
    const heldByOther = Boolean(lock && lock.user_id && lock.user_id !== userIdRef.current);
    if (heldByOther) return undefined;

    (async () => {
      try {
        await acquireSegmentLock(projectId, segmentId);
        if (cancelled) return;
        heldSegmentIdRef.current = segmentId;
        setSegmentLockError('');
        refreshLocks().catch(() => {});
      } catch (error) {
        if (cancelled) return;
        setSegmentLockError(error.message || '无法占用该分集编辑锁');
      }
    })();

    const timer = window.setInterval(() => {
      if (heldSegmentIdRef.current === segmentId) {
        acquireSegmentLock(projectId, segmentId).catch(() => {});
      }
    }, HEARTBEAT_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSegment?.id, canWriteProject, projectId, refreshLocks]);

  useEffect(() => {
    return () => {
      releaseHeldLock().catch(() => {});
    };
  }, [projectId, releaseHeldLock]);

  useEffect(() => {
    if (!projectId) {
      heldSegmentIdRef.current = '';
      setSegmentLockError('');
    }
  }, [projectId]);

  return {
    locks,
    segmentLockError,
    lockForSegment,
    isLockedByOther,
    canEditSegment,
    selectSegment,
    refreshLocks,
    releaseHeldLock,
  };
}
