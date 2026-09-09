import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Download,
  Film,
  Loader2,
  Lock,
  Plus,
  RotateCcw,
  Save,
  ScanSearch,
  Trash2,
  Unlock,
  WandSparkles,
} from 'lucide-react';
import Empty from '../../components/Empty';
import PanelTitle from '../../components/PanelTitle';
import { request } from '../../api/client';
import { promptCardMaxDurationSeconds } from '../../constants';
import { downloadTextFile, sanitizeFilename } from '../../utils/download';
import MentionTextarea from './MentionTextarea';
import MentionPickerOverlay from './MentionPickerOverlay';
import SubjectAssetThumb, { buildAssetUrl, missingAsset } from './SubjectAssetThumb';
import TotalDurationControl from './TotalDurationControl';
import {
  cardAssetPaths,
  clampPromptCardHeight,
  composeSegmentTitle,
  defaultPromptCardHeight,
  displaySegmentTitleBody,
  entityCardIdsFromAnchorText,
  entityCardsForAnchorText,
  formatSeconds,
  isPromptCardResizePointer,
  segmentOrder,
  sourceRangeLabel,
} from './videoViewUtils';

const PROMPT_VERSION_LABELS = {
  generated: '生成',
  rerun: '重跑',
  edited: '手工',
};

function versionTabLabel(version) {
  const type = PROMPT_VERSION_LABELS[version.version_type] || '版';
  return `${type}${version.version_index}`;
}

function versionTagLabel(version) {
  const type = PROMPT_VERSION_LABELS[version.version_type] || '版本';
  return `${type} v${version.version_index}`;
}

/**
 * Prompt card shell with per-card persisted height.
 * Uses a bottom-right custom drag handle only (no CSS resize) so the native grip
 * does not bleed into adjacent cards in the scroll list.
 */
function VideoPromptCard({ cardId, savedHeight, onHeightChange, className, onClick, children }) {
  const cardRef = useRef(null);
  const resizeSessionRef = useRef(null);
  const dragHeightRef = useRef(null);
  const [dragHeight, setDragHeight] = useState(null);
  const resolvedHeight = clampPromptCardHeight(savedHeight);
  const displayHeight = dragHeight ?? resolvedHeight;

  function beginResize(event) {
    const element = cardRef.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    if (!isPromptCardResizePointer(event.clientX, event.clientY, rect)) return;

    event.preventDefault();
    event.stopPropagation();

    const startHeight = rect.height;
    resizeSessionRef.current = { startY: event.clientY, startHeight };
    element.setAttribute('data-resizing', 'true');

    function applyResize(moveEvent) {
      const session = resizeSessionRef.current;
      if (!session) return;
      const next = clampPromptCardHeight(session.startHeight + (moveEvent.clientY - session.startY));
      if (!next) return;
      dragHeightRef.current = next;
      setDragHeight(next);
    }

    function stopResize() {
      resizeSessionRef.current = null;
      window.removeEventListener('pointermove', applyResize);
      window.removeEventListener('pointerup', stopResize);
      const active = cardRef.current;
      if (active) active.removeAttribute('data-resizing');
      const finalHeight = dragHeightRef.current;
      dragHeightRef.current = null;
      setDragHeight(null);
      if (finalHeight) onHeightChange?.(cardId, finalHeight);
    }

    window.addEventListener('pointermove', applyResize);
    window.addEventListener('pointerup', stopResize);
  }

  function updateResizeCursor(event) {
    const element = cardRef.current;
    if (!element || resizeSessionRef.current) return;
    const rect = element.getBoundingClientRect();
    element.style.cursor = isPromptCardResizePointer(event.clientX, event.clientY, rect) ? 'ns-resize' : '';
  }

  function clearResizeCursor() {
    const element = cardRef.current;
    if (element && !resizeSessionRef.current) element.style.cursor = '';
  }

  return (
    <article
      ref={cardRef}
      className={className}
      data-custom-height={displayHeight ? 'true' : undefined}
      style={displayHeight ? { height: `${displayHeight}px`, minHeight: `${displayHeight}px` } : undefined}
      onClick={onClick}
      onPointerDown={beginResize}
      onPointerMove={updateResizeCursor}
      onPointerLeave={clearResizeCursor}
    >
      {children}
    </article>
  );
}

