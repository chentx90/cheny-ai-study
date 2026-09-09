import React from 'react';

export const TOOLBAR_CONTROL_SIZE = 32;

export default function FontSizeControls({
  value,
  onChange,
  min = 12,
  max = 22,
  className = 'font-size-controls',
}) {
  const current = Number(value) || min;

  function step(delta, event) {
    event.preventDefault();
    event.stopPropagation();
    const next = Math.min(max, Math.max(min, current + delta));
    if (next !== current) onChange?.(next);
  }

  return (
    <div className={className}>
      <button
        type="button"
        className="secondary font-size-btn"
        disabled={current <= min}
        title="减小字号"
        onClick={(event) => step(-1, event)}
      >
        A−
      </button>
      <span className="font-size-value">{current}</span>
      <button
        type="button"
        className="secondary font-size-btn"
        disabled={current >= max}
        title="增大字号"
        onClick={(event) => step(1, event)}
      >
        A+
      </button>
    </div>
  );
}
