import { LLM_REQUEST_TIMEOUT_MS, request } from './client';

const base = (projectId) => `/api/v3/projects/${projectId}`;

export const assetProductionApi = {
  listProfiles: (projectId) => request(`${base(projectId)}/entity-profiles`),
  runAnalysis: (projectId, episodeIds = []) => request(`${base(projectId)}/entity-analysis-runs`, {
    method: 'POST', timeoutMs: LLM_REQUEST_TIMEOUT_MS, body: JSON.stringify({ episode_ids: episodeIds }),
  }),
  updateProfile: (projectId, profileId, patch) => request(`${base(projectId)}/entity-profiles/${profileId}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  }),
  deleteProfile: (projectId, profileId) => request(`${base(projectId)}/entity-profiles/${profileId}`, { method: 'DELETE' }),
  generateSetting: (projectId, profileId) => request(`${base(projectId)}/entity-profiles/${profileId}/setting`, {
    method: 'POST', timeoutMs: LLM_REQUEST_TIMEOUT_MS,
  }),
  createEntityCard: (projectId, profileId, variantId = null) => request(`${base(projectId)}/entity-profiles/${profileId}/entity-card`, {
    method: 'POST', body: JSON.stringify({ variant_id: variantId }),
  }),
  listStyles: (projectId) => request(`${base(projectId)}/visual-styles`),
  createStyle: (projectId, data) => request(`${base(projectId)}/visual-styles`, { method: 'POST', body: JSON.stringify(data) }),
  updateStyle: (projectId, styleId, data) => request(`${base(projectId)}/visual-styles/${styleId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteStyle: (projectId, styleId) => request(`${base(projectId)}/visual-styles/${styleId}`, { method: 'DELETE' }),
  listPresets: (projectId) => request(`${base(projectId)}/asset-presets`),
  savePreset: (projectId, type, data) => request(`${base(projectId)}/asset-presets/${type}`, { method: 'PUT', body: JSON.stringify(data) }),
  listPrompts: (projectId) => request(`${base(projectId)}/asset-prompts`),
  generatePrompt: (projectId, profileId, data = {}) => request(`${base(projectId)}/entity-profiles/${profileId}/asset-prompts`, {
    method: 'POST', timeoutMs: LLM_REQUEST_TIMEOUT_MS, body: JSON.stringify(data),
  }),
  updatePrompt: (projectId, promptId, data) => request(`${base(projectId)}/asset-prompts/${promptId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  listTasks: (projectId) => request(`${base(projectId)}/image-tasks`),
  generateImages: (projectId, promptId) => request(`${base(projectId)}/image-tasks`, {
    method: 'POST', timeoutMs: LLM_REQUEST_TIMEOUT_MS, body: JSON.stringify({ asset_prompt_id: promptId }),
  }),
  adoptOutput: (projectId, outputId) => request(`${base(projectId)}/image-outputs/${outputId}/adopt`, { method: 'POST' }),
};
