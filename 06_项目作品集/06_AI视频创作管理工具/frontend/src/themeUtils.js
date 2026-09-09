import { readStorageJson, writeStorageJson } from './app/uiStorage';

export const APPEARANCE_STORAGE_KEY = 'ai-video-manager:appearance:v1';

export const FONT_SCALE_OPTIONS = [
  { value: 's', label: '小' },
  { value: 'm', label: '中' },
  { value: 'l', label: '大' },
];

export const BORDER_RADIUS_OPTIONS = [
  { value: 's', label: '小' },
  { value: 'm', label: '中' },
  { value: 'l', label: '大' },
];

export const THEME_MODE_OPTIONS = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
];

export const defaultAppearanceSettings = {
  themeMode: 'system',
  fontScale: 'm',
  borderRadius: 'm',
};

const FONT_SCALE_BASE = { s: 12, m: 13, l: 15 };
const RADIUS_SCALE = {
  s: { sm: '4px', md: '6px', lg: '8px' },
  m: { sm: '6px', md: '8px', lg: '10px' },
  l: { sm: '8px', md: '12px', lg: '16px' },
};

const VALID_FONT_SCALES = new Set(FONT_SCALE_OPTIONS.map((item) => item.value));
const VALID_BORDER_RADIUS = new Set(BORDER_RADIUS_OPTIONS.map((item) => item.value));
const VALID_THEME_MODES = new Set(THEME_MODE_OPTIONS.map((item) => item.value));

export function sanitizeAppearanceSettings(raw = {}) {
  return {
    themeMode: VALID_THEME_MODES.has(raw.themeMode) ? raw.themeMode : defaultAppearanceSettings.themeMode,
    fontScale: VALID_FONT_SCALES.has(raw.fontScale) ? raw.fontScale : defaultAppearanceSettings.fontScale,
    borderRadius: VALID_BORDER_RADIUS.has(raw.borderRadius) ? raw.borderRadius : defaultAppearanceSettings.borderRadius,
  };
}

export function readAppearanceSettings() {
  return sanitizeAppearanceSettings(readStorageJson(APPEARANCE_STORAGE_KEY, defaultAppearanceSettings));
}

export function writeAppearanceSettings(settings) {
  writeStorageJson(APPEARANCE_STORAGE_KEY, sanitizeAppearanceSettings(settings));
}

export function baseContentFontSize(fontScale = 'm') {
  return FONT_SCALE_BASE[fontScale] || FONT_SCALE_BASE.m;
}

export function resolveThemeMode(themeMode = 'system') {
  if (themeMode === 'dark' || themeMode === 'light') return themeMode;
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
  return 'light';
}

export function applyAppearance(settings = defaultAppearanceSettings) {
  if (typeof document === 'undefined') return;
  const clean = sanitizeAppearanceSettings(settings);
  const root = document.documentElement;
  const effectiveTheme = resolveThemeMode(clean.themeMode);
  const radius = RADIUS_SCALE[clean.borderRadius] || RADIUS_SCALE.m;
  const baseFont = baseContentFontSize(clean.fontScale);

  root.dataset.theme = effectiveTheme;
  root.style.colorScheme = effectiveTheme;
  root.style.setProperty('--radius-sm', radius.sm);
  root.style.setProperty('--radius-md', radius.md);
  root.style.setProperty('--radius-lg', radius.lg);
  root.style.setProperty('--radius-pill', '999px');
  root.style.setProperty('--font-size-base', `${baseFont}px`);
  root.style.setProperty('--content-font-size', `${baseFont}px`);
}
