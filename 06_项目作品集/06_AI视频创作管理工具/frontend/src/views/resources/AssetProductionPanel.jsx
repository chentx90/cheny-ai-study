import React, { useEffect, useMemo, useState } from 'react';
import {
  Check,
  CircleAlert,
  Clock3,
  Edit3,
  Image as ImageIcon,
  Loader2,
  Palette,
  RefreshCw,
  RotateCw,
  Save,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { assetProductionApi } from '../../api/assetProduction';
import { readStorageJson, writeStorageJson } from '../../app/uiStorage';
import Empty from '../../components/Empty';
import PanelTitle from '../../components/PanelTitle';
import { typeLabel } from '../../utils';
import { buildAssetUrl } from './resourceMedia';

const types = [
  { id: 'character', label: '人物', defaultView: '全身', defaultSize: '1024x1536', defaultRatio: '2:3' },
  { id: 'scene', label: '场景', defaultView: '全景', defaultSize: '1536x1024', defaultRatio: '3:2' },
  { id: 'prop', label: '物品', defaultView: '单体', defaultSize: '1024x1024', defaultRatio: '1:1' },
];

const sections = [
  { id: 'prompts', label: '提示词与任务', icon: Sparkles },
  { id: 'settings', label: '风格与预设', icon: Palette },
];

const taskStatus = {
  queued: { label: '等待中', tone: 'pending' },
  processing: { label: '生成中', tone: 'pending' },
  succeeded: { label: '已完成', tone: 'success' },
  failed: { label: '失败', tone: 'danger' },
};

const emptyStyle = () => ({ name: '', prompt: '', negative_prompt: '', is_active: true, reference_asset_ids: [] });

function promptDraft(prompt) {
  return { prompt_text: prompt.prompt_text || '', negative_prompt: prompt.negative_prompt || '', view_type: prompt.view_type || '' };
}

function isPromptDirty(prompt, draft) {
  const saved = promptDraft(prompt);
  return Object.keys(saved).some((key) => saved[key] !== (draft?.[key] || ''));
}

export default function AssetProductionPanel({ projectId, selectedProject, apiBase, busy, run, notify, askConfirm, refreshAssets, refreshCards, agentRefreshVersion = '' }) {
  const storageKey = `avm:asset-production-section:${projectId}`;
  const [activeSection, setActiveSection] = useState('prompts');
  const [profiles, setProfiles] = useState([]);
  const [styles, setStyles] = useState([]);
  const [presets, setPresets] = useState([]);
  const [prompts, setPrompts] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [styleDraft, setStyleDraft] = useState(emptyStyle);
  const [editingStyleId, setEditingStyleId] = useState('');
  const [promptDrafts, setPromptDrafts] = useState({});
  const [previewOutput, setPreviewOutput] = useState(null);

  async function refresh() {
    const [profileData, styleData, presetData, promptData, taskData] = await Promise.all([
      assetProductionApi.listProfiles(projectId),
      assetProductionApi.listStyles(projectId),
      assetProductionApi.listPresets(projectId),
      assetProductionApi.listPrompts(projectId),
      assetProductionApi.listTasks(projectId),
    ]);
    setProfiles(profileData.profiles || []);
    setStyles(styleData.styles || []);
    setPresets(presetData.presets || []);
    setPrompts(promptData.prompts || []);
    setTasks(taskData.tasks || []);
  }

  useEffect(() => {
    const stored = readStorageJson(storageKey, 'prompts');
    setActiveSection(sections.some((item) => item.id === stored) ? stored : 'prompts');
    setStyleDraft(emptyStyle());
    setEditingStyleId('');
    refresh().catch((error) => notify(error.message, 'error'));
  }, [projectId]);

  useEffect(() => {
    if (agentRefreshVersion) refresh().catch((error) => notify(error.message, 'error'));
  }, [agentRefreshVersion]);

  useEffect(() => {
    setPromptDrafts(Object.fromEntries(prompts.map((item) => [item.id, promptDraft(item)])));
  }, [prompts]);

  const profilesById = useMemo(() => new Map(profiles.map((item) => [item.id, item])), [profiles]);

  function selectSection(id) {
    setActiveSection(id);
    writeStorageJson(storageKey, id);
  }

  async function saveStyle() {
    await run('saveVisualStyle', async () => {
      if (editingStyleId) await assetProductionApi.updateStyle(projectId, editingStyleId, styleDraft);
      else await assetProductionApi.createStyle(projectId, styleDraft);
      setStyleDraft(emptyStyle());
      setEditingStyleId('');
      await refresh();
      notify('项目视觉风格已保存', 'success');
    });
  }

  async function removeStyle(style) {
    const confirmed = await askConfirm({
      title: '删除视觉风格',
      message: `确认删除“${style.name}”v${style.version}？已被资产提示词引用的版本不会被删除。`,
      confirmLabel: '删除',
      tone: 'danger',
    });
    if (!confirmed) return;
    await run(`deleteStyle:${style.id}`, async () => {
      await assetProductionApi.deleteStyle(projectId, style.id);
      if (editingStyleId === style.id) {
        setEditingStyleId('');
        setStyleDraft(emptyStyle());
      }
      await refresh();
      notify('视觉风格已删除', 'success');
    });
  }

  async function savePrompt(prompt) {
    const draft = promptDrafts[prompt.id] || promptDraft(prompt);
    await assetProductionApi.updatePrompt(projectId, prompt.id, draft);
  }

  async function generateImages(prompt) {
    const profile = profilesById.get(prompt.profile_id);
    const draft = promptDrafts[prompt.id] || promptDraft(prompt);
    const dirty = isPromptDirty(prompt, draft);
    const confirmed = await askConfirm({
      title: '提交图片生成',
      message: `${dirty ? '当前编辑内容将先保存。' : ''}将按${typeLabel(profile?.type) || '实体'}预设提交“${profile?.canonical_name || '实体'}”图片任务，成功结果自动进入项目素材。`,
      confirmLabel: '提交生成',
      tone: 'primary',
    });
    if (!confirmed) return;
    await run(`imageTask:${prompt.id}`, async () => {
      try {
        if (dirty) await savePrompt(prompt);
        await assetProductionApi.generateImages(projectId, prompt.id);
        notify('图片生成完成，候选已进入项目素材', 'success');
      } finally {
        await refresh();
        await refreshAssets?.();
      }
    });
  }

  function renderSettings() {
    return <div className="asset-settings-layout">
      <section className={styles.length ? 'panel visual-style-panel' : 'panel visual-style-panel is-empty'}>
        <PanelTitle icon={Palette} title="项目视觉风格">
          {editingStyleId && <button type="button" className="icon-button secondary" title="取消编辑" aria-label="取消编辑" onClick={() => { setEditingStyleId(''); setStyleDraft(emptyStyle()); }}><X /></button>}
        </PanelTitle>
        <div className="visual-style-editor">
          <div className="visual-style-fields">
            <input value={styleDraft.name} onChange={(event) => setStyleDraft({ ...styleDraft, name: event.target.value })} placeholder="风格方案名称" />
            <label className="checkbox-row"><input type="checkbox" checked={styleDraft.is_active} onChange={(event) => setStyleDraft({ ...styleDraft, is_active: event.target.checked })} />设为当前活动风格</label>
            <textarea value={styleDraft.prompt} onChange={(event) => setStyleDraft({ ...styleDraft, prompt: event.target.value })} placeholder="统一正向风格提示词" />
            <textarea value={styleDraft.negative_prompt} onChange={(event) => setStyleDraft({ ...styleDraft, negative_prompt: event.target.value })} placeholder="统一负向风格提示词" />
          </div>
          <button type="button" className="icon-button" title={editingStyleId ? '保存为新版本' : '新建视觉风格'} aria-label={editingStyleId ? '保存为新版本' : '新建视觉风格'} disabled={!styleDraft.name.trim() || busy.has('saveVisualStyle')} onClick={saveStyle}>{busy.has('saveVisualStyle') ? <Loader2 className="spin" /> : <Save />}</button>
        </div>
        <div className="visual-style-list">
          {styles.map((style) => <article key={style.id} className={style.is_active ? 'is-active' : ''}>
            <div><strong>{style.name}</strong><small>v{style.version}{style.is_active ? ' · 当前活动' : ' · 历史版本'}</small></div>
            <p>{style.prompt || '未填写正向风格'}</p>
            <div className="row-actions">
              <button type="button" className="icon-button secondary" title="基于此版本编辑" onClick={() => { setEditingStyleId(style.id); setStyleDraft({ name: style.name, prompt: style.prompt, negative_prompt: style.negative_prompt, reference_asset_ids: style.reference_asset_ids || [], is_active: style.is_active }); }}><Edit3 /></button>
              <button type="button" className="icon-button danger" title="删除此版本" disabled={busy.has(`deleteStyle:${style.id}`)} onClick={() => removeStyle(style)}><Trash2 /></button>
            </div>
          </article>)}
          {!styles.length && <Empty text="尚未创建视觉风格" />}
        </div>
      </section>
      <section className="panel asset-preset-panel">
        <PanelTitle icon={ImageIcon} title="分类生成预设" />
        <div className="asset-preset-grid">{types.map((type) => {
          const preset = presets.find((item) => item.entity_type === type.id) || { entity_type: type.id, provider: 'openai', model: '', size: type.defaultSize, aspect_ratio: type.defaultRatio, output_count: 1, view_types: [type.defaultView], type_prompt: '', type_negative_prompt: '', auto_adopt: false };
          const update = (patch) => setPresets((rows) => [...rows.filter((item) => item.entity_type !== type.id), { ...preset, ...patch }]);
          return <form key={type.id} onSubmit={(event) => { event.preventDefault(); run(`preset:${type.id}`, async () => { await assetProductionApi.savePreset(projectId, type.id, preset); await refresh(); notify(`${type.label}预设已保存`, 'success'); }); }}>
            <div className="preset-form-heading"><h4>{type.label}</h4><button type="submit" className="icon-button" title={`保存${type.label}预设`} aria-label={`保存${type.label}预设`} disabled={busy.has(`preset:${type.id}`)}>{busy.has(`preset:${type.id}`) ? <Loader2 className="spin" /> : <Save />}</button></div>
            <div className="preset-service-row"><label>服务商<input value={preset.provider} onChange={(event) => update({ provider: event.target.value })} /></label><label>模型<input value={preset.model} onChange={(event) => update({ model: event.target.value })} placeholder="图片模型 ID" /></label></div>
            <div className="preset-row"><label>尺寸<input value={preset.size} onChange={(event) => update({ size: event.target.value })} /></label><label>比例<input value={preset.aspect_ratio} onChange={(event) => update({ aspect_ratio: event.target.value })} /></label><label>数量<input type="number" min="1" max="8" value={preset.output_count} onChange={(event) => update({ output_count: Number(event.target.value) })} /></label></div>
            <label>默认视图<input value={(preset.view_types || []).join('，')} onChange={(event) => update({ view_types: event.target.value.split(/[，,]/).map((item) => item.trim()).filter(Boolean) })} /></label>
            <div className="preset-prompt-row"><label>类型正向<textarea value={preset.type_prompt} onChange={(event) => update({ type_prompt: event.target.value })} /></label><label>类型负向<textarea value={preset.type_negative_prompt} onChange={(event) => update({ type_negative_prompt: event.target.value })} /></label></div>
            <label className="checkbox-row"><input type="checkbox" checked={preset.auto_adopt} onChange={(event) => update({ auto_adopt: event.target.checked })} />自动采用首张生成结果</label>
          </form>;
        })}</div>
      </section>
    </div>;
  }

  function renderPrompts() {
    return <section className="panel asset-prompt-panel">
      <PanelTitle icon={Sparkles} title="提示词与任务"><button type="button" className="icon-button secondary" title="刷新提示词与任务" aria-label="刷新提示词与任务" onClick={() => refresh()}><RefreshCw /></button></PanelTitle>
      <div className="asset-prompt-list">{prompts.map((prompt) => {
        const profile = profilesById.get(prompt.profile_id);
        const draft = promptDrafts[prompt.id] || promptDraft(prompt);
        const dirty = isPromptDirty(prompt, draft);
        const taskRows = tasks.filter((task) => task.asset_prompt_id === prompt.id);
        return <article key={prompt.id} className="asset-prompt-card">
          <header>
            <div><strong>{profile?.canonical_name || prompt.profile_id}</strong><small>{typeLabel(profile?.type) || '实体'} · {draft.view_type || '默认视图'} · 模板 v{prompt.template_version || '-'}</small></div>
            <div className="row-actions"><button type="button" className="icon-button secondary" title={dirty ? '保存提示词修改' : '提示词已保存'} aria-label={dirty ? '保存提示词修改' : '提示词已保存'} disabled={!dirty || busy.has(`saveAssetPrompt:${prompt.id}`)} onClick={() => run(`saveAssetPrompt:${prompt.id}`, async () => { await savePrompt(prompt); await refresh(); notify('资产提示词已保存', 'success'); })}>{busy.has(`saveAssetPrompt:${prompt.id}`) ? <Loader2 className="spin" /> : <Save />}</button><button type="button" className="icon-button" title="生成图片" aria-label="生成图片" onClick={() => generateImages(prompt)} disabled={!draft.prompt_text.trim() || busy.has(`imageTask:${prompt.id}`)}>{busy.has(`imageTask:${prompt.id}`) ? <Loader2 className="spin" /> : <ImageIcon />}</button></div>
          </header>
          <label>视图<input value={draft.view_type} onChange={(event) => setPromptDrafts({ ...promptDrafts, [prompt.id]: { ...draft, view_type: event.target.value } })} /></label>
          <label>正向提示词<textarea value={draft.prompt_text} onChange={(event) => setPromptDrafts({ ...promptDrafts, [prompt.id]: { ...draft, prompt_text: event.target.value } })} /></label>
          <label>负向提示词<textarea className="negative" value={draft.negative_prompt} onChange={(event) => setPromptDrafts({ ...promptDrafts, [prompt.id]: { ...draft, negative_prompt: event.target.value } })} /></label>
          {taskRows.length > 0 && <div className="image-task-history">
            <strong>生成记录</strong>
            {taskRows.map((task) => {
              const status = taskStatus[task.status] || { label: task.status, tone: 'pending' };
              return <div className="image-task-row" key={task.id}>
                <span className={`status-chip ${status.tone}`}>{task.status === 'processing' ? <Loader2 className="spin" /> : task.status === 'failed' ? <CircleAlert /> : task.status === 'succeeded' ? <Check /> : <Clock3 />}{status.label}</span>
                <small>{task.created_at ? new Date(task.created_at).toLocaleString() : task.id}</small>
                {task.error_message && <p title={task.error_message}>{task.error_message}</p>}
                {task.status === 'failed' && <button type="button" className="icon-button secondary" title="重试图片生成" aria-label="重试图片生成" onClick={() => generateImages(prompt)}><RotateCw /></button>}
              </div>;
            })}
          </div>}
          {taskRows.flatMap((task) => task.outputs || []).length > 0 && <div className="image-output-grid">{taskRows.flatMap((task) => task.outputs || []).map((output) => <figure key={output.id}><button type="button" className="image-output-preview" title="放大查看" onClick={() => setPreviewOutput({ ...output, entityName: profile?.canonical_name || '实体' })}><img src={buildAssetUrl(apiBase, selectedProject, { path: output.storage_path })} alt={`${profile?.canonical_name || '实体'}生成候选`} /></button><figcaption>{output.adopted ? <span><Check />已采用</span> : <button type="button" onClick={() => run(`adopt:${output.id}`, async () => { await assetProductionApi.adoptOutput(projectId, output.id); await refresh(); await refreshCards?.(); notify('候选已采用到实体卡', 'success'); })}>采用</button>}</figcaption></figure>)}</div>}
        </article>;
      })}</div>
      {!prompts.length && <Empty text="尚未生成资产提示词，请先从“待生成实体”开始" />}
    </section>;
  }

  return <><div className="asset-production-layout">
    <nav className="asset-production-tabs" aria-label="资产生成步骤">
      {sections.map((section) => { const Icon = section.icon; return <button type="button" key={section.id} className={activeSection === section.id ? 'active' : ''} onClick={() => selectSection(section.id)}><Icon />{section.label}</button>; })}
    </nav>
    {activeSection === 'settings' && renderSettings()}
    {activeSection === 'prompts' && renderPrompts()}
  </div>
    {previewOutput && <div className="asset-preview-overlay" role="dialog" aria-modal="true" aria-label={`${previewOutput.entityName} 生成结果预览`} onMouseDown={(event) => { if (event.target === event.currentTarget) setPreviewOutput(null); }}>
      <div className="asset-preview-modal image-output-modal">
        <button type="button" className="icon-button secondary asset-preview-close" title="关闭预览" aria-label="关闭预览" onClick={() => setPreviewOutput(null)}><X /></button>
        <div className="asset-preview-stage"><img className="asset-preview-media" src={buildAssetUrl(apiBase, selectedProject, { path: previewOutput.storage_path })} alt={`${previewOutput.entityName}生成结果`} /></div>
        <div className="asset-preview-details"><strong>{previewOutput.entityName}</strong><span>{previewOutput.adopted ? '已采用到实体卡' : '生成候选'}</span></div>
      </div>
    </div>}
  </>;
}
