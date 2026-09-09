import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Edit3, FileSearch, Loader2, Plus, RefreshCw, Save, Sparkles, Trash2, WandSparkles, X } from 'lucide-react';
import { assetProductionApi } from '../../api/assetProduction';
import { readStorageJson, writeStorageJson } from '../../app/uiStorage';
import Empty from '../../components/Empty';
import PanelTitle from '../../components/PanelTitle';
import { typeLabel } from '../../utils';

const roleLabels = { protagonist: '主角', supporting: '重要配角', minor: '普通配角', guest: '客串' };

export default function EntityProfilesPanel({ projectId, episodes = [], busy, run, notify, askConfirm, onCardsChanged, agentRefreshVersion = '' }) {
  const [profiles, setProfiles] = useState([]);
  const [prompts, setPrompts] = useState([]);
  const [styles, setStyles] = useState([]);
  const [filter, setFilter] = useState({ search: '', type: 'all', importance: 'all' });
  const [expanded, setExpanded] = useState(new Set());
  const [selectedEpisodes, setSelectedEpisodes] = useState([]);
  const [editing, setEditing] = useState(null);
  const analyzableEpisodes = useMemo(() => episodes.filter((episode) => episode.hasScript), [episodes]);
  const episodeAvailabilityKey = useMemo(() => episodes.map((episode) => `${episode.id}:${episode.hasScript ? 1 : 0}`).join('|'), [episodes]);

  const selectionKey = `avm:entity-analysis-scope:v2:${projectId}`;

  const refresh = async () => {
    const [profileData, promptData, styleData] = await Promise.all([
      assetProductionApi.listProfiles(projectId),
      assetProductionApi.listPrompts(projectId),
      assetProductionApi.listStyles(projectId),
    ]);
    setProfiles(profileData.profiles || []);
    setPrompts(promptData.prompts || []);
    setStyles(styleData.styles || []);
  };
  useEffect(() => { refresh().catch((error) => notify(error.message, 'error')); }, [projectId]);
  useEffect(() => {
    if (agentRefreshVersion) refresh().catch((error) => notify(error.message, 'error'));
  }, [agentRefreshVersion]);
  useEffect(() => {
    try {
      const stored = readStorageJson(selectionKey, { mode: 'all', ids: [] });
      const available = new Set(analyzableEpisodes.map((episode) => episode.id));
      const legacyIds = Array.isArray(stored) ? stored : null;
      const mode = legacyIds ? (legacyIds.length ? 'custom' : 'all') : stored?.mode === 'custom' ? 'custom' : 'all';
      const sourceIds = legacyIds || (Array.isArray(stored?.ids) ? stored.ids : []);
      const validSelection = mode === 'all'
        ? analyzableEpisodes.map((episode) => episode.id)
        : sourceIds.filter((id) => available.has(id));
      setSelectedEpisodes(validSelection);
      writeStorageJson(selectionKey, { mode, ids: validSelection });
    } catch {
      setSelectedEpisodes(analyzableEpisodes.map((episode) => episode.id));
    }
  }, [projectId, episodeAvailabilityKey]);

  const filtered = useMemo(() => profiles.filter((profile) => {
    const search = filter.search.trim().toLowerCase();
    return (filter.type === 'all' || profile.type === filter.type)
      && (filter.importance === 'all' || profile.importance === filter.importance)
      && (!search || `${profile.canonical_name} ${(profile.aliases || []).join(' ')}`.toLowerCase().includes(search));
  }), [filter, profiles]);
  const activeStyle = styles.find((style) => style.is_active);
  const latestPromptByProfile = useMemo(() => {
    const result = new Map();
    prompts.forEach((prompt) => { if (!result.has(prompt.profile_id)) result.set(prompt.profile_id, prompt); });
    return result;
  }, [prompts]);
  const allEpisodesSelected = analyzableEpisodes.length > 0 && selectedEpisodes.length === analyzableEpisodes.length;

  async function analyze() {
    if (!analyzableEpisodes.length) {
      notify('当前项目没有已入库的剧本原文，请先在预处理中保存剧本', 'error');
      return;
    }
    const confirmed = await askConfirm({
      title: '运行实体分析',
      message: `将分析选中的 ${selectedEpisodes.length} 集剧本，并更新跨集统计。`,
      confirmLabel: '开始分析', tone: 'primary',
    });
    if (!confirmed) return;
    await run('entityAnalysis', async () => {
      const data = await assetProductionApi.runAnalysis(projectId, selectedEpisodes);
      setProfiles(data.profiles || []);
      notify(`实体分析完成，共 ${data.profiles?.length || 0} 项`, 'success');
    });
  }

  async function saveEdit() {
    await run(`profile:${editing.id}`, async () => {
      const updated = await assetProductionApi.updateProfile(projectId, editing.id, {
        canonical_name: editing.canonical_name,
        type: editing.type,
        aliases: String(editing.aliasesText || '').split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        role: editing.role,
        importance: editing.importance,
        setting: editing.setting,
        status: editing.status,
      });
      setProfiles((rows) => rows.map((item) => item.id === updated.id ? updated : item));
      setEditing(null);
      notify('实体档案已保存', 'success');
    });
  }

  async function remove(profile) {
    const confirmed = await askConfirm({ title: '删除实体档案', message: `确认删除“${profile.canonical_name}”及其证据、变体和资产提示词？`, confirmLabel: '删除', tone: 'danger' });
    if (!confirmed) return;
    await run(`deleteProfile:${profile.id}`, async () => {
      await assetProductionApi.deleteProfile(projectId, profile.id);
      setProfiles((rows) => rows.filter((item) => item.id !== profile.id));
      notify('实体档案已删除', 'success');
    });
  }

  async function generateSetting(profile) {
    const confirmed = await askConfirm({
      title: profile.setting ? '重新生成实体设定' : '生成实体设定',
      message: `将调用 LLM 根据剧本证据${profile.setting ? '覆盖' : '生成'}“${profile.canonical_name}”的视觉设定。`,
      confirmLabel: profile.setting ? '重新生成' : '生成设定',
      tone: 'primary',
    });
    if (!confirmed) return;
    await run(`setting:${profile.id}`, async () => {
      const updated = await assetProductionApi.generateSetting(projectId, profile.id);
      setProfiles((rows) => rows.map((item) => item.id === updated.id ? updated : item));
      notify('实体设定已生成', 'success');
    });
  }

  async function generateAssetPrompt(profile) {
    const existing = latestPromptByProfile.get(profile.id);
    const confirmed = await askConfirm({
      title: existing ? '重新生成资产提示词' : '生成资产提示词',
      message: `将使用当前活动风格和${typeLabel(profile.type)}预设，为“${profile.canonical_name}”调用 LLM。${existing ? '现有提示词会保留为历史版本。' : ''}`,
      confirmLabel: existing ? '重新生成' : '生成提示词',
      tone: 'primary',
    });
    if (!confirmed) return;
    await run(`assetPrompt:${profile.id}`, async () => {
      await assetProductionApi.generatePrompt(projectId, profile.id);
      await refresh();
      notify('资产提示词已生成，可在“资产生成”中编辑并出图', 'success');
    });
  }

  const storeSelection = (ids, mode = ids.length === analyzableEpisodes.length ? 'all' : 'custom') => {
    setSelectedEpisodes(ids);
    try {
      writeStorageJson(selectionKey, { mode, ids });
    } catch {
      // Selection still works for the current page when browser storage is unavailable.
    }
  };
  const toggleEpisode = (id) => storeSelection(selectedEpisodes.includes(id) ? selectedEpisodes.filter((item) => item !== id) : [...selectedEpisodes, id]);
  const toggleAllEpisodes = () => storeSelection(
    allEpisodesSelected ? [] : analyzableEpisodes.map((episode) => episode.id),
    allEpisodesSelected ? 'custom' : 'all',
  );
  const toggleExpanded = (id) => setExpanded((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <section className="panel entity-profile-panel">
      <PanelTitle icon={FileSearch} title="实体清单">
        <button type="button" onClick={analyze} disabled={busy.has('entityAnalysis') || !selectedEpisodes.length} title={!analyzableEpisodes.length ? '请先在预处理中保存剧本原文' : !selectedEpisodes.length ? '请至少选择一集' : ''}>
          {busy.has('entityAnalysis') ? <Loader2 className="spin" /> : <RefreshCw />}
          {profiles.length ? '重新分析' : '分析剧本'}
        </button>
      </PanelTitle>
      <div className="entity-analysis-scope">
        <strong>分析范围</strong>
        <button type="button" className={allEpisodesSelected ? 'selected' : ''} onClick={toggleAllEpisodes}>{allEpisodesSelected ? '取消全选' : '全选'}</button>
        <span className="scope-count">已选 {selectedEpisodes.length} / {analyzableEpisodes.length}</span>
        <div className="episode-scope-list">
          {episodes.map((episode) => (
            <label key={episode.id} className={!episode.hasScript ? 'is-disabled' : ''} title={!episode.hasScript ? '该集尚未保存剧本原文' : ''}>
              <input type="checkbox" disabled={!episode.hasScript} checked={selectedEpisodes.includes(episode.id)} onChange={() => toggleEpisode(episode.id)} />
              <span>{episode.title || `第${episode.order}集`}{!episode.hasScript ? ' · 无剧本' : ''}</span>
            </label>
          ))}
        </div>
        {!episodes.length && <span className="scope-empty">项目暂无分集</span>}
      </div>
      {!activeStyle && profiles.length > 0 && <div className="inline-warning">生成资产提示词前，请先在“资产生成 / 风格与预设”中启用项目视觉风格。</div>}
      <div className="entity-profile-toolbar">
        <input value={filter.search} onChange={(event) => setFilter({ ...filter, search: event.target.value })} placeholder="搜索名称或别名" />
        <select value={filter.type} onChange={(event) => setFilter({ ...filter, type: event.target.value })}>
          <option value="all">全部类型</option><option value="character">人物</option><option value="scene">场景</option><option value="prop">物品</option>
        </select>
        <select value={filter.importance} onChange={(event) => setFilter({ ...filter, importance: event.target.value })}>
          <option value="all">全部重要性</option>{['S', 'A', 'B', 'C'].map((item) => <option key={item}>{item}</option>)}
        </select>
        <span>{filtered.length} / {profiles.length}</span>
      </div>
      {!profiles.length && <Empty text="暂无实体档案，请先分析已入库剧本" />}
      <div className="entity-profile-list">
        {filtered.map((profile) => {
          const open = expanded.has(profile.id);
          const assetPrompt = latestPromptByProfile.get(profile.id);
          const promptDisabledReason = !profile.setting ? '请先生成或填写视觉设定' : !activeStyle ? '请先启用项目视觉风格' : '';
          const episodeOrders = (profile.mentions || [])
            .map((item) => item.episode_order)
            .filter((value, index, rows) => rows.indexOf(value) === index);
          return (
            <article className="entity-profile-row" key={profile.id}>
              <button type="button" className="entity-profile-expand" onClick={() => toggleExpanded(profile.id)}>{open ? <ChevronDown /> : <ChevronRight />}</button>
              <div className="entity-profile-identity"><strong>{profile.canonical_name}</strong><small>{(profile.aliases || []).join(' / ') || '无别名'}</small></div>
              <span>{typeLabel(profile.type)}</span>
              <span className={`importance-badge importance-${profile.importance}`}>{profile.importance}</span>
              <span>{roleLabels[profile.role] || profile.role || '-'}</span>
              <span>{profile.mention_count} 次 / {profile.scene_count} 场</span>
              <span className="entity-episode-summary" title={episodeOrders.length ? `第 ${episodeOrders.join('、')} 集` : '无集数证据'}>{episodeOrders.length ? `涉及 ${episodeOrders.length} 集` : '无集数'}</span>
              <div className="row-actions">
                <button type="button" className="icon-button secondary" title={profile.setting ? '重新生成设定' : '生成设定'} disabled={busy.has(`setting:${profile.id}`)} onClick={() => generateSetting(profile)}>{busy.has(`setting:${profile.id}`) ? <Loader2 className="spin" /> : <Sparkles />}</button>
                <button type="button" className={`icon-button secondary${assetPrompt ? ' has-output' : ''}`} title={promptDisabledReason || (assetPrompt ? '重新生成资产提示词' : '生成资产提示词')} disabled={Boolean(promptDisabledReason) || busy.has(`assetPrompt:${profile.id}`)} onClick={() => generateAssetPrompt(profile)}>{busy.has(`assetPrompt:${profile.id}`) ? <Loader2 className="spin" /> : <WandSparkles />}</button>
                <button type="button" className="icon-button secondary" title="编辑" onClick={() => setEditing({ ...profile, aliasesText: (profile.aliases || []).join('，') })}><Edit3 /></button>
                <button type="button" className="icon-button secondary" title={profile.linked_entity_card_id ? '实体卡已入库' : '创建实体卡'} disabled={Boolean(profile.linked_entity_card_id) || busy.has(`card:${profile.id}`)} onClick={() => run(`card:${profile.id}`, async () => {
                  await assetProductionApi.createEntityCard(projectId, profile.id); await refresh(); await onCardsChanged?.(); notify('实体卡已入库', 'success');
                })}>{busy.has(`card:${profile.id}`) ? <Loader2 className="spin" /> : <Plus />}</button>
                <button type="button" className="icon-button danger" title="删除" disabled={busy.has(`deleteProfile:${profile.id}`)} onClick={() => remove(profile)}><Trash2 /></button>
              </div>
              {open && <div className="entity-profile-detail">
                <div><strong>视觉设定</strong><p>{profile.setting || '尚未生成或人工填写设定'}</p></div>
                <div><strong>资产提示词</strong><p>{assetPrompt?.prompt_text || '尚未生成'}</p></div>
                <div><strong>证据</strong>{(profile.mentions || []).map((mention) => <blockquote key={mention.id}>第 {mention.episode_order} 集：{mention.evidence || mention.alias}</blockquote>)}</div>
                <div><strong>状态变体与集数</strong><p>{(profile.variants || []).map((item) => item.name).join(' / ') || '无'}</p><p>{episodeOrders.length ? `第 ${episodeOrders.join('、')} 集` : '无集数证据'}</p></div>
              </div>}
            </article>
          );
        })}
      </div>
      {editing && <div className="modal-backdrop" role="dialog" aria-modal="true"><div className="entity-profile-editor">
        <header><h3>编辑实体档案</h3><button type="button" className="icon-button secondary" title="关闭" aria-label="关闭" onClick={() => setEditing(null)}><X /></button></header>
        <div className="entity-profile-editor-grid">
          <label>名称<input value={editing.canonical_name} onChange={(event) => setEditing({ ...editing, canonical_name: event.target.value })} /></label>
          <label>类型<select value={editing.type} onChange={(event) => setEditing({ ...editing, type: event.target.value })}><option value="character">人物</option><option value="scene">场景</option><option value="prop">物品</option></select></label>
          <label>重要性<select value={editing.importance} onChange={(event) => setEditing({ ...editing, importance: event.target.value })}>{['S', 'A', 'B', 'C'].map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>角色定位<select value={editing.role || ''} onChange={(event) => setEditing({ ...editing, role: event.target.value })}><option value="">不适用</option>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="span-2">别名<input value={editing.aliasesText} onChange={(event) => setEditing({ ...editing, aliasesText: event.target.value })} /></label>
          <label className="span-2">视觉设定<textarea value={editing.setting || ''} onChange={(event) => setEditing({ ...editing, setting: event.target.value })} /></label>
        </div>
        <footer><button type="button" className="secondary" onClick={() => setEditing(null)}>取消</button><button type="button" disabled={!editing.canonical_name.trim() || busy.has(`profile:${editing.id}`)} onClick={saveEdit}>{busy.has(`profile:${editing.id}`) ? <Loader2 className="spin" /> : <Save />}保存</button></footer>
      </div></div>}
    </section>
  );
}
