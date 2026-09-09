import { readStorageJson, writeStorageJson } from '../app/uiStorage';

const PREPROCESS_UI_STORAGE_KEY = 'ai-video-manager:preprocess-ui';

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function readPreprocessUiPrefs() {
  const raw = readStorageJson(PREPROCESS_UI_STORAGE_KEY, {});
  return {
    mainLeft: clamp(Number(raw.mainLeft), 28, 62) || 42,
    boardList: clamp(Number(raw.boardList), 22, 48) || 32,
  };
}

export function writePreprocessUiPrefs(prefs) {
  writeStorageJson(PREPROCESS_UI_STORAGE_KEY, {
    mainLeft: clamp(Number(prefs.mainLeft), 28, 62),
    boardList: clamp(Number(prefs.boardList), 22, 48),
  });
}

export function startMainColumnResize({ event, startLeft, onChange }) {
  event.preventDefault();
  const grid = event.currentTarget.closest('.preprocess-grid');
  const gridWidth = grid?.getBoundingClientRect().width || 1;
  const startX = event.clientX;

  function applyResize(moveEvent) {
    const delta = ((moveEvent.clientX - startX) / gridWidth) * 100;
    onChange(clamp(startLeft + delta, 28, 62));
  }

  function stopResize() {
    window.removeEventListener('pointermove', applyResize);
    window.removeEventListener('pointerup', stopResize);
  }

  window.addEventListener('pointermove', applyResize);
  window.addEventListener('pointerup', stopResize);
}

export function startBoardColumnResize({ event, startList, onChange }) {
  event.preventDefault();
  const board = event.currentTarget.closest('.preprocess-board');
  const boardWidth = board?.getBoundingClientRect().width || 1;
  const startX = event.clientX;

  function applyResize(moveEvent) {
    const delta = ((moveEvent.clientX - startX) / boardWidth) * 100;
    onChange(clamp(startList + delta, 22, 48));
  }

  function stopResize() {
    window.removeEventListener('pointermove', applyResize);
    window.removeEventListener('pointerup', stopResize);
  }

  window.addEventListener('pointermove', applyResize);
  window.addEventListener('pointerup', stopResize);
}
