import React, { useEffect, useMemo, useState } from 'react';
import { Copy, FileText, Plus, RotateCcw, Save, Trash2, WandSparkles } from 'lucide-react';
import Empty from '../components/Empty';
import PanelTitle from '../components/PanelTitle';
import { promptCategories } from '../constants';
import { describePromptVariable } from '../utils/promptVariableDescriptions';

const requiredVariablesByCategory = {
  split_planning: ['minutes', 'content'],
  script_convert: ['content_type', 'content'],
  entity_extract: ['episode_title', 'episode_order', 'episode_script'],
  entity_consolidate: ['extraction_catalog'],
  entity_setting: ['entity_profile'],
  character_asset_prompt: ['entity_name', 'entity_setting', 'variant_setting', 'project_style_prompt', 'project_negative_prompt', 'type_prompt', 'type_negative_prompt', 'reference_summary', 'view_type'],
  scene_asset_prompt: ['entity_name', 'entity_setting', 'variant_setting', 'project_style_prompt', 'project_negative_prompt', 'type_prompt', 'type_negative_prompt', 'reference_summary', 'view_type'],
  prop_asset_prompt: ['entity_name', 'entity_setting', 'variant_setting', 'project_style_prompt', 'project_negative_prompt', 'type_prompt', 'type_negative_prompt', 'reference_summary', 'view_type'],
  subject_match: ['prompt_card', 'entity_catalog'],
  prompt_split: ['script', 'entity_catalog', 'max_duration_seconds', 'expected_total_duration_seconds'],
  video_generate: ['script_excerpt', 'entity_catalog', 'max_duration_seconds', 'neighbor_context'],
  prompt_rerun: ['script_excerpt', 'entity_catalog', 'max_duration_seconds', 'target_card', 'generated_context'],
  video_agent: ['segment', 'prompt'],
  workflow_agent: ['user_request', 'project_context', 'current_view', 'active_context', 'command_catalog'],
};

const projectStyleAwareCategories = new Set([
  'split_planning',
  'script_convert',
  'entity_extract',
  'entity_consolidate',
  'entity_setting',
  'character_asset_prompt',
  'scene_asset_prompt',
  'prop_asset_prompt',
  'subject_match',
  'prompt_split',
  'video_generate',
  'prompt_rerun',
  'video_agent',
  'workflow_agent',
]);

const emptyDraft = {
  id: '',
  name: '',
  category: 'script_convert',
  template: '',
  is_default: false,
};

function templateKindLabel(template) {
  if (String(template?.id || '').startsWith('tpl_example_')) return '示例';
  return template?.is_default ? '默认' : '自定义';
}

function extractVariables(template) {
  const normalized = normalizeLegacyPlaceholders(template || '');
  const variables = new Set();
  const pattern = /\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})/g;
  let match = pattern.exec(normalized);
  while (match) {
    variables.add(match[1] || match[2]);
    match = pattern.exec(normalized);
  }
  return [...variables].sort();
}

function normalizeLegacyPlaceholders(template) {
  return String(template || '').replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (match, name, offset, source) =>
    source[offset - 1] === '$' ? match : `$${name}`,
  );
}

