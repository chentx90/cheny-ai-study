const configuredApiBase = import.meta.env.VITE_API_BASE;
export const API_BASE =
  configuredApiBase !== undefined && configuredApiBase !== null
    ? configuredApiBase
    : '';

/** Short CRUD / list calls. */
export const DEFAULT_REQUEST_TIMEOUT_MS = 30000;
/** LLM-heavy endpoints (切分、转剧本、生成提示词等). */
export const LLM_REQUEST_TIMEOUT_MS = 600000;

let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  constructor(message, { status, statusText, body } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.statusText = statusText;
    this.body = body;
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export { sleep };

export function isTransientNetworkError(error) {
  return error instanceof ApiError && error.status === 0;
}

function isRetryableRequestError(error) {
  if (!(error instanceof ApiError)) return false;
  return error.status === 0 || [502, 503, 504].includes(error.status);
}

function formatDetail(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === 'object' && item.msg) {
          const location = Array.isArray(item.loc) ? item.loc.join('.') : '';
          return location ? `${location}: ${item.msg}` : item.msg;
        }
        return formatDetail(item, '');
      })
      .filter(Boolean);
    return messages.length ? messages.join('；') : fallback;
  }
  if (typeof detail === 'object') {
    const parts = [];
    const nested = detail.detail || detail.message || detail.error;
    if (nested) parts.push(formatDetail(nested, ''));
    if (detail.label) parts.push(`使用点：${detail.label}`);
    if (detail.provider) parts.push(`服务商：${detail.provider}`);
    if (detail.model) parts.push(`模型：${detail.model}`);
    if (detail.base_url) parts.push(`地址：${detail.base_url}`);
    if (parts.length) return parts.filter(Boolean).join(' / ');
    try {
      return JSON.stringify(detail);
    } catch (_error) {
      return fallback;
    }
  }
  return String(detail);
}

function formatErrorBody(body, fallback) {
  if (!body || typeof body !== 'object') return fallback;
  return formatDetail(body.detail || body.message || body.error, fallback);
}

function withTimeoutSignal(options = {}, timeoutMs = 0) {
  const ms = Number(timeoutMs || options.timeoutMs || 0);
  if (!ms || ms <= 0) {
    const { timeoutMs: _ignored, ...rest } = options;
    return rest;
  }
  const { timeoutMs: _ignored, signal: outerSignal, ...rest } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), ms);
  if (outerSignal) {
    if (outerSignal.aborted) controller.abort();
    else outerSignal.addEventListener('abort', () => controller.abort(), { once: true });
  }
  return {
    ...rest,
    signal: controller.signal,
    __clearTimeout: () => window.clearTimeout(timer),
  };
}

function networkErrorMessage(aborted) {
  if (aborted) {
    return '请求超时：LLM/长任务可能仍在后端执行。请稍候刷新查看结果；若持续无响应再检查 Docker 服务日志。';
  }
  return '无法连接后端服务，请确认本软件服务已启动（Docker 默认 http://127.0.0.1:8010）。';
}

export async function request(path, options = {}) {
  let response;
  const fetchOptions = withTimeoutSignal(
    {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    },
    options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS,
  );
  const clearTimeoutFn = fetchOptions.__clearTimeout;
  delete fetchOptions.__clearTimeout;
  try {
    response = await fetch(`${API_BASE}${path}`, fetchOptions);
  } catch (error) {
    const aborted = error?.name === 'AbortError';
    throw new ApiError(networkErrorMessage(aborted), {
      status: 0,
      statusText: aborted ? 'Timeout' : 'Network Error',
      body: { detail: error?.message || 'Failed to fetch' },
    });
  } finally {
    clearTimeoutFn?.();
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const skipUnauthorized =
      path.startsWith('/api/auth/me') ||
      path === '/api/auth/setup-status';
    if (response.status === 401 && unauthorizedHandler && !skipUnauthorized) {
      unauthorizedHandler();
    }
    if (response.status === 404) {
      throw new ApiError('后端接口不存在（404），请重启后端服务后再试', {
        status: response.status,
        statusText: response.statusText,
        body,
      });
    }
    throw new ApiError(formatErrorBody(body, response.statusText || '操作失败'), {
      status: response.status,
      statusText: response.statusText,
      body,
    });
  }
  return response.json();
}

export async function uploadBinary(path, formData, options = {}) {
  let response;
  const fetchOptions = withTimeoutSignal(
    {
      credentials: 'include',
      method: 'POST',
      body: formData,
      ...options,
    },
    options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS,
  );
  const clearTimeoutFn = fetchOptions.__clearTimeout;
  delete fetchOptions.__clearTimeout;
  try {
    response = await fetch(`${API_BASE}${path}`, fetchOptions);
  } catch (error) {
    const aborted = error?.name === 'AbortError';
    throw new ApiError(networkErrorMessage(aborted), {
      status: 0,
      statusText: aborted ? 'Timeout' : 'Network Error',
      body: { detail: error?.message || 'Failed to fetch' },
    });
  } finally {
    clearTimeoutFn?.();
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(formatErrorBody(body, response.statusText || '上传失败'), {
      status: response.status,
      statusText: response.statusText,
      body,
    });
  }
  return response.json();
}

export async function requestWithRetry(path, options = {}, retryOptions = {}) {
  const attempts = Math.max(1, Number(retryOptions.attempts || 3));
  const delayMs = Math.max(50, Number(retryOptions.delayMs || 400));
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await request(path, options);
    } catch (error) {
      lastError = error;
      if (attempt >= attempts || !isRetryableRequestError(error)) throw error;
      await sleep(delayMs * attempt);
    }
  }
  throw lastError;
}