function normalizeBackendMatch(match) {
  const card = match.entity_card || {};
  return {
    entityCard: card,
    assets: Array.isArray(match.assets) ? match.assets : [],
    reasons: Array.isArray(match.reasons) ? match.reasons : [],
  };
}

function normalizeLocalMatch(card, assetByPath) {
  const paths = cardAssetPaths(card);
  return {
    entityCard: card,
    assets: paths.map((path) => assetByPath.get(path) || missingAsset(path)),
    reasons: [],
  };
}

export default function PromptCardPanel({
  activeScript,
  sortedPromptCards,
  videoTemplates = [],
  selectedTemplateId = '',
  setSelectedTemplateId,
  expectedTotalDuration,
  setExpectedTotalDuration,
  activePromptCardId = '',
  setActivePromptCardId,
  busy,
  generatePromptCards,
  rerunPromptCard,
  togglePromptCardLock,
  matchPromptCardSubjects,
  updatePromptCardSubjects,
  cardValue,
  updateCardDraft,
  savePromptCard,
  deletePromptCard,
  saveCardBeforeVideo,
  entityCards = [],
  assets = [],
  selectedProject,
  apiBase,
  promptContentFontSize = 14,
  promptCardHeights = {},
  setPromptCardHeight,
}) {
  const [subjectMatches, setSubjectMatches] = useState({});
  const [mentionPickerCard, setMentionPickerCard] = useState(null);
  const [mentionPickerSearch, setMentionPickerSearch] = useState('');
  const [mentionPickerDraftIds, setMentionPickerDraftIds] = useState([]);
  const [mentionIdsByCard, setMentionIdsByCard] = useState({});
  const [versionsByCard, setVersionsByCard] = useState({});
  const [activeVersionByCard, setActiveVersionByCard] = useState({});
  const listRef = useRef(null);
  const assetByPath = useMemo(() => new Map(assets.map((asset) => [asset.path, asset])), [assets]);
  const imageAssetCount = useMemo(() => assets.filter((asset) => asset.asset_type === 'image').length, [assets]);

  useEffect(() => {
    const element = listRef.current;
    if (!element) return undefined;
    const updateDefaultHeight = () => {
      element.style.setProperty('--prompt-card-default-height', `${defaultPromptCardHeight(window.innerHeight)}px`);
    };
    updateDefaultHeight();
    window.addEventListener('resize', updateDefaultHeight);
    return () => window.removeEventListener('resize', updateDefaultHeight);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const entries = await Promise.all(
        sortedPromptCards.map(async (card) => {
          try {
            const data = await request(`/api/prompt-cards/${card.id}/versions`);
            return [card.id, data.versions || []];
          } catch {
            return [card.id, []];
          }
        }),
      );
      if (!cancelled) {
        setVersionsByCard(Object.fromEntries(entries));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sortedPromptCards]);

  function applyPromptVersion(card, version) {
    setActiveVersionByCard((prev) => ({ ...prev, [card.id]: version.id }));
    updateCardDraft(card, {
      prompt_text: version.prompt_text,
      anchor_text: version.anchor_text || '',
      title: version.title || card.title,
      status: version.version_type === 'edited' ? 'edited' : card.status,
    });
  }

  function resetPromptVersion(card) {
    setActiveVersionByCard((prev) => {
      const next = { ...prev };
      delete next[card.id];
      return next;
    });
    updateCardDraft(card, {
      prompt_text: card.prompt_text,
      anchor_text: card.anchor_text || '',
      title: card.title,
      status: card.status,
    });
  }

  function openMentionPicker(card, value, matchedSubjects) {
    const mentionIds = mentionIdsFor(card);
    const subjectIdsList = subjectIds(matchedSubjects);
    setMentionPickerCard({ card, value });
    setMentionPickerSearch('');
    setMentionPickerDraftIds([...new Set([...mentionIds, ...subjectIdsList])]);
  }

  function closeMentionPicker() {
    setMentionPickerCard(null);
    setMentionPickerSearch('');
    setMentionPickerDraftIds([]);
  }

  function toggleMentionPickerDraft(entityCardId) {
    setMentionPickerDraftIds((prev) =>
      prev.includes(entityCardId) ? prev.filter((id) => id !== entityCardId) : [...prev, entityCardId],
    );
  }

  async function saveMentionPicker() {
    if (!mentionPickerCard) return;
    const { card, value } = mentionPickerCard;
    const data = await saveSubjectSelection(value, mentionPickerDraftIds);
    if (data) {
      setMentionIdsByCard((prev) => ({ ...prev, [card.id]: [...mentionPickerDraftIds] }));
      closeMentionPicker();
    }
  }

  function mentionRefItems(entityCard) {
    const paths = cardAssetPaths(entityCard);
    return {
      entityCard,
      assets: paths.map((path) => assetByPath.get(path) || missingAsset(path)),
    };
  }

  function subjectCardsFor(card) {
    const cached = subjectMatches[card.id];
    if (cached) return cached.map(normalizeBackendMatch);
    if (card.status !== 'matched') return [];
    return entityCardsForAnchorText(card.anchor_text || '', entityCards).map((entityCard) => normalizeLocalMatch(entityCard, assetByPath));
  }

  async function runSubjectMatch(card) {
    const data = await matchPromptCardSubjects?.(card);
    if (data?.matches) {
      setSubjectMatches((prev) => ({ ...prev, [card.id]: data.matches }));
    }
  }

  async function saveSubjectSelection(card, entityCardIds, options = {}) {
    const data = await updatePromptCardSubjects?.(card, entityCardIds, options);
    if (data?.matches) {
      setSubjectMatches((prev) => ({ ...prev, [card.id]: data.matches }));
    }
    return data;
  }

  function subjectIds(matches) {
    return matches.map((match) => match.entityCard?.id).filter(Boolean);
  }

  function mentionIdsFor(card) {
    if (mentionIdsByCard[card.id]) return mentionIdsByCard[card.id];
    return entityCardIdsFromAnchorText(card.anchor_text);
  }

  function mentionedCardsFor(card) {
    const ids = mentionIdsFor(card);
    return entityCards.filter((entityCard) => ids.includes(entityCard.id));
  }

  function downloadPromptCard(value, order) {
    const projectPrefix = sanitizeFilename(selectedProject?.name || 'project', 'project');
    const titleBody = displaySegmentTitleBody(value.title, order);
    const filename = `${projectPrefix}-片段${order}-${sanitizeFilename(titleBody || '分镜', '分镜')}`;
    const sections = [
      value.prompt_text || '',
      value.anchor_text ? `\n\n--- 引用锚定 ---\n${value.anchor_text}` : '',
      value.source_text ? `\n\n--- 原文摘录 ---\n${value.source_text}` : '',
    ];
    downloadTextFile(sections.join(''), filename);
  }

  const mentionPickerSaving = mentionPickerCard
    ? busy.has(`updatePromptCardSubjects:${mentionPickerCard.card.id}`)
    : false;

  return (
    <article className="panel video-prompt-panel">
      <PanelTitle icon={WandSparkles} title="提示词卡片">
        <div className="prompt-panel-toolbar">
          <select
            className="prompt-template-select"
            value={videoTemplates.some((template) => template.id === selectedTemplateId) ? selectedTemplateId : ''}
            onChange={(event) => setSelectedTemplateId?.(event.target.value)}
            aria-label="视频生成提示词预设"
          >
            <option value="">默认视频提示词预设</option>
            {videoTemplates.map((template) => (
              <option value={template.id} key={template.id}>
                {template.name}
              </option>
            ))}
          </select>
          <TotalDurationControl value={expectedTotalDuration} onChange={setExpectedTotalDuration} />
          <button
            type="button"
            disabled={!activeScript || busy.has('generatePromptCards')}
            onClick={() =>
              generatePromptCards({
                expectedTotalDurationSeconds: expectedTotalDuration,
              })
            }
          >
            {busy.has('generatePromptCards') ? <Loader2 className="spin" /> : <WandSparkles />}
            {sortedPromptCards.length ? '重新生成' : '生成提示词'}
          </button>
        </div>
      </PanelTitle>
      <p className="prompt-panel-hint">
        单卡≤{promptCardMaxDurationSeconds}s · 张数不限 · 拖动卡片右下角可调高度 · 在此列内下滑查看后续片段
        {imageAssetCount > 0 ? ` · 图片 ${imageAssetCount} 个可首尾帧/Multi` : ''}
      </p>

      <div className={`video-prompt-list ${sortedPromptCards.length === 0 ? 'is-empty' : ''}`} ref={listRef}>
        {sortedPromptCards.length === 0 && (
          <Empty text="生成提示词后，这里会按时长显示一张张提示词卡片" />
        )}
        {sortedPromptCards.map((card, index) => {
          const value = cardValue(card);
          const locked = Boolean(value.locked);
          const matchedSubjects = subjectCardsFor(value);
          const saving = busy.has(`savePromptCard:${card.id}`);
          const deleting = busy.has(`deletePromptCard:${card.id}`);
          const generatingVideo = busy.has(`generatePromptCardVideo:${card.id}`);
          const rerunning = busy.has(`rerunPromptCard:${card.id}`);
          const matching = busy.has(`matchPromptCardSubjects:${card.id}`);
          const updatingSubjects = busy.has(`updatePromptCardSubjects:${card.id}`);
          const togglingLock = busy.has(`togglePromptCardLock:${card.id}`);
          const mentionedCards = mentionedCardsFor(value);
          const versions = versionsByCard[card.id] || [];
          const activeVersionId = activeVersionByCard[card.id] || '';

          const order = segmentOrder(value, index);
          const titleBody = displaySegmentTitleBody(value.title, order);

          return (
            <VideoPromptCard
              key={card.id}
              cardId={card.id}
              savedHeight={clampPromptCardHeight(promptCardHeights[card.id])}
              onHeightChange={setPromptCardHeight}
              className={[
                locked ? 'video-prompt-card locked' : 'video-prompt-card',
                activePromptCardId === card.id ? 'active' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => setActivePromptCardId?.(card.id)}
            >
              <header className="prompt-card-header" onClick={(event) => event.stopPropagation()}>
                <div className="prompt-card-title-row">
                  <span className="prompt-card-segment">{`片段${order}`}</span>
                  <input
                    className="prompt-card-title-input"
                    value={titleBody}
                    disabled={locked}
                    placeholder="片段标题"
                    onChange={(event) =>
                      updateCardDraft(card, { title: composeSegmentTitle(order, event.target.value) })
                    }
                  />
                  <span className="prompt-card-head-meta">
                    {formatSeconds(value.duration)} / {sourceRangeLabel(value)}
                    {locked ? <span className="prompt-card-lock-badge">已锁定</span> : null}
                  </span>
                </div>
              </header>

              <div className="prompt-card-body" onClick={(event) => event.stopPropagation()}>
                <section
                  className={[
                    'prompt-card-slot',
                    'prompt-card-slot-content',
                    versions.length > 0 ? 'has-version-tabs' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  <div className="prompt-card-slot-head">
                    <span>分镜内容</span>
                    {versions.length > 0 && (
                      <div className="prompt-version-tabbar" role="tablist" onClick={(event) => event.stopPropagation()}>
                        <button
                          type="button"
                          role="tab"
                          aria-selected={!activeVersionId}
                          className={`prompt-version-tab${!activeVersionId ? ' active' : ''}`}
                          title="当前编辑中的提示词"
                          onClick={() => resetPromptVersion(card)}
                        >
                          当前
                        </button>
                        {versions.map((version) => (
                          <button
                            type="button"
                            role="tab"
                            key={version.id}
                            aria-selected={activeVersionId === version.id}
                            className={`prompt-version-tab${activeVersionId === version.id ? ' active' : ''}`}
                            title={`${versionTagLabel(version)} · ${version.created_at || ''}`}
                            onClick={() => applyPromptVersion(card, version)}
                          >
                            {versionTabLabel(version)}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="prompt-card-slot-actions">
                      <button
                        type="button"
                        className="secondary"
                        disabled={!value.prompt_text?.trim()}
                        onClick={() => downloadPromptCard(value, order)}
                      >
                        <Download />
                        下载
                      </button>
                    </div>
                  </div>
                  <div className="prompt-card-slot-body prompt-version-panel">
                    <MentionTextarea
                      value={value.prompt_text || ''}
                      disabled={locked}
                      entityCards={entityCards}
                      fontSize={promptContentFontSize}
                      rows={5}
                      onChange={(prompt_text) => updateCardDraft(card, { prompt_text, status: 'edited' })}
                      onInsertMention={(entityCard) =>
                        setMentionIdsByCard((prev) => {
                          const current = prev[card.id] || mentionIdsFor(card);
                          return current.includes(entityCard.id)
                            ? prev
                            : { ...prev, [card.id]: [...current, entityCard.id] };
                        })
                      }
                    />
                  </div>
                </section>

                <section className="prompt-card-slot">
                  <div className="prompt-card-slot-head">
                    <span>@引用</span>
                    <div className="prompt-card-slot-actions">
                      <button
                        type="button"
                        className="secondary prompt-subject-add"
                        disabled={locked || updatingSubjects}
                        onClick={() => openMentionPicker(card, value, matchedSubjects)}
                      >
                        <Plus />
                        手动添加
                      </button>
                    </div>
                  </div>
                  <div className="prompt-card-slot-body prompt-card-slot-body-inline">
                    <div className="mention-ref-list">
                      {mentionedCards.length === 0 && (
                        <span className="empty-inline">点击「匹配主体」或「手动添加」绑定实体卡</span>
                      )}
                      {mentionedCards.map((entityCard) => {
                        const refItem = mentionRefItems(entityCard);
                        const firstAsset = refItem.assets[0];
                        return (
                          <span className="mention-ref-item" key={entityCard.id}>
                            <span className="mention-ref-thumb">
                              {firstAsset ? (
                                <SubjectAssetThumb
                                  asset={firstAsset}
                                  url={buildAssetUrl(apiBase, selectedProject, firstAsset)}
                                />
                              ) : (
                                <span>无素材</span>
                              )}
                            </span>
                            <span className="mention-ref-meta">
                              <strong>@{entityCard.entity_name}</strong>
                              {entityCard.state ? <em>·{entityCard.state}</em> : null}
                            </span>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                </section>
              </div>

              <footer className="prompt-card-footer" onClick={(event) => event.stopPropagation()}>
                <div className="prompt-card-actions-row video-prompt-actions">
                  <button
                    type="button"
                    className={locked ? 'icon-button lock active' : 'icon-button lock'}
                    disabled={togglingLock}
                    title={locked ? '解锁提示词卡片' : '锁定提示词卡片'}
                    onClick={() => togglePromptCardLock?.(value)}
                  >
                    {togglingLock ? <Loader2 className="spin" /> : locked ? <Lock /> : <Unlock />}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={saving || locked}
                    onClick={() => savePromptCard(value)}
                  >
                    {saving ? <Loader2 className="spin" /> : <Save />}
                    保存
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={matching || locked}
                    onClick={() => runSubjectMatch(value)}
                  >
                    {matching ? <Loader2 className="spin" /> : <ScanSearch />}
                    匹配主体
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={rerunning || locked || !activeScript}
                    onClick={() => rerunPromptCard?.(value)}
                  >
                    {rerunning ? <Loader2 className="spin" /> : <RotateCcw />}
                    重跑
                  </button>
                  <button
                    type="button"
                    disabled={generatingVideo || !value.prompt_text?.trim()}
                    onClick={() => saveCardBeforeVideo(card)}
                  >
                    {generatingVideo ? <Loader2 className="spin" /> : <Film />}
                    生成视频请求
                  </button>
                  <button
                    type="button"
                    className="icon-button danger"
                    disabled={deleting || locked}
                    title="删除提示词卡片"
                    onClick={() => deletePromptCard(card)}
                  >
                    {deleting ? <Loader2 className="spin" /> : <Trash2 />}
                  </button>
                </div>
              </footer>
            </VideoPromptCard>
          );
        })}
      </div>

      <MentionPickerOverlay
        open={Boolean(mentionPickerCard)}
        cardTitle={mentionPickerCard?.value?.title || mentionPickerCard?.card?.title || ''}
        search={mentionPickerSearch}
        onSearchChange={setMentionPickerSearch}
        entityCards={entityCards}
        draftIds={mentionPickerDraftIds}
        onToggle={toggleMentionPickerDraft}
        saving={mentionPickerSaving}
        onCancel={closeMentionPicker}
        onSave={saveMentionPicker}
        selectedProject={selectedProject}
        apiBase={apiBase}
        assetByPath={assetByPath}
        cardAssetPaths={cardAssetPaths}
        missingAsset={missingAsset}
      />
    </article>
  );
}
