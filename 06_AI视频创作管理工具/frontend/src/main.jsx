import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applyAppearance, readAppearanceSettings } from './themeUtils';

applyAppearance(readAppearanceSettings());

createRoot(document.getElementById('root')).render(<App />);
