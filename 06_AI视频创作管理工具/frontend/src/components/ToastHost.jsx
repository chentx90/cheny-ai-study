import React from 'react';
import { X } from 'lucide-react';

export default function ToastHost({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="toast-host" aria-live="polite">
      {toasts.map((toast) => (
        <div className={`toast ${toast.type || 'info'}`} key={toast.id}>
          <div>
            <strong>{toast.title || (toast.type === 'error' ? '操作失败' : '提示')}</strong>
            <p>{toast.message}</p>
          </div>
          <button type="button" aria-label="关闭提示" onClick={() => onDismiss(toast.id)}>
            <X />
          </button>
        </div>
      ))}
    </div>
  );
}
