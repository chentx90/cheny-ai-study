import React from 'react';

export default function SegmentedControl({
  options = [],
  value,
  onChange,
  ariaLabel = '选项',
  className = 'segmented-control',
}) {
  return (
    <div className={className} role="radiogroup" aria-label={ariaLabel}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            className={active ? 'segmented-option active' : 'segmented-option'}
            onClick={() => onChange?.(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
