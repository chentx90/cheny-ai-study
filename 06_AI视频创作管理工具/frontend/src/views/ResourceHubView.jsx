import React, { useState } from 'react';
import { Database, FileSearch, FolderOpen, Images } from 'lucide-react';
import ResourceView from './ResourceView';
import AssetProductionPanel from './resources/AssetProductionPanel';
import EntityProfilesPanel from './resources/EntityProfilesPanel';
import { readStorageJson, writeStorageJson } from '../app/uiStorage';

const tabs = [
  { id: 'profiles', label: '实体清单', icon: FileSearch },
  { id: 'cards', label: '实体卡库', icon: Database },
  { id: 'production', label: '资产生成', icon: Images },
  { id: 'assets', label: '项目素材', icon: FolderOpen },
];

export default function ResourceHubView({ selectedProject, workspace, run, notify, askConfirm, refreshEntityCards, refreshAssets, agentMutation, ...resourceProps }) {
  const storageKey = `avm:resource-tab:${selectedProject.id}`;
  const [activeTab, setActiveTab] = useState(() => readStorageJson(storageKey, 'profiles'));
  const agentRefreshVersion = agentMutation?.effects?.includes('asset-production') ? agentMutation.id : '';
  const selectTab = (tabId) => {
    setActiveTab(tabId);
    writeStorageJson(storageKey, tabId);
  };
  return <div className="resource-hub">
    <nav className="resource-tabs" aria-label="资源管理分类">{tabs.map((tab) => { const Icon = tab.icon; return <button type="button" key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => selectTab(tab.id)}><Icon />{tab.label}</button>; })}</nav>
    {activeTab === 'profiles' && <EntityProfilesPanel projectId={selectedProject.id} episodes={(workspace?.segments || []).map((episode) => ({ ...episode, hasScript: Boolean(String(workspace?.scripts?.[episode.id] || '').trim()) }))} busy={resourceProps.busy} run={run} notify={notify} askConfirm={askConfirm} onCardsChanged={() => refreshEntityCards(selectedProject.id)} agentRefreshVersion={agentRefreshVersion} />}
    {(activeTab === 'cards' || activeTab === 'assets') && <ResourceView {...resourceProps} selectedProject={selectedProject} mode={activeTab} />}
    {activeTab === 'production' && <AssetProductionPanel projectId={selectedProject.id} selectedProject={selectedProject} apiBase={resourceProps.apiBase} busy={resourceProps.busy} run={run} notify={notify} askConfirm={askConfirm} refreshAssets={() => refreshAssets(selectedProject.id)} refreshCards={() => refreshEntityCards(selectedProject.id)} agentRefreshVersion={agentRefreshVersion} />}
  </div>;
}
