import React, { useEffect, useRef, useState } from 'react';
import {
  Clapperboard,
  Download,
  FileText,
  Layers3,
  Loader2,
  PenLine,
  Plus,
  RefreshCw,
  Save,
  Scissors,
  Upload,
} from 'lucide-react';
import PanelTitle from '../components/PanelTitle';
import SegmentList from '../components/SegmentList';
import { strategyLabel } from '../utils';
import { downloadTextFile, sanitizeFilename } from '../utils/download';
import {
  readPreprocessUiPrefs,
  startBoardColumnResize,
  startMainColumnResize,
  writePreprocessUiPrefs,
} from './preprocessViewUtils';

const defaultEpisodeTitle = (order) => `第${order}集`;
const defaultTitlePattern = /^第\d+集$/;

function resequenceEpisodes(segments) {
  return segments.map((segment, index) => {
    const order = index + 1;
    const title = !segment.title || defaultTitlePattern.test(segment.title) ? defaultEpisodeTitle(order) : segment.title;
    return { ...segment, order, title };
  });
}

function removeSegmentOutput(source, segmentId) {
  const next = { ...(source || {}) };
  delete next[segmentId];
  return next;
}

function compactSummary(value, fallback) {
  return (value || '').replace(/\s+/g, ' ').trim().slice(0, 92) || fallback;
}

