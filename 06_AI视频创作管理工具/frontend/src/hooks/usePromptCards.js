import { useCallback } from 'react';

import {
  isTransientNetworkError,
  LLM_REQUEST_TIMEOUT_MS,
  request,
  sleep,
} from '../api/client';
import {
  defaultExpectedTotalDurationSeconds,
  promptCardMaxDurationSeconds,
} from '../constants';
import { promptContextValue } from '../app/uiStorage';
import { sanitizeVideoRequestSettings, writeVideoRequestSettings } from '../app/videoRequestSettings';
import { createPromptCardVideoTask } from '../api/promptCards';
import { useProjectScope } from './useProjectScope';

function promptCardPayload(card, patch = {}) {
  return {
    title: card.title || `提示词卡片 ${card.order || 1}`,
    prompt_text: card.prompt_text || '',
    anchor_text: card.anchor_text || '',
    duration: Number(card.duration || 0),
    status: card.status || 'draft',
    locked: Boolean(card.locked),
    source_text: card.source_text || '',
    source_start: Number(card.source_start || 0),
    source_end: Number(card.source_end || 0),
    ...patch,
  };
}

function cardFingerprint(cards = []) {
  return cards
    .map((card) => `${card.id}:${card.prompt_text || ''}:${Number(card.duration || 0)}`)
    .join('|');
}

async function waitForPromptCardsChange(projectId, segmentId, baselineFingerprint, {
  timeoutMs = LLM_REQUEST_TIMEOUT_MS,
  intervalMs = 4000,
} = {}) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    await sleep(intervalMs);
    try {
      const data = await request(
        `/api/projects/${encodeURIComponent(projectId)}/segments/${encodeURIComponent(segmentId)}/prompt-cards`,
        { timeoutMs: 20000 },
      );
      const cards = data.cards || [];
      if (cardFingerprint(cards) !== baselineFingerprint) {
        return { cards };
      }
    } catch (_error) {
      // Backend may still be busy with the LLM call; keep polling.
    }
  }
  return null;
}

async function requestGenerateWithRecovery(path, options, { recover, onWaiting }) {
  try {
    return await request(path, options);
  } catch (error) {
    if (!isTransientNetworkError(error)) throw error;
    onWaiting?.(error);
    const recovered = await recover();
    if (recovered) return recovered;
    throw error;
  }
}

