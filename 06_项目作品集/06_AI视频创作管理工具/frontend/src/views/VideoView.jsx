import React, { useEffect, useMemo, useRef, useState } from 'react';
import PromptCardPanel from './video/PromptCardPanel';
import VideoOutputColumn from './video/VideoOutputColumn';
import VideoSourceColumn from './video/VideoSourceColumn';
import {
  draftKey,
  readVideoUiPrefs,
  selectEntityCards,
  selectSegmentVideoTasks,
  writeVideoUiPrefs,
  clampPromptContentFontSize,
  clampPromptCardHeight,
  clampScriptFontSize,
} from './video/videoViewUtils';
import { baseContentFontSize } from '../themeUtils';

export default function VideoView({
  workspace,
  entityCards,
  assets = [],
  selectedProject,
  apiBase,
  apiConfig = {},
  videoTasks,
  videoOutputs = [],
  promptCards = [],
  templates = [],
  selectedTemplateId = '',
  activeScript = '',
  busy,
  setActiveSegment,
  setSelectedTemplateId,
  updateWorkspace,
  generatePromptCards,
  rerunPromptCard,
  togglePromptCardLock,
  matchPromptCardSubjects,
  updatePromptCardSubjects,
  savePromptCard,
  deletePromptCard,
  resolveMentions,
  generatePromptCardVideo,
  retryVideoTask,
  downloadVideoTask,
  recoverVideoTask,
  deleteVideoTask,
  syncVideoTasks,
  adoptVideoOutput,
  appearance = { fontScale: 'm' },
}) {
  const [columnLayout, setColumnLayout] = useState({ left: 30, middle: 44, right: 26 });
  const [cardDrafts, setCardDrafts] = useState({});
  const [activePromptCardId, setActivePromptCardId] = useState('');
  const [videoUi, setVideoUi] = useState(() => readVideoUiPrefs(appearance.fontScale));
  const prevFontScaleRef = useRef(appearance.fontScale);
  const gridRef = useRef(null);

  const expectedTotalDuration = workspace.expectedTotalDurationSeconds ?? null;

  const activeSegment = useMemo(
    () => workspace.segments.find((segment) => segment.id === workspace.activeSegmentId) || workspace.segments[0] || null,
    [workspace.activeSegmentId, workspace.segments],
  );
  const activeSegmentIndex = activeSegment ? workspace.segments.findIndex((segment) => segment.id === activeSegment.id) : -1;
  const sortedPromptCards = useMemo(() => [...promptCards].sort((a, b) => a.order - b.order), [promptCards]);
  const videoTemplates = useMemo(
    () => templates.filter((template) => template.category === 'video_generate'),
    [templates],
  );
  const promptCardStateKey = useMemo(() => draftKey(sortedPromptCards), [sortedPromptCards]);

  useEffect(() => {
    setCardDrafts({});
  }, [activeSegment?.id, promptCardStateKey]);

  useEffect(() => {
    const prevBase = baseContentFontSize(prevFontScaleRef.current);
    const nextBase = baseContentFontSize(appearance.fontScale);
    const delta = nextBase - prevBase;
    if (!delta) return;
    setVideoUi((prev) => {
      const next = {
        ...prev,
        promptContentFontSize: clampPromptContentFontSize(prev.promptContentFontSize + delta),
        scriptFontSize: clampScriptFontSize(prev.scriptFontSize + delta),
      };
      writeVideoUiPrefs(next);
      return next;
    });
    prevFontScaleRef.current = appearance.fontScale;
  }, [appearance.fontScale]);

  useEffect(() => {
    if (!sortedPromptCards.length) {
      setActivePromptCardId('');
      return;
    }
    if (!sortedPromptCards.some((card) => card.id === activePromptCardId)) {
      setActivePromptCardId(sortedPromptCards[0].id);
    }
  }, [sortedPromptCards, activePromptCardId]);

  const selectedEntityCards = useMemo(
    () => selectEntityCards({ entityCards, promptCards: sortedPromptCards }),
    [entityCards, sortedPromptCards],
  );
  const activeTasks = useMemo(
    () => selectSegmentVideoTasks({ activeSegment, promptCards: sortedPromptCards, videoTasks }),
    [activeSegment, sortedPromptCards, videoTasks],
  );
  const activeShot = sortedPromptCards.find((card) => card.id === activePromptCardId) || sortedPromptCards[0] || null;
  const shotTasks = useMemo(() => {
    if (!activeShot) return [];
    return videoTasks
      .filter((task) => task.prompt_card_id === activeShot.id)
      .sort((a, b) => String(b.created_at || b.createdAt || '').localeCompare(String(a.created_at || a.createdAt || '')));
  }, [activeShot, videoTasks]);
  const shotOutputs = useMemo(() => {
    if (!activeShot) return [];
    return videoOutputs
      .filter((output) => output.prompt_card_id === activeShot.id)
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  }, [activeShot, videoOutputs]);

  function setExpectedTotalDuration(value) {
    updateWorkspace?.({ expectedTotalDurationSeconds: value });
  }

  function setScriptFontSize(value) {
    setVideoUi((prev) => {
      const next = { ...prev, scriptFontSize: clampScriptFontSize(value) };
      writeVideoUiPrefs(next);
      return next;
    });
  }

  /** Persist per-card height from PromptCardPanel custom resize handle (localStorage). */
  function setPromptCardHeight(cardId, height) {
    const clamped = clampPromptCardHeight(height);
    if (!cardId || !clamped) return;
    setVideoUi((prev) => {
      if (prev.promptCardHeights?.[cardId] === clamped) return prev;
      const next = {
        ...prev,
        promptCardHeights: { ...prev.promptCardHeights, [cardId]: clamped },
      };
      writeVideoUiPrefs(next);
      return next;
    });
  }

  function startColumnResize(handle, event) {
    event.preventDefault();
    const startX = event.clientX;
    const startLayout = columnLayout;
    const gridWidth = gridRef.current?.getBoundingClientRect().width || 1;

    function applyResize(moveEvent) {
      const delta = ((moveEvent.clientX - startX) / gridWidth) * 100;
      setColumnLayout(() => {
        if (handle === 'left') {
          const left = Math.min(48, Math.max(18, startLayout.left + delta));
          const middle = Math.min(58, Math.max(24, startLayout.middle - (left - startLayout.left)));
          return { left, middle, right: 100 - left - middle };
        }
        const right = Math.min(44, Math.max(18, startLayout.right - delta));
        const middle = Math.min(58, Math.max(24, startLayout.middle + (startLayout.right - right)));
        return { left: 100 - middle - right, middle, right };
      });
    }

    function stopResize() {
      window.removeEventListener('pointermove', applyResize);
      window.removeEventListener('pointerup', stopResize);
    }

    window.addEventListener('pointermove', applyResize);
    window.addEventListener('pointerup', stopResize);
  }

  function cardValue(card) {
    return { ...card, ...(cardDrafts[card.id] || {}) };
  }

  function updateCardDraft(card, patch) {
    setCardDrafts((prev) => ({
      ...prev,
      [card.id]: { ...(prev[card.id] || {}), ...patch },
    }));
  }

  async function saveCardBeforeVideo(card) {
    const value = cardValue(card);
    const dirty = Boolean(cardDrafts[card.id]);
    const saved = dirty ? await savePromptCard(value) : value;
    if (!saved) return;
    setActivePromptCardId(card.id);
    await generatePromptCardVideo(saved);
  }

  return (
    <div
      className="work-grid video-grid"
      ref={gridRef}
      style={{
        gridTemplateColumns: `minmax(220px, ${columnLayout.left}fr) 8px minmax(320px, ${columnLayout.middle}fr) 8px minmax(220px, ${columnLayout.right}fr)`,
      }}
    >
      <div className="video-column-scroll">
        <VideoSourceColumn
          workspace={workspace}
          activeSegment={activeSegment}
          activeSegmentIndex={activeSegmentIndex}
          activeScript={activeScript}
          selectedEntityCards={selectedEntityCards}
          projectName={selectedProject?.name}
          assets={assets}
          selectedProject={selectedProject}
          apiBase={apiBase}
          setActiveSegment={setActiveSegment}
          scriptFontSize={videoUi.scriptFontSize}
          setScriptFontSize={setScriptFontSize}
        />
      </div>

      <div
        className="video-column-resizer"
        role="separator"
        aria-label="调整左侧和中间宽度"
        onPointerDown={(event) => startColumnResize('left', event)}
      />

      <div className="video-column-scroll">
        <PromptCardPanel
          activeScript={activeScript}
          sortedPromptCards={sortedPromptCards}
          videoTemplates={videoTemplates}
          selectedTemplateId={selectedTemplateId}
          setSelectedTemplateId={setSelectedTemplateId}
          expectedTotalDuration={expectedTotalDuration}
          setExpectedTotalDuration={setExpectedTotalDuration}
          activePromptCardId={activePromptCardId}
          setActivePromptCardId={setActivePromptCardId}
          busy={busy}
          generatePromptCards={generatePromptCards}
          rerunPromptCard={rerunPromptCard}
          togglePromptCardLock={togglePromptCardLock}
          matchPromptCardSubjects={matchPromptCardSubjects}
          updatePromptCardSubjects={updatePromptCardSubjects}
          resolveMentions={resolveMentions}
          cardValue={cardValue}
          updateCardDraft={updateCardDraft}
          savePromptCard={savePromptCard}
          deletePromptCard={deletePromptCard}
          saveCardBeforeVideo={saveCardBeforeVideo}
          entityCards={entityCards}
          assets={assets}
          selectedProject={selectedProject}
          apiBase={apiBase}
          promptContentFontSize={videoUi.promptContentFontSize}
          promptCardHeights={videoUi.promptCardHeights}
          setPromptCardHeight={setPromptCardHeight}
        />
      </div>

      <div
        className="video-column-resizer"
        role="separator"
        aria-label="调整中间和右侧宽度"
        onPointerDown={(event) => startColumnResize('right', event)}
      />

      <div className="video-column-scroll">
        <VideoOutputColumn
          apiBase={apiBase}
          selectedProject={selectedProject}
          apiConfig={apiConfig}
          activeShot={activeShot ? cardValue(activeShot) : null}
          shotTasks={shotTasks}
          shotOutputs={shotOutputs}
          activeTasks={activeTasks}
          retryVideoTask={retryVideoTask}
          downloadVideoTask={downloadVideoTask}
          recoverVideoTask={recoverVideoTask}
          deleteVideoTask={deleteVideoTask}
          syncVideoTasks={syncVideoTasks}
          adoptVideoOutput={adoptVideoOutput}
          syncBusy={busy instanceof Set ? busy.has('syncVideoTasks') : false}
          downloadBusyId={
            [...(busy instanceof Set ? busy : [])].find((key) => String(key).startsWith('downloadVideoTask:'))?.replace(
              'downloadVideoTask:',
              '',
            ) || ''
          }
          recoverBusyId={
            [...(busy instanceof Set ? busy : [])].find((key) => String(key).startsWith('recoverVideoTask:'))?.replace(
              'recoverVideoTask:',
              '',
            ) || ''
          }
        />
      </div>
    </div>
  );
}
