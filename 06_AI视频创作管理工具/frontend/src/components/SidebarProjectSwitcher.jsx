import React from 'react';
import { ChevronDown } from 'lucide-react';
import { recentProjects } from '../utils/projectUtils';

export default function SidebarProjectSwitcher({
  projects = [],
  selectedProject,
  collapsed = false,
  onSwitchProject,
  onOpenProjects,
}) {
  const recent = recentProjects(projects, 8);

  if (collapsed) {
    return (
      <button type="button" className="sidebar-project-compact" title={selectedProject?.name || '切换项目'} onClick={onOpenProjects}>
        <ChevronDown />
      </button>
    );
  }

  return (
    <div className="sidebar-project-switcher sidebar-project-switcher--minimal">
      <label className="sidebar-project-label">
        <span>当前项目</span>
        <div className="sidebar-project-select-wrap">
          <select
            value={selectedProject?.id || ''}
            onChange={(event) => {
              const nextId = event.target.value;
              if (nextId) onSwitchProject?.(nextId);
            }}
          >
            <option value="" disabled>
              选择项目…
            </option>
            {recent.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <ChevronDown />
        </div>
      </label>
    </div>
  );
}
