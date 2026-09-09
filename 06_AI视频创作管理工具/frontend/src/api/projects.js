import { API_BASE, ApiError, request, uploadBinary } from './client';

function formatErrorBody(body, fallback) {
  if (!body || typeof body !== 'object') return fallback;
  const detail = body.detail || body.message || body.error;
  if (typeof detail === 'string') return detail;
  return fallback;
}

export async function fetchProjectDataRoot(projectId) {
  return request(`/api/projects/${projectId}/data-root`);
}

export async function syncProjectBundle(projectId) {
  return request(`/api/projects/${projectId}/sync-bundle`, { method: 'POST', body: '{}' });
}

export async function exportProjectBundle(projectId) {
  let response;
  try {
    response = await fetch(`${API_BASE}/api/projects/${projectId}/export`, {
      credentials: 'include',
    });
  } catch (error) {
    throw new ApiError('无法连接后端服务', {
      status: 0,
      statusText: 'Network Error',
      body: { detail: error?.message || 'Failed to fetch' },
    });
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(formatErrorBody(body, response.statusText || '导出失败'), {
      status: response.status,
      statusText: response.statusText,
      body,
    });
  }
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || `project-${projectId}.zip`;
  return { blob, filename };
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function importProjectZip(file, { name } = {}) {
  const formData = new FormData();
  formData.append('file', file);
  const query = name ? `?name=${encodeURIComponent(name)}` : '';
  return uploadBinary(`/api/projects/import${query}`, formData);
}

export async function importProjectFolder(path, { name } = {}) {
  return request('/api/projects/import-folder', {
    method: 'POST',
    body: JSON.stringify({ path, name: name || null }),
  });
}
