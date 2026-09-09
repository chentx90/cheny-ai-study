import { request } from './client';

export async function fetchSetupStatus() {
  return request('/api/auth/setup-status');
}

export async function fetchMe(projectId = '') {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return request(`/api/auth/me${query}`);
}

export async function fetchProjectMembers(projectId) {
  return request(`/api/projects/${encodeURIComponent(projectId)}/members`);
}

export async function fetchProjectMemberCandidates(projectId) {
  return request(`/api/projects/${encodeURIComponent(projectId)}/members/candidates`);
}

export async function upsertProjectMember(projectId, payload) {
  return request(`/api/projects/${encodeURIComponent(projectId)}/members`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function removeProjectMember(projectId, userId) {
  return request(`/api/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
}

export async function updateProjectVisibility(projectId, visibility) {
  return request(`/api/projects/${encodeURIComponent(projectId)}/visibility`, {
    method: 'PATCH',
    body: JSON.stringify({ visibility }),
  });
}
