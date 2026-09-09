import { useCallback } from 'react';

import { LLM_REQUEST_TIMEOUT_MS, request } from '../api/client';
import { saveSegmentScript } from '../api/workspace';
import { normalizeEpisodeSegments } from '../app/uiStorage';
import { useProjectScope } from './useProjectScope';
import { requireProjectAndSegments } from '../utils';

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      resolve(result.includes(',') ? result.split(',').pop() : result);
    };
    reader.onerror = () => reject(reader.error || new Error('文件读取失败'));
    reader.readAsDataURL(file);
  });
}

function splitRequestBody(workspace, content, strategy = workspace.splitStrategy) {
  const normalizedStrategy = strategy === 'duration_2min' ? 'duration' : strategy;
  return {
    content,
    strategy: normalizedStrategy,
    max_chars: 1200,
    custom_pattern: workspace.customSplitPattern || '',
    duration_minutes: Number(workspace.durationMinutes || 2),
  };
}

function scriptMetaFromConversion(data) {
  const valid = Boolean(data.validation?.valid);
  return {
    ...data.validation,
    status: valid ? (data.source_format === 'script' ? 'script' : 'converted') : 'invalid',
    confirmed: false,
    source_format: data.source_format,
    format_decision: data.format_decision,
    error: '',
  };
}

function assertScriptHandlingChoice(sourceFormat) {
  if (sourceFormat !== 'script' && sourceFormat !== 'source_text') {
    throw new Error('请选择：直接转存或 LLM 转写成剧本');
  }
}

/** 剧本仍是「进入剧本处理」时从分集原文直接导入，未经 LLM/转存转换。 */
function isDirectImportScript(validation) {
  return validation?.status === 'imported';
}

function reconvertFormatFor(validation) {
  return validation?.source_format === 'script' ? 'script' : 'source_text';
}

