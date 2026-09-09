import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

export default function EpisodePicker({
  segments = [],
  activeSegmentId,
  onSelect,
  getLabel,
  emptyLabel = '暂无分集',
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const activeRef = useRef(null);

  const activeIndex = segments.findIndex((segment) => segment.id === activeSegmentId);
  const activeSegment = activeIndex >= 0 ? segments[activeIndex] : null;
  const triggerLabel = activeSegment
    ? getLabel?.(activeSegment, activeIndex) || `第${activeSegment.order || activeIndex + 1}集`
    : emptyLabel;

  useEffect(() => {
    if (!open) return undefined;
    const frame = window.requestAnimationFrame(() => {
      activeRef.current?.scrollIntoView({ block: 'center' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, activeSegmentId]);

  useEffect(() => {
    if (!open) return undefined;
    function handlePointerDown(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    }
    function handleKeyDown(event) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  function toggleOpen() {
    if (segments.length === 0) return;
    setOpen((value) => !value);
  }

  function selectSegment(segmentId) {
    onSelect?.(segmentId);
    setOpen(false);
  }

  return (
    <div className={`episode-picker${open ? ' is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className="episode-picker-trigger secondary"
        disabled={segments.length === 0}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={toggleOpen}
      >
        <span className="episode-picker-trigger-label">{triggerLabel}</span>
        <ChevronDown />
      </button>
      {open && segments.length > 0 && (
        <div className="episode-picker-popover" role="listbox" aria-label="选择分集">
          <div className="episode-picker-wheel">
            {segments.map((segment, index) => {
              const label = getLabel?.(segment, index) || `第${segment.order || index + 1}集`;
              const isActive = segment.id === activeSegmentId;
              return (
                <button
                  key={segment.id}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  ref={isActive ? activeRef : undefined}
                  className={isActive ? 'episode-picker-item active' : 'episode-picker-item'}
                  onClick={() => selectSegment(segment.id)}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