export function usePromptCards({
  run,
  notify,
  askConfirm,
  selectedProject,
  activeSegment,
  activeScript,
  promptCards,
  setPromptCards,
  templates,
  selectedTemplateId,
  refreshProjectState,
  askVideoRequest,
  setVideoRequestSettings,
  videoProvider = '',
  prependVideoTask,
}) {
  const currentProjectId = selectedProject?.id || '';
  const isCurrentProject = useProjectScope(currentProjectId);
  const setCurrentPromptCards = useCallback((updater) => {
    if (isCurrentProject(currentProjectId)) setPromptCards(updater);
  }, [currentProjectId, isCurrentProject, setPromptCards]);

  const selectedVideoTemplateId = useCallback(() => {
    const selected = templates.find((item) => item.id === selectedTemplateId && item.category === 'video_generate');
    return selected?.id || '';
  }, [selectedTemplateId, templates]);

  const generatePromptCards = useCallback(
    ({ expectedTotalDurationSeconds } = {}) =>
      run('generatePromptCards', async () => {
        if (!selectedProject || !activeSegment) throw new Error('请先选择项目和分集');
        if (!activeScript.trim()) throw new Error('当前集没有剧本原文');
        const lockedCount = promptCards.filter((card) => card.locked).length;
        const useExpected =
          expectedTotalDurationSeconds != null &&
          expectedTotalDurationSeconds !== '' &&
          Number.isFinite(Number(expectedTotalDurationSeconds));
        const expectedTotalDuration = useExpected
          ? promptContextValue(expectedTotalDurationSeconds, defaultExpectedTotalDurationSeconds)
          : null;
        const confirmItems = [
          { label: '分集', value: activeSegment.title || activeSegment.order },
          { label: '剧本字数', value: activeScript.length },
          { label: '总时长', value: useExpected ? `${expectedTotalDuration}s` : '-' },
          { label: '单卡上限', value: `提示词规则 ${promptCardMaxDurationSeconds} 秒` },
          { label: '已锁定', value: lockedCount },
        ];
        const confirmed = await askConfirm({
          title: promptCards.length ? '重新生成提示词' : '生成提示词',
          body: lockedCount
            ? `将调用 LLM 重新生成本集提示词，${lockedCount} 张已锁定卡片会保留，未锁定卡片会被替换。`
            : '将调用 LLM 直接读取本集剧本，按剧情节奏自动生成提示词卡片。已有提示词卡片会被替换。',
          confirmLabel: promptCards.length ? '重新生成' : '生成提示词',
          items: confirmItems,
        });
        if (!confirmed) return;
        const videoTemplateId = selectedVideoTemplateId();
        const baselineFingerprint = cardFingerprint(promptCards);
        const data = await requestGenerateWithRecovery(
          `/api/projects/${selectedProject.id}/segments/${activeSegment.id}/prompt-cards/generate`,
          {
            method: 'POST',
            timeoutMs: LLM_REQUEST_TIMEOUT_MS,
            body: JSON.stringify({
              script: activeScript,
              template_name_or_id: videoTemplateId || null,
              expected_total_duration_seconds: expectedTotalDuration,
              max_duration_seconds: promptCardMaxDurationSeconds,
              replace: true,
            }),
          },
          {
            onWaiting: () =>
              notify('生成请求已中断或超时，正在轮询后台结果（无需手动刷新）…', 'info'),
            recover: () =>
              waitForPromptCardsChange(selectedProject.id, activeSegment.id, baselineFingerprint),
          },
        );
        if (!isCurrentProject(selectedProject.id)) return data.cards;
        setCurrentPromptCards(data.cards);
        refreshProjectState(selectedProject.id).catch(() => {});
        notify(`已生成 ${data.cards.length} 张提示词卡片`, 'success');
        if (useExpected && expectedTotalDuration) {
          const totalDuration = (data.cards || []).reduce((sum, card) => sum + Number(card.duration || 0), 0);
          const ratio = totalDuration / Number(expectedTotalDuration);
          if (ratio < 0.5 || ratio > 1.5) {
            notify(
              `总时长约 ${Math.round(totalDuration)}s，与预期 ${expectedTotalDuration}s 偏差较大，可重生成或补卡`,
              'info',
            );
          }
        }
        return data.cards;
      }),
    [
      activeScript,
      activeSegment,
      askConfirm,
      notify,
      promptCards,
      refreshProjectState,
      run,
      selectedProject,
      selectedVideoTemplateId,
      setCurrentPromptCards,
      isCurrentProject,
    ],
  );

  const savePromptCard = useCallback(
    (card) =>
      run(`savePromptCard:${card.id}`, async () => {
        const saved = await request(`/api/prompt-cards/${card.id}`, {
          method: 'PUT',
          body: JSON.stringify(promptCardPayload(card)),
        });
        setCurrentPromptCards((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        notify('提示词卡片已保存', 'success');
        return saved;
      }),
    [notify, run, setCurrentPromptCards],
  );

  const matchPromptCardSubjects = useCallback(
    (card) =>
      run(`matchPromptCardSubjects:${card.id}`, async () => {
        if (card.locked) throw new Error('提示词卡片已锁定，请先解锁后再匹配主体');
        const saved = await request(`/api/prompt-cards/${card.id}`, {
          method: 'PUT',
          body: JSON.stringify(promptCardPayload(card)),
        });
        setCurrentPromptCards((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        const data = await request(`/api/prompt-cards/${saved.id}/match-subjects`, {
          method: 'POST',
          timeoutMs: LLM_REQUEST_TIMEOUT_MS,
        });
        if (data.card) {
          setCurrentPromptCards((prev) => prev.map((item) => (item.id === data.card.id ? data.card : item)));
        }
        const matchCount = data.matches?.length || 0;
        notify(matchCount ? `已匹配 ${matchCount} 个主体卡片` : '未匹配到主体卡片', matchCount ? 'success' : 'info');
        return data;
      }),
    [notify, run, setCurrentPromptCards],
  );

  const updatePromptCardSubjects = useCallback(
    (card, entityCardIds, options = {}) =>
      run(`updatePromptCardSubjects:${card.id}`, async () => {
        if (card.locked) throw new Error('提示词卡片已锁定，请先解锁后再调整主体');
        if (options.confirmRemoveName) {
          const confirmed = await askConfirm({
            title: '移除匹配主体',
            body: '这里只移除当前提示词卡片和主体卡的绑定，不会删除实体卡或素材文件。',
            confirmLabel: '移除',
            items: [
              { label: '提示词卡片', value: card.title || card.id },
              { label: '主体', value: options.confirmRemoveName },
            ],
          });
          if (!confirmed) return;
        }
        const saved = await request(`/api/prompt-cards/${card.id}`, {
          method: 'PUT',
          body: JSON.stringify(promptCardPayload(card)),
        });
        setCurrentPromptCards((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        const data = await request(`/api/prompt-cards/${saved.id}/subjects`, {
          method: 'PUT',
          body: JSON.stringify({ entity_card_ids: entityCardIds }),
        });
        if (data.card) {
          setCurrentPromptCards((prev) => prev.map((item) => (item.id === data.card.id ? data.card : item)));
        }
        notify(`已更新 ${data.matches?.length || 0} 个匹配主体`, 'success');
        return data;
      }),
    [askConfirm, notify, run, setCurrentPromptCards],
  );

  const togglePromptCardLock = useCallback(
    (card) =>
      run(`togglePromptCardLock:${card.id}`, async () => {
        const nextLocked = !card.locked;
        const saved = await request(`/api/prompt-cards/${card.id}`, {
          method: 'PUT',
          body: JSON.stringify(promptCardPayload(card, { locked: nextLocked })),
        });
        setCurrentPromptCards((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        notify(nextLocked ? '提示词卡片已锁定' : '提示词卡片已解锁', 'success');
        return saved;
      }),
    [notify, run, setCurrentPromptCards],
  );

  const rerunPromptCard = useCallback(
    (card, { maxDurationSeconds } = {}) =>
      run(`rerunPromptCard:${card.id}`, async () => {
        if (!selectedProject || !activeSegment) throw new Error('请先选择项目和分集');
        if (!activeScript.trim()) throw new Error('当前集没有剧本原文');
        if (card.locked) throw new Error('提示词卡片已锁定，请先解锁后再重跑');
        const sourceStart = Number(card.source_start || 0);
        const sourceEnd = Number(card.source_end || 0);
        const confirmed = await askConfirm({
          title: '重跑单张提示词',
          body: '将只重跑当前提示词卡片。系统会把该卡片的剧本来源范围、前后已生成卡片和实体卡库一起传给 LLM。',
          confirmLabel: '重跑本卡',
          items: [
            { label: '卡片', value: card.title || card.id },
            { label: '来源范围', value: sourceEnd > sourceStart ? `${sourceStart + 1}-${sourceEnd}` : '未定位' },
            { label: '上下文卡片', value: promptCards.length },
          ],
        });
        if (!confirmed) return;
        const cardBaseline = `${card.id}:${card.prompt_text || ''}:${Number(card.duration || 0)}`;
        let saved;
        try {
          saved = await request(`/api/prompt-cards/${card.id}/rerun`, {
            method: 'POST',
            timeoutMs: LLM_REQUEST_TIMEOUT_MS,
            body: JSON.stringify({
              script: activeScript,
              template_name_or_id: null,
              max_duration_seconds: Number(maxDurationSeconds || card.duration || promptCardMaxDurationSeconds),
            }),
          });
        } catch (error) {
          if (!isTransientNetworkError(error)) throw error;
          notify('重跑请求已中断或超时，正在轮询后台结果…', 'info');
          const started = Date.now();
          saved = null;
          while (Date.now() - started < LLM_REQUEST_TIMEOUT_MS) {
            await sleep(4000);
            try {
              const data = await request(
                `/api/projects/${selectedProject.id}/segments/${activeSegment.id}/prompt-cards`,
                { timeoutMs: 20000 },
              );
              const next = (data.cards || []).find((item) => item.id === card.id);
              if (next && `${next.id}:${next.prompt_text || ''}:${Number(next.duration || 0)}` !== cardBaseline) {
                saved = next;
                break;
              }
            } catch (_pollError) {
              // keep waiting
            }
          }
          if (!saved) throw error;
        }
        if (!isCurrentProject(selectedProject.id)) return saved;
        setCurrentPromptCards((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        refreshProjectState(selectedProject.id).catch(() => {});
        notify('提示词卡片已重跑', 'success');
        return saved;
      }),
    [
      activeScript,
      activeSegment,
      askConfirm,
      notify,
      promptCards.length,
      refreshProjectState,
      run,
      selectedProject,
      setCurrentPromptCards,
      isCurrentProject,
    ],
  );

  const deletePromptCard = useCallback(
    (card) =>
      run(`deletePromptCard:${card.id}`, async () => {
        if (card.locked) throw new Error('提示词卡片已锁定，请先解锁后再删除');
        const confirmed = await askConfirm({
          title: '删除提示词卡片',
          body: '删除后该卡片对应的视频生成入口会一并移除，不会影响本集剧本。',
          tone: 'danger',
          confirmLabel: '删除',
          items: [
            { label: '卡片', value: card.title || card.id },
            { label: '预计时长', value: `${Math.round(Number(card.duration || 0)) || 0} 秒` },
          ],
        });
        if (!confirmed) return;
        await request(`/api/prompt-cards/${card.id}`, { method: 'DELETE' });
        if (!isCurrentProject(currentProjectId)) return;
        setCurrentPromptCards((prev) => prev.filter((item) => item.id !== card.id));
        refreshProjectState(selectedProject?.id).catch((error) => notify(error.message, 'error'));
        notify('提示词卡片已删除', 'success');
      }),
    [askConfirm, currentProjectId, isCurrentProject, notify, refreshProjectState, run, selectedProject?.id, setCurrentPromptCards],
  );

  const resolveMentions = useCallback(
    (card, options = {}) =>
      run(`resolveMentions:${card.id}`, async () => {
        const data = await request(`/api/prompt-cards/${card.id}/resolve-mentions`, {
          method: 'POST',
          body: JSON.stringify({
            prompt_text: options.prompt_text ?? card.prompt_text ?? '',
            existing_anchor_text: options.existing_anchor_text ?? card.anchor_text ?? '',
            apply: Boolean(options.apply),
          }),
        });
        if (data.card) {
          setCurrentPromptCards((prev) => prev.map((item) => (item.id === data.card.id ? data.card : item)));
        }
        const missing = Array.isArray(data.missing) ? data.missing : [];
        notify(
          missing.length
            ? `已解析 ${data.entity_card_ids?.length || 0} 个主体，未匹配：${missing.join('、')}`
            : `已解析 ${data.entity_card_ids?.length || 0} 个 @ 主体`,
          missing.length ? 'error' : 'success',
        );
        return data;
      }),
    [notify, run, setCurrentPromptCards],
  );

  const generatePromptCardVideo = useCallback(
    (card) =>
      run(`generatePromptCardVideo:${card.id}`, async () => {
        if (!selectedProject || !activeSegment) throw new Error('请先选择项目和分集');
        if (!card.prompt_text?.trim()) throw new Error('提示词卡片为空，无法生成视频请求');
        const settings = await askVideoRequest(card);
        if (!settings) return;
        const persistedSettings = sanitizeVideoRequestSettings(settings, videoProvider);
        setVideoRequestSettings(persistedSettings);
        writeVideoRequestSettings(persistedSettings, videoProvider);
        const duration = Math.round(Number(persistedSettings.duration || card.duration || 0)) || null;
        const model = String(persistedSettings.model || '').trim() || null;
        const data = await createPromptCardVideoTask(card.id, {
          duration,
          model,
          aspect_ratio: persistedSettings.aspectRatio || null,
          resolution: persistedSettings.resolution || null,
          preview: false,
          assets: {},
          reference_mode: persistedSettings.referenceMode || 'omni',
          first_frame: persistedSettings.firstFrame || null,
          last_frame: persistedSettings.lastFrame || null,
          reference_images: persistedSettings.referenceImages || [],
          reference_videos: persistedSettings.referenceVideos || [],
          reference_audios: persistedSettings.referenceAudios || [],
          generate_audio: persistedSettings.generateAudio !== false,
        });
        if (!isCurrentProject(selectedProject.id)) return data;
        prependVideoTask(data, {
          segmentOrder: activeSegment.order,
          prompt: data.prompt || card.prompt_text,
        });
        refreshProjectState(selectedProject.id).catch((error) => notify(error.message, 'error'));
        notify(`视频任务已提交：${data.api_task_id || data.id}（后台生成中）`, 'success');
        return data;
      }),
    [
      activeSegment,
      askVideoRequest,
      isCurrentProject,
      notify,
      refreshProjectState,
      run,
      selectedProject,
      setVideoRequestSettings,
      videoProvider,
      prependVideoTask,
    ],
  );

  return {
    generatePromptCards,
    savePromptCard,
    matchPromptCardSubjects,
    updatePromptCardSubjects,
    togglePromptCardLock,
    rerunPromptCard,
    deletePromptCard,
    resolveMentions,
    generatePromptCardVideo,
  };
}
