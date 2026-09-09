import { baseContentFontSize } from '../../themeUtils';
import { defaultVideoRequestSettings } from '../../constants';
import { readStorageJson, writeStorageJson } from '../../app/uiStorage';

export const defaultEpisodeTitle = (segment, index = 0) => segment?.title || `第${segment?.order || index + 1}集`;

export function compactText(text = '', length = 110) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  return value.length > length ? `${value.slice(0, length)}...` : value;
}

export function uniqueAssetCount(card) {
  return new Set([...(card.assets || []), ...(card.reference_images || []), ...(card.audio_samples || []), ...(card.video_clips || [])]).size;
}

export function cardAssetPaths(card) {
  return Array.from(
    new Set([...(card.assets || []), ...(card.reference_images || []), ...(card.audio_samples || []), ...(card.video_clips || [])]),
  ).filter(Boolean);
}

export function formatSeconds(value) {
  const number = Number(value || 0);
  return number > 0 ? `${Math.round(number * 10) / 10}s` : '未估算';
}

export function sourceRangeLabel(card) {
  const start = Number(card.source_start || 0);
  const end = Number(card.source_end || 0);
  return end > start ? `原文 ${start + 1}-${end}` : '来源未定位';
}

export function segmentOrder(card, index = 0) {
  return Number(card?.order || index + 1);
}

export function segmentPrefix(order) {
  return `片段${order}`;
}

export function splitSegmentTitle(title = '', order = 1) {
  const prefix = segmentPrefix(order);
  const normalized = String(title || '').trim();
  if (!normalized) return { prefix, body: '' };
  if (normalized.startsWith(`${prefix} `)) {
    return { prefix, body: normalized.slice(prefix.length + 1).trim() };
  }
  if (normalized.startsWith(prefix)) {
    return { prefix, body: normalized.slice(prefix.length).trim() };
  }
  return { prefix, body: normalized };
}

export function composeSegmentTitle(order, body = '') {
  const prefix = segmentPrefix(order);
  const trimmed = String(body || '').trim();
  if (!trimmed || trimmed === prefix) return prefix;
  if (trimmed.startsWith(`${prefix} `) || trimmed.startsWith(prefix)) return trimmed;
  return `${prefix} ${trimmed}`;
}

export function displaySegmentTitleBody(title = '', order = 1) {
  const { body } = splitSegmentTitle(title, order);
  const trimmed = String(body || '').trim();
  if (!trimmed) return '';
  if (/^提示词卡片\s*\d*$/.test(trimmed)) return '';
  return trimmed;
}

export function draftKey(items) {
  return items.map((item) => `${item.id}:${item.updated_at || ''}`).join('|');
}

export function entityCardIdsFromAnchorText(anchorText = '') {
  return Array.from(new Set(String(anchorText || '').match(/\bcard_[0-9a-fA-F]{12}\b/g) || []));
}

export function selectEntityCards({ entityCards = [], promptCards = [] }) {
  const selectedIds = new Set(promptCards.flatMap((card) => entityCardIdsFromAnchorText(card.anchor_text)));
  return entityCards
    .filter((card) => selectedIds.has(card.id))
    .sort((a, b) => String(a.type || '').localeCompare(String(b.type || '')) || String(a.entity_name || '').localeCompare(String(b.entity_name || '')));
}

export function entityCardsForAnchorText(anchorText = '', entityCards = []) {
  const selectedIds = entityCardIdsFromAnchorText(anchorText);
  const byId = new Map(entityCards.map((card) => [card.id, card]));
  return selectedIds.map((id) => byId.get(id)).filter(Boolean);
}

export function selectSegmentVideoTasks({ activeSegment, promptCards = [], videoTasks = [] }) {
  const cardIds = new Set(promptCards.map((card) => card.id));
  const activeId = activeSegment?.id;
  const activeOrder = String(activeSegment?.order || '');

  const matched = videoTasks.filter((task) => {
    if (task.segment_id === activeId || String(task.segmentOrder || '') === activeOrder) return true;
    if (task.prompt_card_id && cardIds.has(task.prompt_card_id)) return true;
    return false;
  });

  // Keep orphaned history visible even when segment ids changed after resplit.
  const orphaned = videoTasks.filter((task) => task.orphaned && !matched.some((item) => item.id === task.id));
  return [...matched, ...orphaned];
}

