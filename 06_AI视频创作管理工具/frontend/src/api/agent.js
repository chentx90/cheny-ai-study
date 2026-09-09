import { LLM_REQUEST_TIMEOUT_MS, request } from './client';

export function createAgentThread(projectId) {
  return request('/api/agent/threads', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  });
}

export function listAgentThreads(projectId) {
  return request(`/api/agent/threads?project_id=${encodeURIComponent(projectId)}`);
}

export function createAgentBranch(threadId, data = {}) {
  return request(`/api/agent/threads/${encodeURIComponent(threadId)}/branches`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getAgentThread(threadId) {
  return request(`/api/agent/threads/${encodeURIComponent(threadId)}`);
}

export function sendAgentMessage(threadId, content, uiContext, approvalMode = 'manual') {
  return request(`/api/agent/threads/${encodeURIComponent(threadId)}/messages`, {
    method: 'POST',
    timeoutMs: LLM_REQUEST_TIMEOUT_MS,
    body: JSON.stringify({ content, ui_context: uiContext, approval_mode: approvalMode }),
  });
}

export function approveAgentRun(runId) {
  return request(`/api/agent/runs/${encodeURIComponent(runId)}/approve`, {
    method: 'POST',
    timeoutMs: LLM_REQUEST_TIMEOUT_MS,
  });
}

export function cancelAgentRun(runId) {
  return request(`/api/agent/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' });
}
