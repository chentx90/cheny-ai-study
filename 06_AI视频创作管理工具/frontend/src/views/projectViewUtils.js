import { readStorageJson, writeStorageJson } from '../app/uiStorage';

const PROJECT_UI_STORAGE_KEY = 'ai-video-manager:project-ui';

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function readProjectUiPrefs() {
  const raw = readStorageJson(PROJECT_UI_STORAGE_KEY, {});
  return {
    leftWidth: clamp(Number(raw.leftWidth), 28, 58) || 38,
  };
}

export function writeProjectUiPrefs(prefs) {
  writeStorageJson(PROJECT_UI_STORAGE_KEY, {
    leftWidth: clamp(Number(prefs.leftWidth), 28, 58),
  });
}

export function startProjectColumnResize({ event, startLeft, onChange }) {
  event.preventDefault();
  const grid = event.currentTarget.closest('.project-grid');
  const gridWidth = grid?.getBoundingClientRect().width || 1;
  const startX = event.clientX;

  function applyResize(moveEvent) {
    const delta = ((moveEvent.clientX - startX) / gridWidth) * 100;
    onChange(clamp(startLeft + delta, 28, 58));
  }

  function stopResize() {
    window.removeEventListener('pointermove', applyResize);
    window.removeEventListener('pointerup', stopResize);
  }

  window.addEventListener('pointermove', applyResize);
  window.addEventListener('pointerup', stopResize);
}
