import { request } from './client';

export function listVideoTasks(projectId, { sync = false, segmentId = '' } = {}) {
  const query = new URLSearchParams({ project_id: projectId });
  if (sync) query.set('sync', '1');
  if (segmentId) query.set('segment_id', segmentId);
  return request(`/api/videos/tasks?${query.toString()}`);
}

export function retryVideoTask(taskId, body) {
  return request(`/api/videos/tasks/${encodeURIComponent(taskId)}/retry`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function recoverVideoTask(taskId, apiTaskId) {
  return request(`/api/videos/tasks/${encodeURIComponent(taskId)}/recover`, {
    method: 'POST',
    body: JSON.stringify({ api_task_id: apiTaskId }),
  });
}

export function deleteVideoTask(taskId) {
  return request(`/api/videos/tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  });
}

export function listVideoOutputs(projectId, { promptCardId = '' } = {}) {
  const query = new URLSearchParams();
  if (promptCardId) query.set('prompt_card_id', promptCardId);
  const suffix = query.size ? `?${query.toString()}` : '';
  return request(`/api/v2/projects/${encodeURIComponent(projectId)}/video-outputs${suffix}`);
}

export function adoptVideoOutput(projectId, outputId) {
  return request(
    `/api/v2/projects/${encodeURIComponent(projectId)}/video-outputs/${encodeURIComponent(outputId)}/adopt`,
    { method: 'POST' },
  );
}

export function videoTaskDownloadUrl(apiBase, taskId, { inline = false } = {}) {
  const qs = inline ? '?inline=1' : '';
  return `${apiBase || ''}/api/videos/tasks/${encodeURIComponent(taskId)}/download${qs}`;
}
