import React from 'react';

export default function NavButton({ item, active, onClick }) {
  const Icon = item.icon;
  return (
    <button className={active ? 'nav-item active' : 'nav-item'} title={item.label} aria-label={item.label} onClick={onClick}>
      <Icon />
      <span>{item.label}</span>
    </button>
  );
}
