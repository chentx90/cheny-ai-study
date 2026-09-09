import { useCallback, useRef, useState } from 'react';

const ERROR_TOAST_DEDUPE_MS = 10000;

export function useAsyncRun() {
  const [busy, setBusy] = useState(new Set());
  const [notice, setNotice] = useState('');
  const [toasts, setToasts] = useState([]);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const lastErrorToastRef = useRef({ key: '', at: 0 });

  const notify = useCallback((message, type = 'info', title) => {
    setNotice(message);
    if (type === 'error') {
      const key = `${title || ''}|${message || ''}`;
      const now = Date.now();
      if (key === lastErrorToastRef.current.key && now - lastErrorToastRef.current.at < ERROR_TOAST_DEDUPE_MS) {
        return;
      }
      lastErrorToastRef.current = { key, at: now };
    }
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((prev) => [{ id, message, type, title }, ...prev].slice(0, 5));
    if (type !== 'error') {
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((toast) => toast.id !== id));
      }, 3500);
    }
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const askConfirm = useCallback((options) => {
    return new Promise((resolve) => {
      setConfirmDialog({ ...options, resolve });
    });
  }, []);

  const resolveConfirm = useCallback((value) => {
    setConfirmDialog((current) => {
      if (current?.resolve) current.resolve(value);
      return null;
    });
  }, []);

  const run = useCallback(
    async (label, task) => {
      setBusy((prev) => new Set(prev).add(label));
      setNotice('');
      try {
        return await task();
      } catch (error) {
        const title = label.startsWith('testLlm:')
          ? 'LLM 连通性测试失败'
          : label === 'testVideoConnection'
            ? '视频连通性测试失败'
            : label === 'fetchVideoModels'
              ? '获取模型列表失败'
              : undefined;
        notify(error.message || '操作失败', 'error', title);
        return undefined;
      } finally {
        setBusy((prev) => {
          const next = new Set(prev);
          next.delete(label);
          return next;
        });
      }
    },
    [notify],
  );

  return {
    busy,
    notice,
    toasts,
    confirmDialog,
    notify,
    dismissToast,
    askConfirm,
    resolveConfirm,
    run,
    setNotice,
  };
}