export const VIDEO_UI_STORAGE_KEY = 'ai-video-manager:video-ui';
export const DEFAULT_PROMPT_CONTENT_FONT_SIZE = 14;
export const MIN_PROMPT_CONTENT_FONT_SIZE = 12;
export const MAX_PROMPT_CONTENT_FONT_SIZE = 22;

export function clampPromptContentFontSize(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return DEFAULT_PROMPT_CONTENT_FONT_SIZE;
  return Math.min(MAX_PROMPT_CONTENT_FONT_SIZE, Math.max(MIN_PROMPT_CONTENT_FONT_SIZE, Math.round(number)));
}

export const clampScriptFontSize = clampPromptContentFontSize;

export function readVideoUiPrefs(fontScale = 'm') {
  const baseFont = baseContentFontSize(fontScale);
  const raw = readStorageJson(VIDEO_UI_STORAGE_KEY, {});
  return {
    promptContentFontSize: clampPromptContentFontSize(raw.promptContentFontSize ?? baseFont),
    scriptFontSize: clampPromptContentFontSize(raw.scriptFontSize ?? baseFont),
    promptCardHeights:
      raw.promptCardHeights && typeof raw.promptCardHeights === 'object' ? raw.promptCardHeights : {},
  };
}

export function writeVideoUiPrefs(prefs) {
  writeStorageJson(VIDEO_UI_STORAGE_KEY, {
    promptContentFontSize: clampPromptContentFontSize(prefs.promptContentFontSize),
    scriptFontSize: clampPromptContentFontSize(prefs.scriptFontSize),
    promptCardHeights: prefs.promptCardHeights || {},
  });
}

/** Bottom-right hit zone (px) for custom prompt-card height drag; native CSS resize is disabled. */
export const PROMPT_CARD_RESIZE_HANDLE_PX = 20;

/** True when pointer is in the bottom-right resize zone of a prompt card. */
export function isPromptCardResizePointer(clientX, clientY, cardRect) {
  return (
    clientX >= cardRect.right - PROMPT_CARD_RESIZE_HANDLE_PX &&
    clientY >= cardRect.bottom - PROMPT_CARD_RESIZE_HANDLE_PX
  );
}

/** Default card height from viewport (~80% minus chrome) when user has not resized. */
export function defaultPromptCardHeight(viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 800) {
  const chrome = 132;
  return Math.max(320, Math.round(Number(viewportHeight) * 0.8 - chrome));
}

/** Clamp persisted drag height to 280px … ~92vh; invalid input yields null (use CSS default). */
export function clampPromptCardHeight(height, viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 800) {
  const number = Number(height);
  if (!Number.isFinite(number) || number <= 0) return null;
  const max = Math.round(Number(viewportHeight) * 0.92 - 72);
  return Math.min(max, Math.max(280, Math.round(number)));
}

export function normalizeVideoProvider(provider) {
  const value = String(provider || 'unconfigured').trim().toLowerCase();
  return !value || value === 'mock' ? 'unconfigured' : value;
}

export function videoRuntimeInfo(apiConfig = {}) {
  const ready = apiConfig.videoRuntimeMode === 'real';
  const provider = normalizeVideoProvider(apiConfig.videoRuntimeProvider || apiConfig.videoProvider);
  return {
    ready,
    provider,
    pill: ready ? `已接入 · ${provider}` : '未配置 · 请先在设置中填写视频服务',
  };
}

export function buildGeneratedUrl(apiBase, selectedProject, resultPath) {
  if (!selectedProject?.id || !resultPath) return '';
  const normalized = String(resultPath).replace(/\\/g, '/');
  let relative = '';
  const marker = `/projects/${selectedProject.id}/generated/`;
  const idx = normalized.indexOf(marker);
  if (idx >= 0) {
    relative = normalized.slice(idx + marker.length);
  } else if (normalized.includes('/generated/')) {
    relative = normalized.split('/generated/').pop() || '';
  } else {
    // 绝对路径但只有文件名时，无法拼出目录，交给 task download
    return '';
  }
  if (!relative) return '';
  const encoded = relative
    .split('/')
    .filter(Boolean)
    .map(encodeURIComponent)
    .join('/');
  return `${apiBase || ''}/api/projects/${encodeURIComponent(selectedProject.id)}/generated/${encoded}`;
}