export default function PreprocessView({
  workspace,
  activeSegment,
  activeScript,
  splitSuggestions,
  busy,
  projectName,
  templates = [],
  updateWorkspace,
  flushPersist,
  splitDocument,
  applySplitSuggestion,
  uploadProjectDocument,
  convertCurrentSegment,
  convertAllSegments,
  saveAllSegmentSources,
  saveAllScriptSources,
  saveActiveSegmentSource,
  saveActiveScriptSource,
  enterScriptStage,
  updateActiveScript,
  readOnly = false,
  documentReadOnly = false,
  segmentLockError = '',
  lockForSegment,
  isLockedByOther,
  onSelectSegment,
}) {
  const segmentLocked = readOnly;
  const documentLocked = documentReadOnly;
  const validation = activeSegment ? workspace.scriptValidation?.[activeSegment.id] : null;
  const activeTitle = activeSegment?.title || (activeSegment ? defaultEpisodeTitle(activeSegment.order) : '');
  const reconvertFormat = validation?.source_format === 'script' ? 'script' : 'source_text';
  const activeLock = activeSegment && lockForSegment ? lockForSegment(activeSegment.id) : null;
  const lockBanner =
    segmentLockError ||
    (activeLock && isLockedByOther?.(activeSegment.id)
      ? `该分集正由 ${activeLock.display_name || '其他用户'} 编辑，当前为只读`
      : '');
  const normalizedSplitStrategy = workspace.splitStrategy === 'duration_2min' ? 'duration' : workspace.splitStrategy;
  const scriptTemplates = templates.filter((template) => template.category === 'script_convert');
  const selectedScriptTemplate = scriptTemplates.find((template) => template.id === workspace.scriptConvertTemplateId)
    || scriptTemplates.find((template) => template.is_default)
    || scriptTemplates[0]
    || null;
  const [columnLayout, setColumnLayout] = useState(() => readPreprocessUiPrefs());
  const [contentTypeDraft, setContentTypeDraft] = useState(() => workspace.contentType || '分集原文');
  const contentTypeComposing = useRef(false);
  const gridRef = useRef(null);

  useEffect(() => {
    if (!contentTypeComposing.current) {
      setContentTypeDraft(workspace.contentType || '分集原文');
    }
  }, [workspace.contentType]);

  function commitContentType(value) {
    const next = String(value || '').trim() || '分集原文';
    setContentTypeDraft(next);
    if (next !== (workspace.contentType || '分集原文')) {
      updateWorkspace({ contentType: next });
    }
  }

  function updateMainLeft(mainLeft) {
    setColumnLayout((prev) => {
      const next = { ...prev, mainLeft };
      writePreprocessUiPrefs(next);
      return next;
    });
  }

  function updateBoardList(boardList) {
    setColumnLayout((prev) => {
      const next = { ...prev, boardList };
      writePreprocessUiPrefs(next);
      return next;
    });
  }

  const boardColumns = `minmax(180px, ${columnLayout.boardList}fr) 12px minmax(220px, ${100 - columnLayout.boardList}fr)`;

  const insertManualMarkers = () => {
    const count = (workspace.documentText.match(/【第?\S+段始】/g) || []).length + 1;
    const marker = `\n\n【第${count}段始】\n\n【第${count}段末】`;
    updateWorkspace({ documentText: `${workspace.documentText || ''}${marker}`.trimStart() });
  };

  const createSegmentAfterActive = ({ seedScript = false } = {}) => {
    const id = `seg_manual_${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 6)}`;
    updateWorkspace((prev) => {
      const activeIndex = prev.segments.findIndex((segment) => segment.id === prev.activeSegmentId);
      const insertIndex = activeIndex >= 0 ? activeIndex + 1 : prev.segments.length;
      const segments = [...prev.segments];
      segments.splice(insertIndex, 0, {
        id,
        document_id: 'manual',
        documentId: 'manual',
        order: insertIndex + 1,
        title: defaultEpisodeTitle(insertIndex + 1),
        content: '',
      });
      const next = {
        ...prev,
        segments: resequenceEpisodes(segments),
        activeSegmentId: id,
        assetsConfirmed: false,
      };
      if (!seedScript) return next;
      return {
        ...next,
        scripts: { ...prev.scripts, [id]: '' },
        scriptValidation: {
          ...prev.scriptValidation,
          [id]: {
            valid: false,
            status: 'edited',
            confirmed: false,
            reason: '脚本为空',
            error: '',
          },
        },
      };
    });
  };

  const addSegment = () => createSegmentAfterActive();
  const addScript = () => createSegmentAfterActive({ seedScript: true });

  const handleEnterScriptStage = () => {
    if (workspace.segments.length === 0) return;
    Promise.resolve(enterScriptStage()).then((completed) => {
      if (!completed) return;
      window.requestAnimationFrame(() => {
        document.getElementById('script-workspace')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  };

  const updateActiveSegmentTitle = (value) => {
    if (!activeSegment) return;
    updateWorkspace((prev) => ({
      ...prev,
      segments: prev.segments.map((segment) => (segment.id === activeSegment.id ? { ...segment, title: value } : segment)),
    }));
  };

  const updateActiveSegmentContent = (value) => {
    if (!activeSegment) return;
    // 编辑分集原文时不同步/清空剧本；仅在「保存本集原文」时按规则同步。
    updateWorkspace((prev) => ({
      ...prev,
      segments: prev.segments.map((segment) => (segment.id === activeSegment.id ? { ...segment, content: value } : segment)),
    }));
  };

  const reorderSegment = (sourceId, targetId) => {
    if (!sourceId || sourceId === targetId) return;
    updateWorkspace((prev) => {
      const sourceIndex = prev.segments.findIndex((segment) => segment.id === sourceId);
      const targetIndex = prev.segments.findIndex((segment) => segment.id === targetId);
      if (sourceIndex < 0 || targetIndex < 0) return prev;
      const segments = [...prev.segments];
      const [segment] = segments.splice(sourceIndex, 1);
      segments.splice(targetIndex, 0, segment);
      return { ...prev, segments: resequenceEpisodes(segments), activeSegmentId: sourceId, assetsConfirmed: false };
    });
  };

  const deleteSegment = (segmentId) => {
    updateWorkspace((prev) => {
      const removedIndex = prev.segments.findIndex((item) => item.id === segmentId);
      const segments = resequenceEpisodes(prev.segments.filter((segment) => segment.id !== segmentId));
      const nextActive =
        prev.activeSegmentId === segmentId
          ? segments[Math.min(Math.max(removedIndex, 0), segments.length - 1)]?.id || ''
          : prev.activeSegmentId;
      return {
        ...prev,
        segments,
        activeSegmentId: nextActive,
        scripts: removeSegmentOutput(prev.scripts, segmentId),
        scriptValidation: removeSegmentOutput(prev.scriptValidation, segmentId),
        prompts: removeSegmentOutput(prev.prompts, segmentId),
        assetsConfirmed: false,
      };
    });
  };

  const deleteScript = (segmentId) => {
    updateWorkspace((prev) => ({
      ...prev,
      scripts: removeSegmentOutput(prev.scripts, segmentId),
      scriptValidation: removeSegmentOutput(prev.scriptValidation, segmentId),
      prompts: removeSegmentOutput(prev.prompts, segmentId),
      assetsConfirmed: false,
    }));
  };

  const scriptSummaryForSegment = (segment) => compactSummary(workspace.scripts?.[segment.id], '尚未生成脚本');

  const projectPrefix = sanitizeFilename(projectName || 'project', 'project');

  function downloadDocumentText() {
    downloadTextFile(workspace.documentText || '', `${projectPrefix}-原始内容`);
  }

  function downloadActiveSegmentSource() {
    if (!activeSegment) return;
    downloadTextFile(activeSegment.content || '', `${projectPrefix}-${sanitizeFilename(activeTitle, '分集')}-原文`);
  }

  function downloadActiveScript() {
    if (!activeSegment) return;
    downloadTextFile(activeScript || '', `${projectPrefix}-${sanitizeFilename(activeTitle, '分集')}-剧本`);
  }

  function buildEpisodeExport(contentForSegment, sectionLabel) {
    return workspace.segments
      .map((segment, index) => {
        const title = segment.title || defaultEpisodeTitle(index + 1);
        const content = String(contentForSegment(segment) || '').trim();
        return `${'='.repeat(64)}\n${title} · ${sectionLabel}\n${'='.repeat(64)}\n\n${content}\n`;
      })
      .join('\n');
  }

  function downloadAllSegmentSources() {
    downloadTextFile(
      buildEpisodeExport((segment) => segment.content, '分集原文'),
      `${projectPrefix}-全部分集原文`,
    );
  }

  function downloadAllScripts() {
    downloadTextFile(
      buildEpisodeExport((segment) => workspace.scripts?.[segment.id], '剧本'),
      `${projectPrefix}-全部剧本`,
    );
  }

  return (
    <div
      className="work-grid preprocess-grid"
      ref={gridRef}
      style={{
        gridTemplateColumns: `minmax(280px, ${columnLayout.mainLeft}fr) 16px minmax(320px, ${100 - columnLayout.mainLeft}fr)`,
      }}
    >
      <section className={`panel text-panel${documentLocked ? ' is-readonly' : ''}`}>
        <PanelTitle icon={FileText} title="原始内容">
          <button type="button" className="icon-button secondary" title="下载原始内容" aria-label="下载原始内容" disabled={!workspace.documentText?.trim()} onClick={downloadDocumentText}>
            <Download />
          </button>
          <label className="upload-control icon-button" title="导入文档" aria-label="导入文档">
            {busy.has('uploadDocument') ? <Loader2 className="spin" /> : <Upload />}
            <input
              type="file"
              accept=".txt,.md,.markdown,.docx,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) uploadProjectDocument(file);
                event.target.value = '';
              }}
            />
          </label>
        </PanelTitle>
        <div className="preprocess-toolbar" aria-label="文本处理设置">
          <label className="toolbar-field split-strategy-field">
            <span>切分方式</span>
          <select value={normalizedSplitStrategy} onChange={(event) => updateWorkspace({ splitStrategy: event.target.value })}>
            <option value="chapter">章节正则</option>
            <option value="custom_regex">自定义正则</option>
            <option value="manual">手动标记</option>
            <option value="length">长度切分</option>
            <option value="duration">按时长（LLM）</option>
          </select>
          </label>
          {normalizedSplitStrategy === 'duration' && (
            <label className="inline-number-field">
              <span>分钟</span>
              <input
                type="number"
                min="0.5"
                max="30"
                step="0.5"
                value={workspace.durationMinutes || 2}
                onChange={(event) => updateWorkspace({ durationMinutes: Number(event.target.value) || 2 })}
              />
            </label>
          )}
          {workspace.splitStrategy === 'custom_regex' && (
            <label className="toolbar-field regex-field">
              <span>匹配表达式</span>
              <input
                className="split-pattern-input"
                value={workspace.customSplitPattern || ''}
                onChange={(event) => updateWorkspace({ customSplitPattern: event.target.value })}
                placeholder="切分符号/正则，如【第*集】"
              />
            </label>
          )}
          {workspace.splitStrategy === 'manual' && (
            <button type="button" className="icon-button secondary" title="插入手动切分标记" aria-label="插入手动切分标记" onClick={insertManualMarkers}>
              <PenLine />
            </button>
          )}
          <button type="button" className="icon-button" title="生成切分方案" aria-label="生成切分方案" onClick={splitDocument}>
            {busy.has('split') ? <Loader2 className="spin" /> : <Scissors />}
          </button>
        </div>
        <textarea
          value={workspace.documentText}
          onChange={(event) => updateWorkspace({ documentText: event.target.value })}
          onBlur={() => flushPersist?.()}
          spellCheck="false"
        />
        {splitSuggestions.length > 0 && (
          <div className="split-suggestions">
            {splitSuggestions.map((suggestion) => (
              <div className="split-suggestion" key={suggestion.strategy}>
                <strong>{strategyLabel(suggestion.strategy)}</strong>
                <span>{suggestion.segment_count} 集</span>
                <small>约 {suggestion.estimated_minutes} 分钟</small>
                <p>{suggestion.summaries?.slice(0, 3).join(' / ')}</p>
                <button type="button" onClick={() => applySplitSuggestion(suggestion.strategy)}>
                  应用为分集
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <div
        className="preprocess-column-resizer"
        role="separator"
        aria-label="调整原文列与右侧列宽度"
        onPointerDown={(event) =>
          startMainColumnResize({
            event,
            startLeft: columnLayout.mainLeft,
            onChange: updateMainLeft,
          })
        }
      />

      <div className={`preprocess-right-column${segmentLocked ? ' is-readonly' : ''}`}>
      <section className="panel episode-panel">
        <PanelTitle icon={Layers3} title="分集管理">
          <button type="button" className="icon-button secondary" title="新增分集" aria-label="新增分集" onClick={addSegment}>
            <Plus />
          </button>
          <button type="button" className="icon-button secondary" title="保存全部分集原文" aria-label="保存全部分集原文" disabled={workspace.segments.length === 0} onClick={saveAllSegmentSources}>
            {busy.has('saveSegments') ? <Loader2 className="spin" /> : <Save />}
          </button>
          <button type="button" className="icon-button secondary" title="下载全部分集" aria-label="下载全部分集" disabled={workspace.segments.length === 0} onClick={downloadAllSegmentSources}>
            <Download />
          </button>
          <button type="button" className="icon-button" title="进入剧本处理" aria-label="进入剧本处理" disabled={workspace.segments.length === 0} onClick={handleEnterScriptStage}>
            <Clapperboard />
          </button>
        </PanelTitle>
        {lockBanner ? <div className="segment-lock-banner">{lockBanner}</div> : null}
        <div className="preprocess-board episode-board" style={{ gridTemplateColumns: boardColumns }}>
          <SegmentList
            workspace={workspace}
            updateWorkspace={updateWorkspace}
            onReorderSegment={reorderSegment}
            onDeleteSegment={deleteSegment}
            onSelectSegment={onSelectSegment}
            lockForSegment={lockForSegment}
            lockLabelForSegment={(lock) => `${lock.display_name || '用户'} 编辑中`}
          />
          <div
            className="preprocess-board-resizer"
            role="separator"
            aria-label="调整分集列表与详情宽度"
            onPointerDown={(event) =>
              startBoardColumnResize({
                event,
                startList: columnLayout.boardList,
                onChange: updateBoardList,
              })
            }
          />
          <div className="episode-detail">
            {activeSegment ? (
              <>
                <div className="episode-detail-heading">
                  <div className="detail-heading-title">
                    <strong>{activeTitle}</strong>
                    <span>第 {activeSegment.order} 集</span>
                  </div>
                  <div className="detail-actions">
                    <button type="button" className="icon-button secondary" title="下载本集原文" aria-label="下载本集原文" disabled={!activeSegment?.content?.trim()} onClick={downloadActiveSegmentSource}>
                      <Download />
                    </button>
                    <button type="button" className="icon-button terminal-action" title="保存本集原文" aria-label="保存本集原文" onClick={saveActiveSegmentSource}>
                      {busy.has('saveActiveSegment') ? <Loader2 className="spin" /> : <Save />}
                    </button>
                  </div>
                </div>
                <label>
                  分集标题
                  <input value={activeTitle} onChange={(event) => updateActiveSegmentTitle(event.target.value)} />
                </label>
                <label className="episode-source">
                  该集原文
                  <textarea
                    value={activeSegment.content || ''}
                    onChange={(event) => updateActiveSegmentContent(event.target.value)}
                    placeholder="该集原文为空"
                  />
                </label>
              </>
            ) : (
              <div className="empty">暂无分集</div>
            )}
          </div>
        </div>
      </section>

      <section className="panel script-panel" id="script-workspace">
        <PanelTitle icon={Clapperboard} title="剧本管理">
          <button type="button" className="icon-button secondary" title="新增剧本" aria-label="新增剧本" onClick={addScript}>
            <Plus />
          </button>
          <button
            type="button"
            className="icon-button secondary"
            title="全部重新转换"
            aria-label="全部重新转换"
            disabled={workspace.segments.length === 0 || busy.has('convertAll')}
            onClick={() => convertAllSegments?.()}
          >
            {busy.has('convertAll') ? <Loader2 className="spin" /> : <RefreshCw />}
          </button>
          <button type="button" className="icon-button secondary" title="下载全部剧本" aria-label="下载全部剧本" disabled={workspace.segments.length === 0} onClick={downloadAllScripts}>
            <Download />
          </button>
          <button type="button" className="icon-button terminal-action" title="保存全部剧本原文" aria-label="保存全部剧本原文" disabled={workspace.segments.length === 0} onClick={saveAllScriptSources}>
            {busy.has('saveScripts') ? <Loader2 className="spin" /> : <Save />}
          </button>
        </PanelTitle>
        <div className="script-conversion-toolbar">
          <label className="toolbar-field template-field">
            <span>转换模板</span>
            <select
              value={selectedScriptTemplate?.id || ''}
              disabled={!scriptTemplates.length}
              onChange={(event) => updateWorkspace({ scriptConvertTemplateId: event.target.value })}
            >
              {!scriptTemplates.length && <option value="">暂无剧本转换模板</option>}
              {scriptTemplates.map((template) => (
                <option key={template.id} value={template.id}>{template.name}{template.is_default ? ' · 默认' : ''}</option>
              ))}
            </select>
          </label>
          <label className="toolbar-field content-type-field" title="$content_type：由此字段提供，可按当前输入语境编辑">
            <span>输入类型 · $content_type</span>
            <input
              value={contentTypeDraft}
              onChange={(event) => setContentTypeDraft(event.target.value)}
              onCompositionStart={() => { contentTypeComposing.current = true; }}
              onCompositionEnd={(event) => {
                contentTypeComposing.current = false;
                commitContentType(event.currentTarget.value);
              }}
              onBlur={(event) => {
                contentTypeComposing.current = false;
                commitContentType(event.currentTarget.value);
                window.setTimeout(() => flushPersist?.(), 0);
              }}
              placeholder="例如：小说原文、口播稿、已有剧本"
            />
          </label>
          <div className="template-impact-note" title="$content 由当前分集原文自动提供">
            <strong>$content</strong>
            <span>当前分集原文</span>
          </div>
          <span className="future-only-note">仅影响后续转换</span>
        </div>
        {lockBanner ? <div className="segment-lock-banner">{lockBanner}</div> : null}
        <div className="preprocess-board script-board" style={{ gridTemplateColumns: boardColumns }}>
          <SegmentList
            className="script-list"
            workspace={workspace}
            updateWorkspace={updateWorkspace}
            emptyText="暂无脚本"
            summaryForSegment={scriptSummaryForSegment}
            onDeleteSegment={deleteScript}
            deleteTitle="删除剧本"
            onSelectSegment={onSelectSegment}
            lockForSegment={lockForSegment}
            lockLabelForSegment={(lock) => `${lock.display_name || '用户'} 编辑中`}
          />
          <div
            className="preprocess-board-resizer"
            role="separator"
            aria-label="调整脚本列表与编辑区宽度"
            onPointerDown={(event) =>
              startBoardColumnResize({
                event,
                startList: columnLayout.boardList,
                onChange: updateBoardList,
              })
            }
          />
          <div className="episode-detail script-detail">
            {activeSegment ? (
              <>
                <div className="episode-detail-heading">
                  <div className="detail-heading-title">
                    <strong>{activeTitle}</strong>
                    <span>第 {activeSegment.order} 集</span>
                  </div>
                  <div className="detail-actions">
                    <button type="button" className="icon-button secondary" title="下载本集剧本" aria-label="下载本集剧本" disabled={!activeScript?.trim()} onClick={downloadActiveScript}>
                      <Download />
                    </button>
                    <button
                      type="button"
                      className="icon-button secondary"
                      title="重新转换本集剧本"
                      aria-label="重新转换本集剧本"
                      disabled={!activeSegment || busy.has('convertCurrent')}
                      onClick={() => convertCurrentSegment(reconvertFormat)}
                    >
                      {busy.has('convertCurrent') ? <Loader2 className="spin" /> : <RefreshCw />}
                    </button>
                    <button type="button" className="icon-button terminal-action" title="保存本集剧本" aria-label="保存本集剧本" onClick={saveActiveScriptSource}>
                      {busy.has('saveActiveScript') ? <Loader2 className="spin" /> : <Save />}
                    </button>
                  </div>
                </div>
                <label className="episode-source script-source">
                  剧本原文
                  <textarea
                    value={activeScript}
                    disabled={!activeSegment}
                    onChange={(event) => updateActiveScript(event.target.value)}
                    placeholder="尚未生成脚本"
                  />
                </label>
              </>
            ) : (
              <div className="empty">请选择分集</div>
            )}
          </div>
        </div>
      </section>
      </div>
    </div>
  );
}
