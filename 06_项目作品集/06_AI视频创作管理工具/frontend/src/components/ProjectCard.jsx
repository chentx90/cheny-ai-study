import React from 'react';
import { BadgeCheck, RotateCcw, Trash2 } from 'lucide-react';
import { categoryLabel } from '../utils';
import { formatProjectDate, projectListMeta, workflowStateLabel } from '../utils/projectUtils';

export default function ProjectCard({
  project,
  selected = false,
  onSelect,
  onDelete,
  onRestore,
  canDelete = true,
}) {
  const deleted = Boolean(project.deleted_at);
  const visibilityLabel = project.visibility === 'public' ? '公共' : '私有';

  return (
    <article className={`project-card${selected ? ' selected' : ''}${deleted ? ' is-trash' : ''}`}>
      <button
        type="button"
        className="project-card-main"
        disabled={deleted}
        onClick={() => onSelect?.(project.id)}
      >
        <div className="project-card-head">
          <strong>{project.name}</strong>
          {selected && <BadgeCheck />}
        </div>
        <span className="project-card-badge">
          {deleted ? '回收站' : categoryLabel(project.category)} · {visibilityLabel}
          {project.my_role ? ` · ${project.my_role}` : ''}
        </span>
        <span className="project-card-stage">{workflowStateLabel(project.current_state)}</span>
        {project.description ? (
          <p className="project-card-desc">{project.description}</p>
        ) : null}
        <small className="project-card-meta">{projectListMeta(project)}</small>
        <small className="project-card-date">更新 {formatProjectDate(project.updated_at)}</small>
      </button>
      {deleted ? (
        <button type="button" className="icon-button secondary project-card-action" title="恢复项目" onClick={() => onRestore?.(project)}>
          <RotateCcw />
        </button>
      ) : canDelete ? (
        <button type="button" className="icon-button danger project-card-action" title="删除项目" onClick={() => onDelete?.(project)}>
          <Trash2 />
        </button>
      ) : null}
    </article>
  );
}
