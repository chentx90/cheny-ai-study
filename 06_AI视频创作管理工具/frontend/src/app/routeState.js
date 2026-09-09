const PROJECT_VIEWS = new Set(['preprocess', 'resources', 'video', 'prompts']);

export function readRouteState(location = window.location) {
  const parts = location.pathname.split('/').filter(Boolean);
  if (parts[0] === 'settings') return { view: 'settings', projectId: '' };
  if (parts[0] !== 'projects') return { view: 'projects', projectId: '' };
  if (!parts[1]) return { view: 'projects', projectId: '' };
  const projectId = decodeURIComponent(parts[1]);
  const view = PROJECT_VIEWS.has(parts[2]) ? parts[2] : 'projects';
  return { view, projectId };
}

export function routeForState(view, projectId = '') {
  if (view === 'settings') return '/settings';
  if (view === 'projects' || !projectId) return '/projects';
  return `/projects/${encodeURIComponent(projectId)}/${PROJECT_VIEWS.has(view) ? view : 'preprocess'}`;
}

export function syncRouteState(view, projectId, { replace = true } = {}) {
  const next = routeForState(view, projectId);
  if (window.location.pathname === next) return;
  const method = replace ? 'replaceState' : 'pushState';
  window.history[method]({}, '', next);
}
