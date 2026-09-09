export function sanitizeFilename(name, fallback = 'export') {
  const cleaned = String(name || fallback)
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80);
  return cleaned || fallback;
}

function triggerBlobDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

export function downloadTextFile(content, filename) {
  const safeName = sanitizeFilename(filename, 'text');
  const finalName = safeName.endsWith('.txt') || safeName.endsWith('.md') ? safeName : `${safeName}.txt`;
  const blob = new Blob([content ?? ''], { type: 'text/plain;charset=utf-8' });
  triggerBlobDownload(blob, finalName);
}

export async function downloadRemoteFile(url, filename) {
  if (!url) throw new Error('下载地址无效');
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) {
    throw new Error(`下载失败（${response.status}）`);
  }
  const blob = await response.blob();
  if (!blob || blob.size === 0) {
    throw new Error('下载失败：文件为空（0KB），请刷新后重试或使用任务「下载」按钮');
  }
  triggerBlobDownload(blob, sanitizeFilename(filename, 'download'));
}
