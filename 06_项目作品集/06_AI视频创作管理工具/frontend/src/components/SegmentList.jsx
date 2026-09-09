import React, { useState } from 'react';
import { Trash2 } from 'lucide-react';
import Empty from './Empty';

const defaultEpisodeTitle = (order) => `第${order}集`;

export default function SegmentList({
  workspace,
  updateWorkspace,
  onReorderSegment,
  onDeleteSegment,
  className = 'segment-list',
  emptyText = '暂无分集',
  activeSegmentId = workspace.activeSegmentId,
  titleForSegment,
  summaryForSegment,
  onSelectSegment,
  lockForSegment,
  lockLabelForSegment,
  deleteTitle = '删除分集',
  showSummary = true,
}) {
  const [draggingId, setDraggingId] = useState('');
  const canReorder = Boolean(onReorderSegment);
  const selectSegment = (segment) => {
    if (onSelectSegment) {
      onSelectSegment(segment);
      return;
    }
    updateWorkspace({ activeSegmentId: segment.id });
  };

  return (
    <div className={className}>
      {workspace.segments.length === 0 && <Empty text={emptyText} />}
      {workspace.segments.map((segment, index) => {
        const title = titleForSegment
          ? titleForSegment(segment, index)
          : segment.title || defaultEpisodeTitle(segment.order || index + 1);
        const rawSummary = showSummary
          ? summaryForSegment
            ? summaryForSegment(segment, index)
            : (segment.content || '').replace(/\s+/g, ' ').slice(0, 92)
          : '';
        const lock = lockForSegment ? lockForSegment(segment.id) : null;
        const lockLabel = lock ? lockLabelForSegment?.(lock) || lock.display_name || '他人' : '';
        const summary = String(rawSummary || '');
        const segmentClassName = [
          'segment',
          showSummary ? '' : 'segment-compact',
          canReorder ? 'reorderable' : '',
          segment.id === activeSegmentId ? 'active' : '',
          draggingId === segment.id ? 'dragging' : '',
          lock ? 'is-locked' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <div
            className={segmentClassName}
            key={segment.id}
            role="button"
            tabIndex={0}
            draggable={canReorder}
            onClick={() => selectSegment(segment)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ' ') return;
              event.preventDefault();
              selectSegment(segment);
            }}
            onDragStart={(event) => {
              if (!canReorder) return;
              event.dataTransfer.effectAllowed = 'move';
              event.dataTransfer.setData('text/plain', segment.id);
              setDraggingId(segment.id);
            }}
            onDragOver={(event) => {
              if (canReorder && draggingId && draggingId !== segment.id) event.preventDefault();
            }}
            onDrop={(event) => {
              if (!canReorder) return;
              event.preventDefault();
              const sourceId = event.dataTransfer.getData('text/plain') || draggingId;
              onReorderSegment(sourceId, segment.id);
              setDraggingId('');
            }}
            onDragEnd={() => setDraggingId('')}
          >
            <div className="segment-main">
              <span>
                {title}
                {lock ? <em className="segment-lock-pill">锁定·{lockLabel}</em> : null}
              </span>
              {showSummary ? <small>{summary || '空原文'}</small> : null}
            </div>
            {onDeleteSegment && (
              <div className="segment-actions">
                <button
                  type="button"
                  className="icon-button danger"
                  title={deleteTitle}
                  onClick={(event) => {
                    event.stopPropagation();
                    onDeleteSegment(segment.id);
                  }}
                >
                  <Trash2 />
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
