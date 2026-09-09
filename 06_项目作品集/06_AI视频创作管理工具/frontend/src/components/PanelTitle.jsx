import React from 'react';

export default function PanelTitle({ icon: Icon, title, children }) {
  return <div className="panel-title"><Icon /><h3>{title}</h3><div className="panel-actions">{children}</div></div>;
}