export default function PromptsView({
  templates,
  selectedTemplateId,
  promptCategory,
  busy,
  setSelectedTemplateId,
  setPromptCategory,
  savePromptTemplate,
  deletePromptTemplate,
  loadPromptTemplateVersions,
  restorePromptTemplateVersion,
}) {
  const category = promptCategory || 'script_convert';
  const [draft, setDraft] = useState(emptyDraft);
  const [versions, setVersions] = useState([]);
  const [restoreVersion, setRestoreVersion] = useState('');
  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedTemplateId) || null,
    [templates, selectedTemplateId],
  );
  const filteredTemplates = templates.filter((template) => template.category === category);
  const derivedVariables = useMemo(() => extractVariables(draft.template), [draft.template]);
  const requiredVariables = requiredVariablesByCategory[draft.category] || [];
  const optionalVariables = projectStyleAwareCategories.has(draft.category)
    && !requiredVariables.includes('project_style_prompt')
    ? ['project_style_prompt']
    : [];
  const missingRequired = requiredVariables.filter((name) => !derivedVariables.includes(name));
  const explainedVariables = useMemo(() => {
    const names = new Set([...derivedVariables, ...requiredVariables, ...optionalVariables]);
    return [...names].sort();
  }, [derivedVariables, requiredVariables, optionalVariables]);
  const categoryLabel = promptCategories.find((item) => item.id === category)?.label || category;
  const draftIsExample = String(draft.id || '').startsWith('tpl_example_');
  const canDelete = Boolean(draft.id && !draft.is_default && !draftIsExample);
  const canRestore = Boolean(draft.id && restoreVersion && Number(restoreVersion) !== Number(draft.version || 1));
  const canSave = !draftIsExample && missingRequired.length === 0;

  useEffect(() => {
    if (!selectedTemplate) {
      setDraft({ ...emptyDraft, category });
      return;
    }
    setPromptCategory(selectedTemplate.category);
    setDraft({
      id: selectedTemplate.id,
      name: selectedTemplate.name,
      category: selectedTemplate.category,
      template: selectedTemplate.template || '',
      is_default: Boolean(selectedTemplate.is_default),
      version: Number(selectedTemplate.version || 1),
    });
  }, [category, selectedTemplate, setPromptCategory]);

  useEffect(() => {
    let active = true;
    if (!selectedTemplate?.id) {
      setVersions([]);
      setRestoreVersion('');
      return undefined;
    }
    loadPromptTemplateVersions(selectedTemplate.id)
      .then((items) => {
        if (!active) return;
        setVersions(items);
        const previous = items.find((item) => Number(item.version) !== Number(selectedTemplate.version || 1));
        setRestoreVersion(previous ? String(previous.version) : '');
      })
      .catch(() => {
        if (active) setVersions([]);
      });
    return () => {
      active = false;
    };
  }, [loadPromptTemplateVersions, selectedTemplate?.id, selectedTemplate?.version]);

  function selectCategory(nextCategory) {
    setPromptCategory(nextCategory);
    setSelectedTemplateId('');
    setDraft({ ...emptyDraft, category: nextCategory });
  }

  function startNewTemplate() {
    setSelectedTemplateId('');
    setDraft({ ...emptyDraft, category });
  }

  function duplicateTemplate() {
    if (!selectedTemplate) return;
    setSelectedTemplateId('');
    setDraft({
      id: '',
      name: `${selectedTemplate.name} 副本`,
      category: selectedTemplate.category,
      template: selectedTemplate.template || '',
      is_default: false,
    });
  }

  function appendMissingVariables() {
    if (!missingRequired.length) return;
    const suffix = missingRequired.map((name) => `$${name}`).join('\n');
    setDraft((prev) => ({
      ...prev,
      template: `${prev.template.trim()}\n\n${suffix}`.trim(),
    }));
  }

  function submitDraft(event) {
    event.preventDefault();
    const normalizedTemplate = normalizeLegacyPlaceholders(draft.template);
    const variables = extractVariables(normalizedTemplate);
    const payload = {
      name: draft.name.trim(),
      category: draft.category,
      template: normalizedTemplate,
      variables,
    };
    savePromptTemplate(draft.id, payload);
  }

  return (
    <div className="work-grid prompt-library-grid">
      <section className="panel prompt-category-panel">
        <PanelTitle icon={WandSparkles} title="提示词分类">
          <button type="button" onClick={startNewTemplate}>
            <Plus />
            新建
          </button>
        </PanelTitle>
        <div className="prompt-category-list">
          {promptCategories.map((item) => (
            <button
              type="button"
              key={item.id}
              className={item.id === category ? 'prompt-category active' : 'prompt-category'}
              onClick={() => selectCategory(item.id)}
            >
              <span>{item.label}</span>
              <small>{templates.filter((template) => template.category === item.id).length}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="panel prompt-template-list-panel">
        <PanelTitle icon={FileText} title={categoryLabel} />
        <div className="template-list">
          {filteredTemplates.length === 0 && <Empty text="暂无提示词预设" />}
          {filteredTemplates.map((template) => (
            <button
              type="button"
              className={selectedTemplateId === template.id ? 'template-row selected' : 'template-row'}
              key={template.id}
              onClick={() => setSelectedTemplateId(template.id)}
            >
              <strong>{template.name}</strong>
              <span>{templateKindLabel(template)}</span>
              <small>{(template.variables || []).join(' / ') || '无变量'}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="panel prompt-editor">
        <PanelTitle icon={FileText} title="预设编辑器">
          <button type="button" className="secondary" disabled={!selectedTemplate} onClick={duplicateTemplate}>
            <Copy />
            复制
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!canRestore || busy.has(`restorePromptTemplate:${draft.id}`)}
            onClick={() => selectedTemplate && restorePromptTemplateVersion(selectedTemplate, Number(restoreVersion))}
          >
            <RotateCcw />
            恢复
          </button>
          <button
            type="submit"
            form="prompt-template-form"
            disabled={busy.has('savePromptTemplate') || !canSave}
          >
            {busy.has('savePromptTemplate') ? <Save className="spin" /> : <Save />}
            保存
          </button>
          <button
            type="button"
            className="icon-button danger"
            disabled={!canDelete || busy.has(`deletePromptTemplate:${draft.id}`)}
            title="删除预设"
            onClick={() => selectedTemplate && deletePromptTemplate(selectedTemplate)}
          >
            <Trash2 />
          </button>
        </PanelTitle>
        <form id="prompt-template-form" className="prompt-template-editor" onSubmit={submitDraft}>
          <div className="settings-row">
            <label>
              名称
              <input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required />
            </label>
            <label>
              分类
              <select value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>
                {promptCategories.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="template-editor-meta">
            <div className="template-version-control">
              <strong>版本</strong>
              <div>
                <span>当前 v{draft.version || 1}</span>
                <select value={restoreVersion} onChange={(event) => setRestoreVersion(event.target.value)}>
                  <option value="">无历史版本</option>
                  {versions.map((item) => (
                    <option value={item.version} key={item.id}>
                      v{item.version} · {new Date(item.created_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <strong>变量</strong>
              <div className="variable-chip-list">
                {derivedVariables.length === 0 && <span className="variable-chip muted">无变量</span>}
                {derivedVariables.map((name) => (
                  <span className="variable-chip" key={name} title={describePromptVariable(name)}>
                    ${name}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <strong>必需</strong>
              <div className="variable-chip-list">
                {requiredVariables.map((name) => (
                  <span
                    className={missingRequired.includes(name) ? 'variable-chip missing' : 'variable-chip'}
                    key={name}
                    title={describePromptVariable(name)}
                  >
                    ${name}
                  </span>
                ))}
              </div>
            </div>
            {optionalVariables.length > 0 && <div>
              <strong>可选约束</strong>
              <div className="variable-chip-list">
                {optionalVariables.map((name) => (
                  <span className="variable-chip optional" key={name} title={describePromptVariable(name)}>
                    ${name}
                  </span>
                ))}
              </div>
            </div>}
          </div>
          {explainedVariables.length > 0 && (
            <div className="variable-explainer-list" aria-label="变量说明">
              <strong className="variable-explainer-title">变量说明</strong>
              {explainedVariables.map((name) => (
                <div className="variable-explainer-item" key={name}>
                  <code className="variable-explainer-name">${name}</code>
                  <p className="variable-explainer-text">{describePromptVariable(name)}</p>
                </div>
              ))}
            </div>
          )}
          {missingRequired.length > 0 && (
            <div className="template-warning">
              <span>缺少 {missingRequired.map((name) => `$${name}`).join(' / ')}</span>
              <button type="button" className="secondary" onClick={appendMissingVariables}>
                补齐
              </button>
            </div>
          )}
          <textarea
            value={draft.template}
            onChange={(event) => setDraft({ ...draft, template: event.target.value })}
            spellCheck="false"
            required
          />
        </form>
      </section>
    </div>
  );
}