export function buildTaskDownloadUrl(apiBase, task, { inline = false } = {}) {
  if (!task?.id) return '';
  const qs = inline ? '?inline=1' : '';
  return `${apiBase || ''}/api/videos/tasks/${encodeURIComponent(task.id)}/download${qs}`;
}

export function taskStatusHint(task) {
  if (!task) return '';
  const updatedAt = task.updated_at || task.updatedAt || task.created_at || task.createdAt;
  const age = updatedAt ? formatRelativeTime(updatedAt) : '';
  if (task.status === 'processing') {
    if (task.error_message?.includes('正在下载')) return `${task.error_message}${age ? ` · ${age}` : ''}`;
    if (!task.api_task_id) return `提交未完成（未拿到远端任务 ID）${age ? ` · ${age}` : ''}`;
    return `远端生成中${age ? ` · 更新 ${age}` : ''}`;
  }
  if (task.status === 'failed' && task.error_message) return task.error_message;
  if (task.status === 'completed' && task.result_path) return `成片已就绪${age ? ` · ${age}` : ''}`;
  return age ? `更新 ${age}` : '';
}

function formatRelativeTime(iso) {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return '';
  const deltaSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (deltaSec < 60) return '刚刚';
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)} 分钟前`;
  if (deltaSec < 86400) return `${Math.floor(deltaSec / 3600)} 小时前`;
  return `${Math.floor(deltaSec / 86400)} 天前`;
}

export function displayResultFilename(resultPath) {
  const normalized = String(resultPath || '').replace(/\\/g, '/');
  const parts = normalized.split('/').filter(Boolean);
  return parts[parts.length - 1] || normalized;
}

export function taskSettingSummary(task) {
  const settings = task?.assets?.settings && typeof task.assets.settings === 'object' ? task.assets.settings : {};
  const duration = settings.duration || task?.duration;
  return [
    settings.model || '服务默认',
    settings.aspect_ratio || settings.aspectRatio || '未设比例',
    duration ? `${duration}秒` : '',
    settings.resolution || '未设分辨率',
  ]
    .filter(Boolean)
    .join(' / ');
}

/** Map a persisted video task back into VideoRequestDialog form defaults. */
export function taskVideoRequestSettings(task) {
  const assets = task?.assets && typeof task.assets === 'object' ? task.assets : {};
  const settings = assets.settings && typeof assets.settings === 'object' ? assets.settings : {};
  const list = (value) => (Array.isArray(value) ? value.map(String).filter(Boolean) : []);
  return {
    model: String(settings.model || ''),
    aspectRatio: String(settings.aspect_ratio || settings.aspectRatio || defaultVideoRequestSettings.aspectRatio),
    duration: Number(settings.duration || task?.duration || defaultVideoRequestSettings.duration),
    resolution: String(settings.resolution || defaultVideoRequestSettings.resolution),
    referenceMode: String(assets.reference_mode || defaultVideoRequestSettings.referenceMode),
    generateAudio:
      settings.generate_audio === undefined && settings.generateAudio === undefined
        ? Boolean(defaultVideoRequestSettings.generateAudio)
        : Boolean(settings.generate_audio ?? settings.generateAudio),
    firstFrame: String(assets.first_frame || ''),
    lastFrame: String(assets.last_frame || ''),
    referenceImages: list(assets.reference_images),
    referenceVideos: list(assets.reference_videos?.length ? assets.reference_videos : assets.video_clips),
    referenceAudios: list(assets.reference_audios?.length ? assets.reference_audios : assets.audio_samples),
  };
}

export function providerDisplayLabel(provider) {
  const value = normalizeVideoProvider(provider);
  if (value === 'unconfigured') return '未配置';
  return value;
}
