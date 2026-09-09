export const WORKFLOW_STEPS = [
  {
    id: 'preprocess',
    label: '预处理',
    view: 'preprocess',
    states: ['initialized', 'document_split', 'script_converted'],
    isDone: (project) => Boolean(project?.has_segments || project?.has_scripts),
  },
  {
    id: 'resources',
    label: '资源',
    view: 'resources',
    states: ['entities_extracted', 'entities_bound'],
    isDone: (project) => Boolean(project?.has_entities || project?.has_bindings),
  },
  {
    id: 'video',
    label: '视频',
    view: 'video',
    states: ['prompts_generated', 'assets_confirmed', 'video_generating', 'video_completed'],
    isDone: (project) => Boolean(project?.has_prompts || project?.has_completed_video),
  },
];

const WORKFLOW_STATE_LABELS = {
  initialized: '已初始化',
  document_split: '已切分',
  script_converted: '剧本就绪',
  entities_extracted: '实体已提取',
  entities_bound: '实体已绑定',
  prompts_generated: '提示词已生成',
  assets_confirmed: '素材已确认',
  video_generating: '视频生成中',
  video_completed: '视频已完成',
};

export function workflowStateLabel(state) {
  return WORKFLOW_STATE_LABELS[state] || state || '未知';
}

export function workflowViewForState(state) {
  const step = WORKFLOW_STEPS.find((item) => item.states.includes(state));
  return step?.view || 'preprocess';
}

export function activeWorkflowStepIndex(project) {
  const state = project?.current_state;
  const index = WORKFLOW_STEPS.findIndex((item) => item.states.includes(state));
  if (index >= 0) return index;
  if (project?.has_completed_video) return WORKFLOW_STEPS.length - 1;
  if (project?.has_prompts) return 2;
  if (project?.has_entities) return 1;
  if (project?.has_segments || project?.has_scripts) return 0;
  return 0;
}

export function formatProjectDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function projectListMeta(project) {
  const parts = [workflowStateLabel(project?.current_state)];
  if (project?.has_segments) parts.push('已分集');
  if (project?.has_scripts) parts.push('有剧本');
  if (project?.has_entities) parts.push('有实体');
  if (project?.has_completed_video) parts.push('有成片');
  return parts.join(' · ');
}

export function filterProjectsBySearch(projects, query = '') {
  const normalized = String(query || '').trim().toLowerCase();
  if (!normalized) return projects;
  return projects.filter((project) => {
    const name = String(project.name || '').toLowerCase();
    const id = String(project.id || '').toLowerCase();
    return name.includes(normalized) || id.includes(normalized);
  });
}

export function sortProjects(projects, sortBy = 'updated') {
  const list = [...projects];
  if (sortBy === 'name') {
    return list.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'));
  }
  if (sortBy === 'created') {
    return list.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
  }
  return list.sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0));
}

export function recentProjects(projects, limit = 8) {
  return sortProjects(
    projects.filter((project) => !project.deleted_at),
    'updated',
  ).slice(0, limit);
}

export function projectDefaultSettings(workspace = {}) {
  return {
    expectedTotalDurationSeconds: workspace.expectedTotalDurationSeconds ?? null,
    defaultAspectRatio: workspace.defaultAspectRatio || '9:16',
    defaultVideoDuration: Number(workspace.defaultVideoDuration) || 5,
    defaultVideoModel: String(workspace.defaultVideoModel || '').trim(),
    defaultResolution: workspace.defaultResolution || '720p',
    projectStylePrompt: String(workspace.projectStylePrompt || '').trim(),
    outputRoot: String(workspace.outputRoot || '').trim(),
    sourceAssetsRoot: String(workspace.sourceAssetsRoot || '').trim(),
    dataRoot: String(workspace.dataRoot || '').trim(),
  };
}
