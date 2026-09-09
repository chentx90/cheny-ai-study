import React from 'react';

export default function ConfirmDialog({ dialog, onCancel, onConfirm }) {
  if (!dialog) return null;
  const actions = dialog.actions?.length
    ? dialog.actions
    : [{ label: dialog.confirmLabel || '确认', value: true, className: dialog.tone === 'danger' ? 'danger' : '' }];

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <header>
          <h3 id="confirm-title">{dialog.title}</h3>
          {dialog.body && <p>{dialog.body}</p>}
        </header>
        {dialog.items?.length > 0 && (
          <div className="confirm-impact">
            {dialog.items.map((item) => (
              <div className="confirm-impact-row" key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
        )}
        <footer>
          <button type="button" className="secondary" onClick={onCancel}>
            {dialog.cancelLabel || '取消'}
          </button>
          {actions.map((action) => (
            <button
              type="button"
              className={action.className || ''}
              key={`${action.label}-${String(action.value)}`}
              onClick={() => onConfirm(action.value)}
            >
              {action.label}
            </button>
          ))}
        </footer>
      </section>
    </div>
  );
}
