import { request } from './client';

export async function fetchWorkspace(projectId) {
  const data = await request(`/api/projects/${projectId}/session`);
  return data.data || {};
}

export async function saveDocument(projectId, payload) {
  const data = await request(`/api/projects/${projectId}/document`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return data.data;
}

export async function replaceSegments(projectId, payload) {
  const data = await request(`/api/projects/${projectId}/segments`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return data.data;
}

export async function saveSegmentScript(projectId, segmentId, payload) {
  const data = await request(`/api/projects/${projectId}/segments/${segmentId}/script`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return data.data;
}

export async function replaceScripts(projectId, payload) {
  const data = await request(`/api/projects/${projectId}/scripts`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return data.data;
}

export async function saveProjectSettings(projectId, payload) {
  const data = await request(`/api/projects/${projectId}/settings`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  return data.data;
}

export async function confirmAssets(projectId, confirmed = true) {
  const data = await request(`/api/projects/${projectId}/assets/confirm`, {
    method: 'POST',
    body: JSON.stringify({ confirmed }),
  });
  return data.data;
}

export async function refreshSourceAssets(projectId) {
  const data = await request(`/api/projects/${projectId}/assets/refresh-source`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
  return data.data;
}

export async function fetchWorkflowUi(projectId) {
  return request(`/api/projects/${projectId}/workflow/ui`);
}

export async function fetchVideoProviderCatalog(provider) {
  return request(`/api/video/providers/${encodeURIComponent(provider || 'newapi')}/catalog`);
}
