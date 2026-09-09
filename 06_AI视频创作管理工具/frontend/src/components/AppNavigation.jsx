import React from 'react';
import { PanelLeftClose, PanelLeftOpen, Settings } from 'lucide-react';

import studioMark from '../assets/studio-mark.png';
import NavButton from './NavButton';
import SidebarProjectSwitcher from './SidebarProjectSwitcher';

export function ProjectSidebar({
  authDisabled,
  health,
  projects,
  selectedProject,
  sidebarCollapsed,
  user,
  onOpenProjects,
  onSwitchProject,
  onToggle,
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand-mark" src={studioMark} alt="AI 视频创作管理标识" />
        <div>
          <h1>AI 视频创作管理</h1>
          <p>
            {authDisabled ? '本地模式' : user?.display_name || user?.username}
            {health === 'ok' ? ' · 服务正常' : health === 'error' ? ' · 后端未连接' : ' · 检查中'}
          </p>
        </div>
        <button
          type="button"
          className="sidebar-toggle"
          title={sidebarCollapsed ? '展开导航栏' : '折叠导航栏'}
          aria-label={sidebarCollapsed ? '展开导航栏' : '折叠导航栏'}
          onClick={onToggle}
        >
          {sidebarCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </button>
      </div>
      <SidebarProjectSwitcher
        projects={projects}
        selectedProject={selectedProject}
        collapsed={sidebarCollapsed}
        onSwitchProject={onSwitchProject}
        onOpenProjects={onOpenProjects}
      />
    </aside>
  );
}

export function TopNavigation({
  currentViewLabel,
  items,
  notice,
  selectedProject,
  view,
  onChangeView,
}) {
  const contextLabel = notice || (
    view === 'projects'
      ? '选择项目、初始化项目并维护项目分类'
      : selectedProject?.name || '未选择项目'
  );

  return (
    <header className="topbar">
      <h2 className="topbar-heading">
        <span className="topbar-view">{currentViewLabel}</span>
        <span className="topbar-sep" aria-hidden="true">·</span>
        <span className="topbar-meta">{contextLabel}</span>
      </h2>
      <nav className="topbar-nav" aria-label="主导航">
        {items.map((item) => (
          <NavButton
            key={item.id}
            item={item}
            active={view === item.id}
            onClick={() => onChangeView(item.id)}
          />
        ))}
      </nav>
      <button
        type="button"
        className={view === 'settings' ? 'topbar-settings active' : 'topbar-settings'}
        title="设置"
        aria-label="设置"
        onClick={() => onChangeView('settings')}
      >
        <Settings />
      </button>
    </header>
  );
}
