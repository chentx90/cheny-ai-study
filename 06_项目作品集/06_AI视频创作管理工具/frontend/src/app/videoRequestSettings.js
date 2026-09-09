import {
  defaultVideoRequestSettings,
  defaultXyqVideoRequestSettings,
  isXyqVideoProvider,
  videoDurationMaxSeconds,
  videoDurationMinSeconds,
  videoRequestSettingsStorageKey,
  videoRequestSettingsStoragePrefix,
  xyqVideoAspectRatioOptions,
  xyqVideoModelOptions,
  xyqVideoResolutionOptions,
} from '../constants';
import { readStorageJson, writeStorageJson } from './uiStorage';

export function clampVideoDuration(value, fallback = defaultVideoRequestSettings.duration) {
  const parsed = Number(value ?? fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(videoDurationMaxSeconds, Math.max(videoDurationMinSeconds, Math.round(parsed)));
}

export function videoSettingsProviderKey(provider = '') {
  return isXyqVideoProvider(provider) ? 'xyq' : 'newapi';
}

export function videoRequestSettingsKeyForProvider(provider = '') {
  return `${videoRequestSettingsStoragePrefix}${videoSettingsProviderKey(provider)}`;
}

export function defaultsForVideoProvider(provider = '') {
  return isXyqVideoProvider(provider) ? defaultXyqVideoRequestSettings : defaultVideoRequestSettings;
}

function isKnownXyqModel(model) {
  const clean = String(model || '').trim();
  if (!clean) return false;
  return xyqVideoModelOptions.some((item) => item.value && item.value !== '__custom__' && item.value === clean);
}

function pickAllowed(value, options, fallback) {
  const clean = String(value || '').trim();
  if (options.some((item) => item.value === clean)) return clean;
  return fallback;
}

export function sanitizeVideoRequestSettings(settings = {}, provider = '') {
  const defaults = defaultsForVideoProvider(provider);
  const isXyq = isXyqVideoProvider(provider);
  const duration = clampVideoDuration(settings.duration, defaults.duration);
  const referenceImages = Array.isArray(settings.referenceImages)
    ? settings.referenceImages
    : Array.isArray(settings.reference_images)
      ? settings.reference_images
      : [];
  const referenceVideos = Array.isArray(settings.referenceVideos)
    ? settings.referenceVideos
    : Array.isArray(settings.reference_videos)
      ? settings.reference_videos
      : [];
  const referenceAudios = Array.isArray(settings.referenceAudios)
    ? settings.referenceAudios
    : Array.isArray(settings.reference_audios)
      ? settings.reference_audios
      : [];

  let model = String(settings.model || defaults.model || '').trim();
  let customModel = String(settings.customModel || '');

  // 切换平台时丢弃另一侧的模型 ID，避免网关模型污染小云雀（或反之）
  if (isXyq && model && model !== '__custom__' && !isKnownXyqModel(model)) {
    model = defaults.model;
    customModel = '';
  }
  if (isXyq && !model) {
    model = defaults.model;
  }

  let aspectRatio = String(settings.aspectRatio || settings.aspect_ratio || defaults.aspectRatio);
  let resolution = String(settings.resolution || defaults.resolution);
  if (isXyq) {
    aspectRatio = pickAllowed(aspectRatio, xyqVideoAspectRatioOptions, defaults.aspectRatio);
    resolution = pickAllowed(resolution, xyqVideoResolutionOptions, defaults.resolution);
  }

  return {
    model,
    customModel,
    aspectRatio,
    duration,
    resolution,
    referenceMode: String(settings.referenceMode || settings.reference_mode || defaults.referenceMode || 'omni'),
    generateAudio:
      settings.generateAudio === undefined && settings.generate_audio === undefined
        ? Boolean(defaults.generateAudio)
        : Boolean(settings.generateAudio ?? settings.generate_audio),
    firstFrame: String(settings.firstFrame || settings.first_frame || ''),
    lastFrame: String(settings.lastFrame || settings.last_frame || ''),
    referenceImages: referenceImages.map(String).filter(Boolean),
    referenceVideos: referenceVideos.map(String).filter(Boolean),
    referenceAudios: referenceAudios.map(String).filter(Boolean),
  };
}

export function readVideoRequestSettings(provider = '') {
  const key = videoRequestSettingsKeyForProvider(provider);
  const scoped = readStorageJson(key, null);
  if (scoped && typeof scoped === 'object') {
    return sanitizeVideoRequestSettings(scoped, provider);
  }
  // 兼容旧版单一 key：仅迁移到当前 provider，避免两边互相覆盖
  const legacy = readStorageJson(videoRequestSettingsStorageKey, null);
  if (legacy && typeof legacy === 'object') {
    return sanitizeVideoRequestSettings(legacy, provider);
  }
  return sanitizeVideoRequestSettings(defaultsForVideoProvider(provider), provider);
}

export function writeVideoRequestSettings(settings, provider = '') {
  const key = videoRequestSettingsKeyForProvider(provider);
  writeStorageJson(key, sanitizeVideoRequestSettings(settings, provider));
}
