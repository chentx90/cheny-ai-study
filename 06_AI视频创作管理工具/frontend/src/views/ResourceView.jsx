import React, { useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Database,
  Download,
  Edit3,
  ImageIcon,
  Loader2,
  Plus,
  Save,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import Empty from '../components/Empty';
import PanelTitle from '../components/PanelTitle';
import { assetTypeLabel, typeLabel } from '../utils';
import { downloadRemoteFile } from '../utils/download';
import ProjectAssetPanel from './resources/ProjectAssetPanel';
import { AssetPreview, assetUploadAccept, buildAssetUrl, formatAssetSize } from './resources/resourceMedia';

const entityTypeColumns = [
  { type: 'character', label: '人物' },
  { type: 'scene', label: '场景' },
  { type: 'prop', label: '物品' },
];

function entityKey(type, entityName) {
  return `${type}:${(entityName || '').trim().toLowerCase()}`;
}

function stateTitle(card) {
  const entityName = card.entity_name || '未命名实体';
  const state = (card.state || '').trim();
  return `【${entityName}${state ? `·${state}` : ''}】`;
}

export default function ResourceView({
  entityCards,
  entityMaterials,
  assets,
  cardDraft,
  editingCardId,
  selectedProject,
  apiBase,
  apiConfig = {},
  busy,
  setCardDraft,
  createEntityCard,
  editEntityCard,
  cancelEntityCardEdit,
  deleteEntityCard,
  uploadProjectAssets,
  renameAsset,
  addEntityMaterials,
  uploadEntityMaterialFiles,
  deleteEntityMaterial,
  deleteEntityMaterialPool,
  deleteAsset,
  mode = 'cards',
}) {
  const [assetFilter, setAssetFilter] = useState('all');
  const [assetSearch, setAssetSearch] = useState('');
  const [previewAsset, setPreviewAsset] = useState(null);
  const [renameTargetPath, setRenameTargetPath] = useState('');
  const [renameDraft, setRenameDraft] = useState('');
  const [materialPicker, setMaterialPicker] = useState({});
  const [materialPickerOpen, setMaterialPickerOpen] = useState({});
  const [materialPickerSearch, setMaterialPickerSearch] = useState({});
  const [expandedGroups, setExpandedGroups] = useState(() => new Set());
  const [entityEditorOpen, setEntityEditorOpen] = useState(false);
  const [entityNameLocked, setEntityNameLocked] = useState(false);
  const [editorPoolSearch, setEditorPoolSearch] = useState('');
  const [downloadingPath, setDownloadingPath] = useState('');
  const uploadBusy = busy.has('uploadProjectAssets');

  const assetByPath = useMemo(() => new Map(assets.map((asset) => [asset.path, asset])), [assets]);

  const filteredAssets = useMemo(() => {
    const keyword = assetSearch.trim().toLowerCase();
    return assets.filter((asset) => {
      const typeMatched = assetFilter === 'all' || asset.asset_type === assetFilter;
      const nameMatched = !keyword || `${asset.filename} ${asset.path}`.toLowerCase().includes(keyword);
      return typeMatched && nameMatched;
    });
  }, [assetFilter, assetSearch, assets]);

  const entityColumns = useMemo(() => {
    const maps = entityTypeColumns.reduce((result, column) => ({ ...result, [column.type]: new Map() }), {});

    function ensureGroup(type, entityName) {
      const columnType = entityTypeColumns.some((column) => column.type === type) ? type : 'prop';
      const cleanName = (entityName || '未命名实体').trim() || '未命名实体';
      const key = entityKey(columnType, cleanName);
      if (!maps[columnType].has(key)) {
        maps[columnType].set(key, { key, type: columnType, entityName: cleanName, cards: [], materials: [] });
      }
      return maps[columnType].get(key);
    }

    entityCards.forEach((card) => ensureGroup(card.type, card.entity_name).cards.push(card));
    entityMaterials.forEach((material) => ensureGroup(material.type, material.entity_name).materials.push(material));

    return entityTypeColumns.map((column) => ({
      ...column,
      groups: Array.from(maps[column.type].values())
        .map((group) => {
          const cards = [...group.cards].sort((a, b) => (a.state || '').localeCompare(b.state || '') || a.id.localeCompare(b.id));
          const materials = [...group.materials].sort((a, b) => a.created_at.localeCompare(b.created_at));
          const materialPaths = Array.from(new Set(materials.map((material) => material.asset_path)));
          return {
            ...group,
            cards,
            materials,
            materialPaths,
            tags: Array.from(new Set(cards.flatMap((card) => card.tags || []))),
          };
        })
        .sort((a, b) => a.entityName.localeCompare(b.entityName)),
    }));
  }, [entityCards, entityMaterials]);

  const editorMaterialPool = useMemo(() => {
    const entityName = (cardDraft.entity_name || '').trim();
    if (!entityName) return [];
    const column = entityColumns.find((item) => item.type === cardDraft.type);
    const group = column?.groups.find((item) => item.entityName === entityName);
    return group?.materialPaths || [];
  }, [cardDraft.entity_name, cardDraft.type, entityColumns]);

  const editorPickFromPool = Boolean(entityNameLocked || editingCardId);

  const editorAssetCandidates = useMemo(() => {
    const keyword = editorPoolSearch.trim().toLowerCase();
    const sourceAssets = editorPickFromPool
      ? editorMaterialPool.map((path) => assetByPath.get(path)).filter(Boolean)
      : assets;
    return sourceAssets.filter((asset) => {
      const matched = !keyword || `${asset.filename} ${asset.path}`.toLowerCase().includes(keyword);
      return matched;
    });
  }, [assetByPath, assets, editorMaterialPool, editorPickFromPool, editorPoolSearch]);

  useEffect(() => {
    if (!previewAsset) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setPreviewAsset(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewAsset]);

  useEffect(() => {
    if (previewAsset && !assets.some((asset) => asset.path === previewAsset.path)) {
      setPreviewAsset(null);
    }
  }, [assets, previewAsset]);

  function handleProjectAssetUpload(event) {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) uploadProjectAssets(files);
    event.target.value = '';
  }

  function toggleEntityGroup(groupKey) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) {
        next.delete(groupKey);
      } else {
        next.add(groupKey);
      }
      return next;
    });
  }

  function cardAssetPaths(card) {
    return Array.from(new Set([...(card.assets || []), ...(card.reference_images || []), ...(card.audio_samples || []), ...(card.video_clips || [])]));
  }

  function beginRename(asset) {
    setRenameTargetPath(asset.path);
    setRenameDraft(asset.filename);
  }

  async function submitRename(asset) {
    const renamed = await renameAsset(asset, renameDraft);
    if (renamed) {
      setRenameTargetPath('');
      setRenameDraft('');
    }
  }

  function toggleMaterialPicker(groupKey) {
    setMaterialPickerOpen((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }));
  }

  function togglePickedMaterial(groupKey, path) {
    setMaterialPicker((prev) => {
      const selectedPaths = prev[groupKey] || [];
      return {
        ...prev,
        [groupKey]: selectedPaths.includes(path) ? selectedPaths.filter((item) => item !== path) : [...selectedPaths, path],
      };
    });
  }

  function addPickedMaterials(group) {
    const pickedPaths = materialPicker[group.key] || [];
    if (pickedPaths.length === 0) return;
    addEntityMaterials({ entityName: group.entityName, type: group.type, assetPaths: pickedPaths });
    setMaterialPicker((prev) => ({ ...prev, [group.key]: [] }));
    setMaterialPickerOpen((prev) => ({ ...prev, [group.key]: false }));
    setMaterialPickerSearch((prev) => ({ ...prev, [group.key]: '' }));
  }

  function uploadMaterialsForGroup(group, event) {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) uploadEntityMaterialFiles({ entityName: group.entityName, type: group.type, files });
    event.target.value = '';
  }

  function openAddMaterials(group) {
    setExpandedGroups((prev) => new Set(prev).add(group.key));
    setMaterialPickerOpen((prev) => ({ ...prev, [group.key]: true }));
  }

  function removeCardAsset(path) {
    setCardDraft((prev) => ({
      ...prev,
      existingAssets: (prev.existingAssets || []).filter((item) => item !== path),
    }));
  }

  function toggleEditorPoolAsset(path) {
    setCardDraft((prev) => {
      const current = prev.existingAssets || [];
      return {
        ...prev,
        existingAssets: current.includes(path) ? current.filter((item) => item !== path) : [...current, path],
      };
    });
  }

  function openCreateEntityEditor(column) {
    cancelEntityCardEdit();
    setEntityNameLocked(false);
    setEditorPoolSearch('');
    setCardDraft({
      entity_name: '',
      type: column.type,
      state: '',
      tags: '',
      existingAssets: [],
    });
    setEntityEditorOpen(true);
  }

  function openCreateStateCard(group) {
    cancelEntityCardEdit();
    setEntityNameLocked(true);
    setEditorPoolSearch('');
    setExpandedGroups((prev) => new Set(prev).add(group.key));
    setCardDraft({
      entity_name: group.entityName,
      type: group.type,
      state: '',
      tags: '',
      existingAssets: [],
    });
    setEntityEditorOpen(true);
  }

  function openEditEntityEditor(card) {
    setEntityNameLocked(false);
    setEditorPoolSearch('');
    editEntityCard(card);
    setEntityEditorOpen(true);
  }

  function closeEntityEditor() {
    setEntityEditorOpen(false);
    setEntityNameLocked(false);
    setEditorPoolSearch('');
    cancelEntityCardEdit();
  }

  async function submitEntityEditor(event) {
    const saved = await createEntityCard(event);
    if (saved) {
      setEntityEditorOpen(false);
    }
  }

  async function handleDownloadAsset(asset) {
    if (!asset?.path || downloadingPath) return;
    const url = buildAssetUrl(apiBase, selectedProject, asset);
    setDownloadingPath(asset.path);
    try {
      await downloadRemoteFile(url, asset.filename || asset.path);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '下载失败');
    } finally {
      setDownloadingPath('');
    }
  }

  function renderEntityCardRow(card, compact = false) {
    const paths = cardAssetPaths(card);
    return (
      <article className={`entity-state-row ${compact ? 'is-compact' : ''}`} key={card.id}>
        <div className="entity-state-main">
          <strong>{stateTitle(card)}</strong>
          <small>{paths.length} 个素材</small>
        </div>
        {!compact && (
          <div className="entity-state-thumbs">
            {paths.slice(0, 5).map((path) => {
              const asset = assetByPath.get(path);
              return (
                <button
                  type="button"
                  className="entity-state-thumb"
                  key={path}
                  disabled={!asset}
                  title={asset?.filename || path}
                  onClick={() => asset && setPreviewAsset(asset)}
                >
                  {asset ? <AssetPreview asset={asset} url={buildAssetUrl(apiBase, selectedProject, asset)} /> : <span>?</span>}
                </button>
              );
            })}
            {paths.length > 5 && <span className="entity-state-more">+{paths.length - 5}</span>}
          </div>
        )}
        <div className="row-actions">
          <button type="button" className="icon-button secondary" title="编辑实体卡" onClick={() => openEditEntityEditor(card)}>
            <Edit3 />
          </button>
          <button type="button" className="icon-button danger" title="删除实体卡" onClick={() => deleteEntityCard(card)}>
            <Trash2 />
          </button>
        </div>
      </article>
    );
  }

  const previewUrl = previewAsset ? buildAssetUrl(apiBase, selectedProject, previewAsset) : '';
  const editorTitle = editingCardId
    ? '编辑实体卡'
    : entityNameLocked && cardDraft.entity_name?.trim()
      ? `添加${typeLabel(cardDraft.type)}状态卡 · ${cardDraft.entity_name.trim()}`
      : `新建${typeLabel(cardDraft.type)}实体`;

  return (
    <>
      <div className="work-grid resource-grid">
        {mode === 'cards' && (
        <section className="panel entity-library-panel">
          <PanelTitle icon={Database} title="实体卡库" />
          <div className="entity-card-columns">
            {entityColumns.map((column) => (
              <div className="entity-card-column" key={column.type}>
                <div className="entity-card-column-title">
                  <strong>{column.label}</strong>
                  <div className="entity-column-actions">
                    <span>{column.groups.length}</span>
                    <button type="button" className="icon-button secondary" title={`新建${column.label}实体`} onClick={() => openCreateEntityEditor(column)}>
                      <Plus />
                    </button>
                  </div>
                </div>
                {column.groups.length === 0 && <Empty text={`暂无${column.label}实体`} />}
                {column.groups.map((group) => {
                  const isExpanded = expandedGroups.has(group.key);
                  const pickedMaterialPaths = materialPicker[group.key] || [];
                  const materialKeyword = (materialPickerSearch[group.key] || '').trim().toLowerCase();
                  const materialCandidates = assets.filter((asset) => {
                    const alreadyAdded = group.materialPaths.includes(asset.path);
                    const matched = !materialKeyword || `${asset.filename} ${asset.path}`.toLowerCase().includes(materialKeyword);
                    return !alreadyAdded && matched;
                  });
                  return (
                    <article className={`entity-card-group ${isExpanded ? 'is-expanded' : 'is-collapsed'}`} key={group.key}>
                      <div className="entity-card-group-heading">
                        <button type="button" className="entity-card-group-toggle" aria-expanded={isExpanded} onClick={() => toggleEntityGroup(group.key)}>
                          {isExpanded ? <ChevronDown /> : <ChevronRight />}
                          <strong>{group.entityName}</strong>
                        </button>
                        <div className="entity-card-group-side">
                          <span className="entity-card-group-count">
                            {group.cards.length} 卡 / {group.materials.length} 素材
                          </span>
                          <div className="entity-card-group-actions">
                            <button
                              type="button"
                              className="icon-button secondary"
                              title="添加状态卡（从小素材库选素材）"
                              onClick={() => openCreateStateCard(group)}
                            >
                              <Plus />
                            </button>
                            <button
                              type="button"
                              className="icon-button danger"
                              title="清空素材库"
                              disabled={group.materials.length === 0}
                              onClick={() =>
                                deleteEntityMaterialPool({
                                  entityName: group.entityName,
                                  type: group.type,
                                  materials: group.materials,
                                })
                              }
                            >
                              <Trash2 />
                            </button>
                          </div>
                        </div>
                      </div>
                      {isExpanded ? (
                        <>
                          <div className="entity-material-library">
                            <div className="entity-material-title">
                              <span>素材库</span>
                              <div className="entity-section-actions">
                                <small>{group.materials.length} 个</small>
                                <button
                                  type="button"
                                  className="icon-button danger"
                                  title="清空素材库"
                                  disabled={group.materials.length === 0}
                                  onClick={() =>
                                    deleteEntityMaterialPool({
                                      entityName: group.entityName,
                                      type: group.type,
                                      materials: group.materials,
                                    })
                                  }
                                >
                                  <Trash2 />
                                </button>
                              </div>
                            </div>
                            <div className="entity-material-list">
                              {group.materials.length === 0 && <span className="empty-inline">暂无实体素材</span>}
                              {group.materials.map((material) => {
                                const asset = assetByPath.get(material.asset_path);
                                return (
                                  <article className="entity-material-card" key={material.id}>
                                    <button
                                      type="button"
                                      className="entity-material-preview"
                                      disabled={!asset}
                                      title={asset ? '查看素材' : '素材缺失'}
                                      onClick={() => asset && setPreviewAsset(asset)}
                                    >
                                      {asset ? <AssetPreview asset={asset} url={buildAssetUrl(apiBase, selectedProject, asset)} /> : <span>缺失</span>}
                                    </button>
                                    <div className="entity-material-meta">
                                      <strong>{asset?.filename || material.asset_path}</strong>
                                      <em>{asset ? assetTypeLabel(asset.asset_type) : '缺失'}</em>
                                    </div>
                                    <button
                                      type="button"
                                      title="下载素材"
                                      disabled={!asset || downloadingPath === asset?.path}
                                      onClick={() => asset && handleDownloadAsset(asset)}
                                    >
                                      {downloadingPath === asset?.path ? <Loader2 className="spin" /> : <Download />}
                                    </button>
                                    <button type="button" title="移除实体素材" onClick={() => deleteEntityMaterial(material)}>
                                      <X />
                                    </button>
                                  </article>
                                );
                              })}
                            </div>
                            <div className="entity-material-actions">
                              <button
                                type="button"
                                className="secondary"
                                disabled={assets.length === group.materialPaths.length}
                                onClick={() => toggleMaterialPicker(group.key)}
                              >
                                <ImageIcon />
                                选择项目素材
                              </button>
                              <label className="upload-control compact">
                                <Upload />
                                本地
                                <input type="file" accept={assetUploadAccept} multiple onChange={(event) => uploadMaterialsForGroup(group, event)} />
                              </label>
                            </div>
                            {materialPickerOpen[group.key] && (
                              <div className="project-asset-picker entity-material-picker">
                                <div className="project-asset-picker-toolbar">
                                  <input
                                    value={materialPickerSearch[group.key] || ''}
                                    onChange={(event) => setMaterialPickerSearch((prev) => ({ ...prev, [group.key]: event.target.value }))}
                                    placeholder="筛选项目素材"
                                  />
                                  <span>{pickedMaterialPaths.length} 已选</span>
                                  <button type="button" disabled={pickedMaterialPaths.length === 0} onClick={() => addPickedMaterials(group)}>
                                    <Plus />
                                    加入素材库
                                  </button>
                                </div>
                                <div className="project-asset-picker-grid">
                                  {materialCandidates.length === 0 && <span className="empty-inline">暂无可选素材</span>}
                                  {materialCandidates.map((asset) => {
                                    const selected = pickedMaterialPaths.includes(asset.path);
                                    return (
                                      <button
                                        type="button"
                                        className={`project-asset-option ${selected ? 'selected' : ''}`}
                                        key={asset.path}
                                        title={asset.filename}
                                        onClick={() => togglePickedMaterial(group.key, asset.path)}
                                      >
                                        <span className="project-asset-option-preview">
                                          <AssetPreview asset={asset} url={buildAssetUrl(apiBase, selectedProject, asset)} />
                                        </span>
                                        <strong>{asset.filename}</strong>
                                        <em>
                                          {assetTypeLabel(asset.asset_type)} · {formatAssetSize(asset.bytes)}
                                        </em>
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                          <div className="entity-state-list">
                            <div className="entity-state-list-head">
                              <span>状态卡片</span>
                              <button type="button" className="secondary entity-state-add-button" onClick={() => openCreateStateCard(group)}>
                                <Plus />
                                添加状态卡
                              </button>
                            </div>
                            {group.cards.length === 0 && (
                              <span className="empty-inline">暂无状态卡片，可基于素材库为不同造型/状态单独建卡</span>
                            )}
                            {group.cards.map((card) => renderEntityCardRow(card))}
                          </div>
                          {group.tags.length > 0 && <small className="entity-card-tags">{group.tags.join(' / ')}</small>}
                        </>
                      ) : (
                        <div className="entity-card-compact-list">
                          {group.cards.length === 0 && <span className="empty-inline">暂无实体卡片</span>}
                          {group.cards.map((card) => renderEntityCardRow(card, true))}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            ))}
          </div>
        </section>
        )}
        {mode === 'assets' && (
        <ProjectAssetPanel
          assets={assets}
          filteredAssets={filteredAssets}
          assetFilter={assetFilter}
          setAssetFilter={setAssetFilter}
          assetSearch={assetSearch}
          setAssetSearch={setAssetSearch}
          uploadBusy={uploadBusy}
          handleProjectAssetUpload={handleProjectAssetUpload}
          apiBase={apiBase}
          selectedProject={selectedProject}
          setPreviewAsset={setPreviewAsset}
          renameTargetPath={renameTargetPath}
          renameDraft={renameDraft}
          setRenameDraft={setRenameDraft}
          setRenameTargetPath={setRenameTargetPath}
          submitRename={submitRename}
          beginRename={beginRename}
          busy={busy}
          downloadingPath={downloadingPath}
          handleDownloadAsset={handleDownloadAsset}
          deleteAsset={deleteAsset}
        />
        )}
      </div>
      {entityEditorOpen && (
        <div
          className="modal-backdrop entity-editor-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={editorTitle}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeEntityEditor();
          }}
        >
          <form className="entity-editor-dialog" onSubmit={submitEntityEditor}>
            <header>
              <h3>{editorTitle}</h3>
              <button type="button" className="icon-button secondary" title="关闭" onClick={closeEntityEditor}>
                <X />
              </button>
            </header>
            <div className="entity-editor-body">
              <div className="entity-editor-fields entity-editor-fields-compact">
                <input
                  value={cardDraft.entity_name}
                  onChange={(event) => setCardDraft({ ...cardDraft, entity_name: event.target.value })}
                  placeholder="实体名称"
                  required
                  readOnly={entityNameLocked}
                  autoFocus={!entityNameLocked}
                />
                <input
                  value={cardDraft.state}
                  onChange={(event) => setCardDraft({ ...cardDraft, state: event.target.value })}
                  placeholder="状态，如：宫女装"
                  autoFocus={entityNameLocked}
                />
              </div>
              {(cardDraft.existingAssets || []).length > 0 && (
                <div className="selected-asset-grid">
                  {cardDraft.existingAssets.map((path) => {
                    const asset = assetByPath.get(path);
                    return (
                      <article className="selected-asset-card" key={path}>
                        <button
                          type="button"
                          className="selected-asset-preview"
                          disabled={!asset}
                          title={asset ? '查看素材' : '素材缺失'}
                          onClick={() => asset && setPreviewAsset(asset)}
                        >
                          {asset ? <AssetPreview asset={asset} url={buildAssetUrl(apiBase, selectedProject, asset)} /> : <span>缺失</span>}
                        </button>
                        <div>
                          <strong>{asset?.filename || path}</strong>
                          <em>{asset ? assetTypeLabel(asset.asset_type) : '素材'}</em>
                        </div>
                        <button type="button" title="移除" onClick={() => removeCardAsset(path)}>
                          <X />
                        </button>
                      </article>
                    );
                  })}
                </div>
              )}
              <div className="entity-editor-asset-actions">
                <strong className="entity-editor-asset-label">
                  {editorPickFromPool ? '从小素材库选择' : '从项目素材选择'}
                </strong>
                <span>{(cardDraft.existingAssets || []).length} 已选</span>
              </div>
              <div className="project-asset-picker entity-editor-asset-picker">
                <div className="project-asset-picker-toolbar">
                  <input
                    value={editorPoolSearch}
                    onChange={(event) => setEditorPoolSearch(event.target.value)}
                    placeholder={editorPickFromPool ? '筛选小素材库' : '筛选项目素材'}
                  />
                </div>
                <div className="project-asset-picker-grid">
                  {editorPickFromPool && editorMaterialPool.length === 0 && (
                    <span className="empty-inline">小素材库为空，请先在实体「素材库」里添加素材</span>
                  )}
                  {!editorPickFromPool && assets.length === 0 && (
                    <span className="empty-inline">暂无项目素材，请先在下方「项目素材」导入</span>
                  )}
                  {(editorPickFromPool ? editorMaterialPool.length > 0 : assets.length > 0) &&
                    editorAssetCandidates.length === 0 && <span className="empty-inline">无匹配素材</span>}
                  {editorAssetCandidates.map((asset) => {
                    const selected = (cardDraft.existingAssets || []).includes(asset.path);
                    return (
                      <button
                        type="button"
                        className={`project-asset-option ${selected ? 'selected' : ''}`}
                        key={asset.path}
                        title={asset.filename}
                        onClick={() => toggleEditorPoolAsset(asset.path)}
                      >
                        <span className="project-asset-option-preview">
                          <AssetPreview asset={asset} url={buildAssetUrl(apiBase, selectedProject, asset)} />
                        </span>
                        <strong>{asset.filename}</strong>
                        <em>
                          {assetTypeLabel(asset.asset_type)} · {formatAssetSize(asset.bytes)}
                        </em>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <footer>
              <button type="button" className="secondary" onClick={closeEntityEditor}>
                取消
              </button>
              <button type="submit" disabled={busy.has('createEntityCard')}>
                {busy.has('createEntityCard') ? <Loader2 className="spin" /> : <Save />}
                {editingCardId ? '保存实体卡' : entityNameLocked ? '添加状态卡' : '新建实体'}
              </button>
            </footer>
          </form>
        </div>
      )}
      {previewAsset && (
        <div
          className="asset-preview-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={`${previewAsset.filename} 预览`}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPreviewAsset(null);
          }}
        >
          <div className="asset-preview-modal">
            <button type="button" className="icon-button secondary asset-preview-close" title="关闭预览" onClick={() => setPreviewAsset(null)}>
              <X />
            </button>
            <div className="asset-preview-stage">
              <AssetPreview asset={previewAsset} url={previewUrl} large />
            </div>
            <div className="asset-preview-details">
              <strong>{previewAsset.filename}</strong>
              <span>
                {assetTypeLabel(previewAsset.asset_type)} · {formatAssetSize(previewAsset.bytes)}
              </span>
              <button
                type="button"
                className="secondary"
                disabled={downloadingPath === previewAsset.path}
                onClick={() => handleDownloadAsset(previewAsset)}
              >
                {downloadingPath === previewAsset.path ? <Loader2 className="spin" /> : <Download />}
                下载到本地
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
