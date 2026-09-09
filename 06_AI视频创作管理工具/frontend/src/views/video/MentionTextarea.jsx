import React, { useMemo, useRef, useState } from 'react';
import { typeLabel } from '../../utils';

export default function MentionTextarea({
  value,
  onChange,
  entityCards,
  onInsertMention,
  disabled = false,
  rows = 4,
  fontSize = 14,
  placeholder = '镜头提示词，输入 @ 引用实体资产',
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const ref = useRef(null);

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entityCards
      .filter((card) => {
        if (!q) return true;
        return (
          String(card.entity_name || '')
            .toLowerCase()
            .includes(q) ||
          String(card.id || '')
            .toLowerCase()
            .includes(q) ||
          String(card.state || '')
            .toLowerCase()
            .includes(q)
        );
      })
      .slice(0, 8);
  }, [entityCards, query]);

  function handleChange(event) {
    const next = event.target.value;
    const pos = event.target.selectionStart || next.length;
    onChange(next);
    setCursor(pos);
    const before = next.slice(0, pos);
    const match = before.match(/@([^\s@，,。；;：:\n\r\[\]()（）]*)$/);
    if (match) {
      setQuery(match[1] || '');
      setOpen(true);
    } else {
      setOpen(false);
      setQuery('');
    }
  }

  function insertCard(card) {
    const textarea = ref.current;
    const text = value || '';
    const pos = cursor;
    const before = text.slice(0, pos);
    const after = text.slice(pos);
    const match = before.match(/@([^\s@，,。；;：:\n\r\[\]()（）]*)$/);
    const start = match ? before.length - match[0].length : before.length;
    const inserted = `@${card.entity_name}`;
    const next = `${text.slice(0, start)}${inserted} ${after}`;
    onChange(next);
    onInsertMention?.(card);
    setOpen(false);
    setQuery('');
    requestAnimationFrame(() => {
      if (!textarea) return;
      const nextPos = start + inserted.length + 1;
      textarea.focus();
      textarea.setSelectionRange(nextPos, nextPos);
    });
  }

  return (
    <div
      className="mention-editor video-content-scalable"
      style={{ '--content-text-size': `${fontSize}px` }}
    >
      <textarea
        ref={ref}
        rows={rows}
        value={value}
        disabled={disabled}
        onChange={handleChange}
        placeholder={placeholder}
      />
      {open && suggestions.length > 0 && (
        <div className="mention-popup">
          {suggestions.map((card) => (
            <button type="button" key={card.id} onClick={() => insertCard(card)}>
              <strong>
                @{card.entity_name}
                {card.state ? `·${card.state}` : ''}
              </strong>
              <span>
                {typeLabel(card.type)} · {card.id}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
