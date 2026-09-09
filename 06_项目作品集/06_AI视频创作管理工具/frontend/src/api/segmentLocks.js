import { request } from './client';

export async function fetchSegmentLocks(projectId) {
  return request(`/api/projects/${encodeURIComponent(projectId)}/segment-locks`);
}

export async function acquireSegmentLock(projectId, segmentId) {
  return request(`/api/projects/${encodeURIComponent(projectId)}/segments/${encodeURIComponent(segmentId)}/lock`, {
    method: 'POST',
  });
}

export async function releaseSegmentLock(projectId, segmentId, { force = false } = {}) {
  const query = force ? '?force=true' : '';
  return request(
    `/api/projects/${encodeURIComponent(projectId)}/segments/${encodeURIComponent(segmentId)}/lock${query}`,
    { method: 'DELETE' },
  );
}
