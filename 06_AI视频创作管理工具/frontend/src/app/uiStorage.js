import { navItems, promptCategories } from '../constants';

export const appUiStorageKey = 'ai-video-manager:ui-state';
export const selectedProjectStorageKey = 'ai-video-manager:selected-project-id';
export const workspaceDraftStoragePrefix = 'ai-video-manager:workspace-draft:';

export const defaultEpisodeTitle = (order) => `第${order}集`;
export const defaultEpisodeTitlePattern = /^第\d+集$/;

export const defaultUiState = {
  selectedProjectId: '',
  view: 'projects',
  projectFilter: 'all',
  selectedTemplateId: '',
  promptCategory: 'script_convert',
  sidebarCollapsed: false,
  projectListLayout: 'list',
  projectSortBy: 'updated',
};

const validProjectListLayouts = new Set(['list', 'cards']);
const validProjectSortBy = new Set(['updated', 'created', 'name']);
export const validViewIds = new Set([...navItems.map((item) => item.id), 'settings']);
const validProjectFilters = new Set(['all', 'active', 'draft', 'archive', 'trash']);
const validPromptCategories = new Set(promptCategories.map((item) => item.id));

export function readStorageJson(key, fallback) {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (_error) {
    return fallback;
  }
}

export function writeStorageJson(key, value) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (_error) {
    // localStorage may be unavailable in restrictive browser modes.
  }
}

export function readStorageText(key, fallback = '') {
  if (typeof window === 'undefined') return fallback;
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch (_error) {
    return fallback;
  }
}

export function writeStorageText(key, value) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, String(value));
  } catch (_error) {
    // localStorage may be unavailable in restrictive browser modes.
  }
}

export function removeStorageItem(key) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(key);
  } catch (_error) {
    // Ignore storage cleanup failures.
  }
}

export function sanitizeUiState(value) {
  const source = value && typeof value === 'object' ? value : {};
  const rawView = typeof source.view === 'string' ? source.view : defaultUiState.view;
  const view = rawView === 'storyboard' ? 'video' : validViewIds.has(rawView) ? rawView : defaultUiState.view;
  return {
    selectedProjectId: typeof source.selectedProjectId === 'string' ? source.selectedProjectId : '',
    view,
    projectFilter: validProjectFilters.has(source.projectFilter) ? source.projectFilter : defaultUiState.projectFilter,
    selectedTemplateId: typeof source.selectedTemplateId === 'string' ? source.selectedTemplateId : '',
    promptCategory: validPromptCategories.has(source.promptCategory)
      ? source.promptCategory
      : defaultUiState.promptCategory,
    sidebarCollapsed: Boolean(source.sidebarCollapsed),
    projectListLayout: validProjectListLayouts.has(source.projectListLayout)
      ? source.projectListLayout
      : defaultUiState.projectListLayout,
    projectSortBy: validProjectSortBy.has(source.projectSortBy) ? source.projectSortBy : defaultUiState.projectSortBy,
    projectLastViews:
      source.projectLastViews && typeof source.projectLastViews === 'object' ? source.projectLastViews : {},
  };
}

export function readStoredUiState() {
  const state = sanitizeUiState(readStorageJson(appUiStorageKey, defaultUiState));
  if (!state.selectedProjectId && typeof window !== 'undefined') {
    try {
      state.selectedProjectId = readStorageText(selectedProjectStorageKey);
    } catch (_error) {
      state.selectedProjectId = '';
    }
  }
  return state;
}

export function storeUiState(patch) {
  const next = sanitizeUiState({ ...readStoredUiState(), ...(patch || {}) });
  writeStorageJson(appUiStorageKey, next);
  if (typeof window !== 'undefined') {
    try {
      if (next.selectedProjectId) writeStorageText(selectedProjectStorageKey, next.selectedProjectId);
      else window.localStorage.removeItem(selectedProjectStorageKey);
    } catch (_error) {
      // consolidated ui-state key remains primary.
    }
  }
}

export function workspaceDraftKey(projectId) {
  return `${workspaceDraftStoragePrefix}${projectId}`;
}

export function encodeAssetPath(assetPath) {
  return String(assetPath || '')
    .split('/')
    .map((part) => encodeURIComponent(part))
    .join('/');
}

export function readWorkspaceDraft(projectId) {
  const draft = readStorageJson(workspaceDraftKey(projectId), null);
  if (!draft || draft.projectId !== projectId || !draft.data || typeof draft.data !== 'object') return null;
  return draft;
}

export function writeWorkspaceDraft(record) {
  if (!record?.projectId) return;
  writeStorageJson(workspaceDraftKey(record.projectId), {
    projectId: record.projectId,
    updatedAt: new Date().toISOString(),
    data: record.data,
  });
}

export function clearWorkspaceDraft(projectId) {
  if (projectId) removeStorageItem(workspaceDraftKey(projectId));
}

export function normalizeEpisodeSegments(segments = []) {
  return segments.map((segment, index) => {
    const order = index + 1;
    const title =
      !segment.title || defaultEpisodeTitlePattern.test(segment.title) ? defaultEpisodeTitle(order) : segment.title;
    return { ...segment, order, title };
  });
}

export function promptContextValue(value, fallback) {
  if (value === null || value === undefined || value === '') return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : String(value);
}
