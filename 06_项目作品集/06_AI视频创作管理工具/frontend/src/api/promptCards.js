import { request, LLM_REQUEST_TIMEOUT_MS } from './client';

export function createPromptCardVideoTask(promptCardId, body) {
  return request(`/api/prompt-cards/${encodeURIComponent(promptCardId)}/video-tasks`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function resolvePromptMentions(promptCardId, body) {
  return request(`/api/prompt-cards/${encodeURIComponent(promptCardId)}/resolve-mentions`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function matchPromptCardSubjects(promptCardId, body = {}) {
  return request(`/api/prompt-cards/${encodeURIComponent(promptCardId)}/match-subjects`, {
    method: 'POST',
    body: JSON.stringify(body),
    timeoutMs: LLM_REQUEST_TIMEOUT_MS,
  });
}
