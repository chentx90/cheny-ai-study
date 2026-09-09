import React from 'react';
import Empty from './Empty';

export default function ProjectGate({ selectedProject, children }) {
  if (selectedProject) return children;
  return <section className="panel empty-state-panel"><Empty text="请先在项目管理中选择或初始化项目" /></section>;
}