export function usePreprocess({
  run,
  notify,
  askConfirm,
  selectedProject,
  workspace,
  workspaceRef,
  activeSegment,
  videoTasks,
  setSplitSuggestions,
  setPromptCards,
  updateWorkspace,
  refreshVideoTasks,
  refreshProjectState,
  refreshWorkspace,
  applyWorkspaceResponse,
  syncWorkspacePatch,
}) {
  const isCurrentProject = useProjectScope(selectedProject?.id);

  const splitDocument = useCallback(
    () =>
      run('split', async () => {
        const projectId = selectedProject?.id || '';
        const data = await request('/api/documents/split/suggest', {
          method: 'POST',
          timeoutMs: LLM_REQUEST_TIMEOUT_MS,
          body: JSON.stringify(splitRequestBody(workspace, workspace.documentText)),
        });
        if (!isCurrentProject(projectId)) return data.suggestions;
        setSplitSuggestions(data.suggestions);
        notify('切分建议已生成，请选择一个方案落盘', 'success');
      }),
    [isCurrentProject, notify, run, selectedProject?.id, setSplitSuggestions, workspace],
  );

  const applySplitSuggestion = useCallback(
    (strategy) =>
      run('applySplit', async () => {
        const projectId = selectedProject?.id || '';
        const downstreamCounts = {
          scripts: Object.keys(workspace.scripts).length,
          entities: workspace.entities.length,
          prompts: Object.keys(workspace.prompts).length,
          videoTasks: videoTasks.length,
        };
        const hasDownstream =
          downstreamCounts.scripts ||
          downstreamCounts.entities ||
          downstreamCounts.prompts ||
          downstreamCounts.videoTasks;
        if (hasDownstream) {
          const confirmed = await askConfirm({
            title: '确认重新切分',
            body: '重新切分会清空当前项目的下游内容，建议只在需要重做结构时执行。',
            tone: 'danger',
            confirmLabel: '重新切分',
            items: [
              { label: '脚本', value: downstreamCounts.scripts },
              { label: '实体', value: downstreamCounts.entities },
              { label: '提示词', value: downstreamCounts.prompts },
              { label: '视频任务', value: downstreamCounts.videoTasks },
            ],
          });
          if (!confirmed) return;
        }
        const data = await request('/api/documents/split', {
          method: 'POST',
          body: JSON.stringify({
            ...splitRequestBody(workspace, workspace.documentText, strategy),
            project_id: projectId || null,
            persist: Boolean(projectId),
            mark_orphaned_tasks: true,
          }),
        });
        if (!isCurrentProject(projectId)) return data;
        let episodeCount = 0;
        if (data.workspace && Object.keys(data.workspace).length) {
          const episodes = normalizeEpisodeSegments(data.workspace.segments || []);
          episodeCount = episodes.length;
          applyWorkspaceResponse({
            ...data.workspace,
            segments: episodes,
            activeSegmentId: data.workspace.activeSegmentId || episodes[0]?.id || '',
          });
        } else {
          const episodes = normalizeEpisodeSegments(data.segments);
          episodeCount = episodes.length;
          updateWorkspace({
            splitStrategy: strategy,
            segments: episodes,
            activeSegmentId: episodes[0]?.id || '',
            clearDownstream: true,
            scripts: {},
            scriptValidation: {},
            assetsConfirmed: false,
          });
        }
        setPromptCards([]);
        setSplitSuggestions([]);
        if (selectedProject?.id) {
          await refreshVideoTasks(selectedProject.id);
          await refreshProjectState(selectedProject.id);
        }
        const orphaned = Number(data.orphaned_task_count || 0);
        notify(
          orphaned
            ? `预处理完成：${episodeCount} 集；已标记 ${orphaned} 个历史视频任务为孤儿`
            : `预处理完成：${episodeCount} 集`,
          'success',
        );
      }),
    [
      applyWorkspaceResponse,
      askConfirm,
      isCurrentProject,
      notify,
      refreshProjectState,
      refreshVideoTasks,
      run,
      selectedProject?.id,
      setPromptCards,
      setSplitSuggestions,
      updateWorkspace,
      videoTasks.length,
      workspace,
    ],
  );

  const uploadProjectDocument = useCallback(
    (file) =>
      run('uploadDocument', async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        if (!file) return;
        const contentBase64 = await fileToBase64(file);
        const data = await request(`/api/projects/${selectedProject.id}/documents/upload`, {
          method: 'POST',
          body: JSON.stringify({
            filename: file.name,
            content_base64: contentBase64,
          }),
        });
        if (!isCurrentProject(projectId)) return data;
        setSplitSuggestions([]);
        if (data.workspace && typeof data.workspace === 'object') {
          applyWorkspaceResponse(data.workspace);
        } else {
          await refreshWorkspace(selectedProject.id);
        }
        await refreshProjectState(selectedProject.id);
        notify(`文档已导入：${data.document.filename}`, 'success');
      }),
    [
      applyWorkspaceResponse,
      isCurrentProject,
      notify,
      refreshProjectState,
      refreshWorkspace,
      run,
      selectedProject,
      setSplitSuggestions,
    ],
  );

  const convertCurrentSegment = useCallback(
    (sourceFormat) =>
      run('convertCurrent', async () => {
        const projectId = selectedProject?.id || '';
        if (!activeSegment) throw new Error('请选择片段');
        assertScriptHandlingChoice(sourceFormat);
        const currentWorkspace = workspaceRef.current || workspace;
        if (String(currentWorkspace.scripts?.[activeSegment.id] || '').trim()) {
          const confirmed = await askConfirm({
            title: '重新转换本集剧本',
            body: '将按当前转换模板和输入类型覆盖本集剧本。现有实体、资产提示词和生成图片不会自动改动；需要同步时请在后续步骤主动重新分析或重新生成。',
            tone: 'danger',
            confirmLabel: '重新转换',
            items: [{ label: '分集', value: activeSegment.title || `第${activeSegment.order}集` }],
          });
          if (!confirmed) return;
        }
        const data = await request('/api/segments/convert', {
          method: 'POST',
          timeoutMs: LLM_REQUEST_TIMEOUT_MS,
          body: JSON.stringify({
            segment_id: activeSegment.id,
            order: activeSegment.order,
            content: activeSegment.content,
            source_format: sourceFormat,
            content_type: workspaceRef.current?.contentType || '分集原文',
            template_id: workspaceRef.current?.scriptConvertTemplateId || null,
          }),
        });
        if (!isCurrentProject(projectId)) return data;
        const validation = scriptMetaFromConversion(data);
        if (projectId) {
          const revision = workspaceRef.current?.revision ?? workspace.revision;
          const saved = await saveSegmentScript(projectId, activeSegment.id, {
            content: data.script.content,
            validation,
            revision,
          });
          if (!isCurrentProject(projectId)) return saved;
          applyWorkspaceResponse(saved);
          await refreshProjectState(projectId);
        } else {
          updateWorkspace((prev) => ({
            ...prev,
            scripts: { ...prev.scripts, [activeSegment.id]: data.script.content },
            scriptValidation: {
              ...prev.scriptValidation,
              [activeSegment.id]: validation,
            },
          }));
        }
        notify(
          data.source_format === 'script'
            ? `片段 ${activeSegment.order} 已直接转存为脚本`
            : `片段 ${activeSegment.order} 已完成 LLM 转写`,
          data.validation.valid ? 'success' : 'error',
        );
      }),
    [
      activeSegment,
      applyWorkspaceResponse,
      askConfirm,
      isCurrentProject,
      notify,
      refreshProjectState,
      run,
      selectedProject?.id,
      updateWorkspace,
      workspace,
      workspaceRef,
    ],
  );

  const convertAllSegments = useCallback(
    () =>
      run('convertAll', async () => {
        requireProjectAndSegments(workspace, selectedProject);
        const projectId = selectedProject.id;
        const current = workspaceRef.current || workspace;
        const segments = current.segments || [];
        if (!segments.length) throw new Error('请先完成文本切分');
        const confirmed = await askConfirm({
          title: '全部重新转换',
          body: '将按当前转换模板和输入类型覆盖全部剧本。现有实体、资产提示词和生成图片不会自动改动；需要同步时请在后续步骤主动重新分析或重新生成。',
          tone: 'danger',
          confirmLabel: '全部重新转换',
          items: [{ label: '分集数', value: segments.length }],
        });
        if (!confirmed) return;

        let okCount = 0;
        let failCount = 0;
        for (const segment of segments) {
          if (!isCurrentProject(projectId)) break;
          const sourceFormat = reconvertFormatFor(current.scriptValidation?.[segment.id]);
          try {
            const data = await request('/api/segments/convert', {
              method: 'POST',
              timeoutMs: LLM_REQUEST_TIMEOUT_MS,
              body: JSON.stringify({
                segment_id: segment.id,
                order: segment.order,
                content: segment.content,
                source_format: sourceFormat,
                content_type: current.contentType || '分集原文',
                template_id: current.scriptConvertTemplateId || null,
              }),
            });
            if (!isCurrentProject(projectId)) break;
            const validation = scriptMetaFromConversion(data);
            if (projectId) {
              const revision = workspaceRef.current?.revision;
              const saved = await saveSegmentScript(projectId, segment.id, {
                content: data.script.content,
                validation,
                revision,
              });
              if (!isCurrentProject(projectId)) break;
              applyWorkspaceResponse(saved);
            } else {
              updateWorkspace((prev) => ({
                ...prev,
                scripts: { ...prev.scripts, [segment.id]: data.script.content },
                scriptValidation: {
                  ...prev.scriptValidation,
                  [segment.id]: validation,
                },
              }));
            }
            okCount += 1;
          } catch (_error) {
            failCount += 1;
          }
        }
        if (!isCurrentProject(projectId)) return { okCount, failCount, cancelled: true };
        if (projectId) await refreshProjectState(projectId);
        notify(
          failCount
            ? `全部转换完成：成功 ${okCount} 集，失败 ${failCount} 集`
            : `全部转换完成：${okCount} 集`,
          failCount ? 'error' : 'success',
        );
      }),
    [
      applyWorkspaceResponse,
      askConfirm,
      isCurrentProject,
      notify,
      refreshProjectState,
      run,
      selectedProject,
      updateWorkspace,
      workspace,
      workspaceRef,
    ],
  );

  const saveAllSegmentSources = useCallback(
    () =>
      run('saveSegments', async () => {
        requireProjectAndSegments(workspace, selectedProject);
        const current = workspaceRef.current;
        const patch = {
          segments: current.segments,
          activeSegmentId: current.activeSegmentId,
        };
        // 仅同步「直接导入、未经转换」的剧本，与分集原文保持一致。
        const scripts = { ...(current.scripts || {}) };
        const scriptValidation = { ...(current.scriptValidation || {}) };
        let synced = 0;
        (current.segments || []).forEach((segment) => {
          if (!Object.prototype.hasOwnProperty.call(scripts, segment.id)) return;
          if (!isDirectImportScript(scriptValidation[segment.id])) return;
          scripts[segment.id] = segment.content || '';
          scriptValidation[segment.id] = {
            ...(scriptValidation[segment.id] || {}),
            valid: false,
            status: 'imported',
            confirmed: false,
            reason: '已随保存的分集原文同步',
            error: '',
            source_format: 'source_text',
          };
          synced += 1;
        });
        if (synced) {
          patch.scripts = scripts;
          patch.scriptValidation = scriptValidation;
        }
        await syncWorkspacePatch(patch, selectedProject?.id);
        notify(
          synced
            ? `已保存 ${current.segments.length} 集分集原文，并同步 ${synced} 集直接导入剧本`
            : `已保存 ${current.segments.length} 集分集原文`,
          'success',
        );
      }),
    [notify, run, selectedProject, syncWorkspacePatch, workspace, workspaceRef],
  );

  const saveActiveSegmentSource = useCallback(
    () =>
      run('saveActiveSegment', async () => {
        requireProjectAndSegments(workspace, selectedProject);
        if (!activeSegment) throw new Error('请选择分集');
        const current = workspaceRef.current;
        const patch = {
          segments: current.segments,
          activeSegmentId: current.activeSegmentId,
        };
        const hasScript = Object.prototype.hasOwnProperty.call(current.scripts || {}, activeSegment.id);
        const meta = current.scriptValidation?.[activeSegment.id];
        if (hasScript && isDirectImportScript(meta)) {
          const segment = current.segments.find((item) => item.id === activeSegment.id) || activeSegment;
          patch.scripts = {
            ...(current.scripts || {}),
            [activeSegment.id]: segment.content || '',
          };
          patch.scriptValidation = {
            ...(current.scriptValidation || {}),
            [activeSegment.id]: {
              ...(meta || {}),
              valid: false,
              status: 'imported',
              confirmed: false,
              reason: '已随保存的分集原文同步',
              error: '',
              source_format: 'source_text',
            },
          };
        }
        await syncWorkspacePatch(patch, selectedProject?.id);
        notify(
          hasScript && isDirectImportScript(meta)
            ? `第 ${activeSegment.order} 集原文已保存，并同步到剧本`
            : `第 ${activeSegment.order} 集原文已保存`,
          'success',
        );
      }),
    [activeSegment, notify, run, selectedProject, syncWorkspacePatch, workspace, workspaceRef],
  );

  const enterScriptStage = useCallback(
    () =>
      run('enterScriptStage', async () => {
        const current = workspaceRef.current || workspace;
        requireProjectAndSegments(current, selectedProject);
        let importedCount = 0;
        const scripts = { ...(current.scripts || {}) };
        const scriptValidation = { ...(current.scriptValidation || {}) };
        (current.segments || []).forEach((segment) => {
          if (String(scripts[segment.id] || '').trim()) return;
          scripts[segment.id] = segment.content || '';
          scriptValidation[segment.id] = {
            ...(scriptValidation[segment.id] || {}),
            valid: false,
            status: 'imported',
            confirmed: false,
            reason: '已导入分集原文，请按需要编辑或重新转换',
            error: '',
            source_format: 'source_text',
          };
          importedCount += 1;
        });
        const activeSegmentId = current.activeSegmentId || current.segments[0]?.id || '';
        const patch = { scripts, scriptValidation, activeSegmentId };
        if (selectedProject?.id) {
          await syncWorkspacePatch(patch, selectedProject?.id);
        } else {
          updateWorkspace(patch);
        }
        notify(importedCount ? `已导入 ${importedCount} 集到剧本处理` : '所有分集已在剧本处理中', 'success');
        return true;
      }),
    [notify, run, selectedProject, syncWorkspacePatch, updateWorkspace, workspace, workspaceRef],
  );

  const saveAllScriptSources = useCallback(
    () =>
      run('saveScripts', async () => {
        requireProjectAndSegments(workspace, selectedProject);
        const current = workspaceRef.current;
        await syncWorkspacePatch({
          scripts: current.scripts,
          scriptValidation: current.scriptValidation,
        }, selectedProject?.id);
        const scriptCount = current.segments.filter((segment) => current.scripts?.[segment.id]?.trim()).length;
        notify(`已保存 ${scriptCount} 集剧本原文`, 'success');
      }),
    [notify, run, selectedProject, syncWorkspacePatch, workspace, workspaceRef],
  );

  const saveActiveScriptSource = useCallback(
    () =>
      run('saveActiveScript', async () => {
        requireProjectAndSegments(workspace, selectedProject);
        if (!activeSegment) throw new Error('请选择分集');
        const current = workspaceRef.current;
        await syncWorkspacePatch({
          scripts: { [activeSegment.id]: current.scripts?.[activeSegment.id] ?? '' },
          scriptValidation: { [activeSegment.id]: current.scriptValidation?.[activeSegment.id] ?? {} },
        }, selectedProject?.id);
        notify(`第 ${activeSegment.order} 集剧本已保存`, 'success');
      }),
    [activeSegment, notify, run, selectedProject, syncWorkspacePatch, workspace, workspaceRef],
  );

  const updateActiveScript = useCallback(
    (value) => {
      if (!activeSegment) return;
      updateWorkspace((prev) => ({
        ...prev,
        scripts: { ...prev.scripts, [activeSegment.id]: value },
        scriptValidation: {
          ...prev.scriptValidation,
          [activeSegment.id]: {
            ...(prev.scriptValidation?.[activeSegment.id] || {}),
            valid: false,
            status: 'edited',
            confirmed: false,
            reason: value.trim() ? '脚本已编辑，请人工确认' : '脚本为空',
            error: '',
          },
        },
      }));
    },
    [activeSegment, updateWorkspace],
  );

  return {
    splitDocument,
    applySplitSuggestion,
    uploadProjectDocument,
    convertCurrentSegment,
    convertAllSegments,
    saveAllSegmentSources,
    saveActiveSegmentSource,
    enterScriptStage,
    saveAllScriptSources,
    saveActiveScriptSource,
    updateActiveScript,
  };
}
