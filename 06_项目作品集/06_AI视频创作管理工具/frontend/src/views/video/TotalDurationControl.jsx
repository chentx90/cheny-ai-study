import React, { useEffect, useState } from 'react';

export default function TotalDurationControl({ value, onChange }) {
  const specified = value != null && Number.isFinite(Number(value)) && Number(value) > 0;
  const [draft, setDraft] = useState(specified ? String(Math.round(Number(value))) : '');

  useEffect(() => {
    setDraft(specified ? String(Math.round(Number(value))) : '');
  }, [value, specified]);

  function commitDraft(nextDraft = draft) {
    const trimmed = String(nextDraft).trim();
    if (!trimmed) {
      onChange?.(null);
      setDraft('');
      return;
    }
    const seconds = Math.min(36000, Math.max(1, Math.round(Number(trimmed) || 0)));
    onChange?.(seconds > 0 ? seconds : null);
    setDraft(seconds > 0 ? String(seconds) : '');
  }

  return (
    <label className="prompt-total-duration" title="直接输入预期总时长，留空则按剧情自然切分">
      <span className="prompt-total-duration-label">总时长</span>
      <input
        type="number"
        min="1"
        max="36000"
        step="1"
        value={draft}
        placeholder="-"
        aria-label="总时长秒数"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => commitDraft()}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            event.currentTarget.blur();
          }
        }}
      />
      <span className="prompt-total-duration-unit">s</span>
    </label>
  );
}
