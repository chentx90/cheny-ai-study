import React, { useMemo } from 'react';
import { Check, Loader2, Plus, Save, X } from 'lucide-react';
import { typeLabel } from '../../utils';
import SubjectAssetThumb, { buildAssetUrl } from './SubjectAssetThumb';

export default function MentionPickerOverlay({
  open,
  cardTitle = '',
  search,
  onSearchChange,
  entityCards = [],
  draftIds = [],
  onToggle,
  saving = false,
  onCancel,
  onSave,
  selectedProject,
  apiBase,
  assetByPath,
  cardAssetPaths,
  missingAsset,
}) {
  const draftIdSet = useMemo(() => new Set(draftIds), [draftIds]);
  const filteredCards = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return entityCards.filter((entityCard) => {
      if (!keyword) return true;
      return `${entityCard.entity_name || ''} ${entityCard.state || ''} ${(entityCard.tags || []).join(' ')}`
        .toLowerCase()
        .includes(keyword);
    });
  }, [entityCards, search]);

  if (!open) return null;

  return (
    <div className="modal-backdrop mention-picker-backdrop" role="presentation" onClick={onCancel}>
      <section
        className="mention-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mention-picker-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <h3 id="mention-picker-title">手动添加引用</h3>
            {cardTitle ? <p>{cardTitle}</p> : null}
          </div>
          <button type="button" className="icon-button secondary" title="关闭" onClick={onCancel}>
            <X />
          </button>
        </header>

        <div className="mention-picker-dialog-body">
          <input
            value={search}
            onChange={(event) => onSearchChange?.(event.target.value)}
            placeholder="筛选实体卡"
            aria-label="筛选实体卡"
          />
          <div className="mention-picker-dialog-list">
            {filteredCards.length === 0 && <span className="empty-inline">暂无可选主体</span>}
            {filteredCards.map((entityCard) => {
              const paths = cardAssetPaths(entityCard);
              const firstAsset = paths.map((path) => assetByPath.get(path) || missingAsset(path))[0];
              const selected = draftIdSet.has(entityCard.id);
              return (
                <button
                  type="button"
                  key={entityCard.id}
                  className={selected ? 'mention-picker-dialog-option selected' : 'mention-picker-dialog-option'}
                  onClick={() => onToggle?.(entityCard.id)}
                >
                  <span className="mention-picker-dialog-thumb">
                    {firstAsset ? (
                      <SubjectAssetThumb asset={firstAsset} url={buildAssetUrl(apiBase, selectedProject, firstAsset)} />
                    ) : (
                      <span>无素材</span>
                    )}
                  </span>
                  <span className="mention-picker-dialog-meta">
                    <strong>{entityCard.entity_name || '未命名主体'}</strong>
                    <em>
                      {typeLabel(entityCard.type)}
                      {entityCard.state ? ` · ${entityCard.state}` : ''}
                    </em>
                  </span>
                  <span className="mention-picker-dialog-action">{selected ? <Check /> : <Plus />}</span>
                </button>
              );
            })}
          </div>
        </div>

        <footer>
          <button type="button" className="secondary" disabled={saving} onClick={onCancel}>
            取消
          </button>
          <button type="button" disabled={saving} onClick={onSave}>
            {saving ? <Loader2 className="spin" /> : <Save />}
            保存退出
          </button>
        </footer>
      </section>
    </div>
  );
}
