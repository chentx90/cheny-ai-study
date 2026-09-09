import { request } from './client';

export async function listEpisodes(projectId) {
  const data = await request(`/api/v2/projects/${projectId}/episodes`);
  return Array.isArray(data.episodes) ? data.episodes : [];
}

export function episodesToWorkspaceFields(episodes) {
  const ordered = [...(episodes || [])].sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
  const segments = ordered.map((episode) => ({
    id: episode.id,
    order: Number(episode.order || 0),
    title: episode.title || `第${episode.order}集`,
    content: episode.source_text || '',
    document_id: episode.document_id || '',
  }));
  const scripts = {};
  const scriptValidation = {};
  ordered.forEach((episode) => {
    const validation = episode.script_validation || {};
    if (String(episode.script_text || '').trim() || Object.keys(validation).length) {
      scripts[episode.id] = episode.script_text || '';
      scriptValidation[episode.id] = validation;
    }
  });
  return { segments, scripts, scriptValidation };
}
