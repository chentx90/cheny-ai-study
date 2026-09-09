import { useCallback, useEffect, useRef, useState } from 'react';

import {
  adoptVideoOutput as adoptVideoOutputApi,
  deleteVideoTask as deleteVideoTaskApi,
  listVideoOutputs,
  listVideoTasks,
  recoverVideoTask as recoverVideoTaskApi,
  retryVideoTask as retryVideoTaskApi,
  videoTaskDownloadUrl,
} from '../api/video';
import { downloadRemoteFile } from '../utils/download';
import { displayResultFilename } from '../views/video/videoViewUtils';

export function useVideoTasks({ run, notify, askConfirm, askVideoRetry, selectedProject, refreshProjectState, apiBase = '' }) {
  const [videoTasks, setVideoTasks] = useState([]);
  const [videoOutputs, setVideoOutputs] = useState([]);
  const taskRefreshSequence = useRef(0);
  const outputRefreshSequence = useRef(0);

  const refreshVideoOutputs = useCallback(async (projectId = selectedProject?.id) => {
    const sequence = ++outputRefreshSequence.current;
    if (!projectId) {
      setVideoOutputs([]);
      return [];
    }
    const data = await listVideoOutputs(projectId);
    if (sequence === outputRefreshSequence.current) setVideoOutputs(data.outputs || []);
    return data.outputs || [];
  }, [selectedProject?.id]);

  const refreshVideoTasks = useCallback(async (projectId = selectedProject?.id, { sync = false } = {}) => {
    const sequence = ++taskRefreshSequence.current;
    if (!projectId) {
      setVideoTasks([]);
      setVideoOutputs([]);
      return [];
    }
    const data = await listVideoTasks(projectId, { sync });
    if (sequence !== taskRefreshSequence.current) return data.tasks;
    setVideoTasks(data.tasks);
    await refreshVideoOutputs(projectId);
    return data.tasks;
  }, [refreshVideoOutputs, selectedProject?.id]);

  const syncVideoTasks = useCallback(
    (projectId = selectedProject?.id) =>
      run('syncVideoTasks', async () => {
        const tasks = await refreshVideoTasks(projectId, { sync: true });
        const processing = tasks.filter((task) => task.status === 'processing').length;
        const failed = tasks.filter((task) => task.status === 'failed').length;
        const completed = tasks.filter((task) => task.status === 'completed').length;
        if (processing) {
          notify(`已同步：${processing} 个任务仍在生成中`, 'info');
        } else if (failed) {
          notify(`已同步：${failed} 个任务失败，${completed} 个已完成`, failed ? 'error' : 'success');
        } else if (completed) {
          notify(`已同步：${completed} 个任务已完成`, 'success');
        } else {
          notify('任务状态已同步', 'success');
        }
        return tasks;
      }),
    [notify, refreshVideoTasks, run, selectedProject?.id],
  );

  const prependVideoTask = useCallback((task, meta = {}) => {
    setVideoTasks((prev) => [
      {
        ...task,
        ...meta,
        createdAt: meta.createdAt || new Date().toISOString(),
      },
      ...prev.filter((item) => item.id !== task.id),
    ]);
  }, []);

  const retryVideoTask = useCallback(
    (task) =>
      run(`retryVideoTask:${task.id}`, async () => {
        const settings = await askVideoRetry?.(task);
        if (!settings) return;
        const prompt = String(settings.prompt || '').trim();
        if (!prompt) {
          notify('提示词不能为空', 'error');
          return;
        }
        const data = await retryVideoTaskApi(task.id, {
          prompt,
          duration: Math.round(Number(settings.duration || 0)) || null,
          model: String(settings.model || '').trim() || null,
          aspect_ratio: settings.aspectRatio || null,
          resolution: settings.resolution || null,
          reference_mode: settings.referenceMode || 'omni',
          first_frame: settings.firstFrame || null,
          last_frame: settings.lastFrame || null,
          reference_images: settings.referenceImages || [],
          reference_videos: settings.referenceVideos || [],
          reference_audios: settings.referenceAudios || [],
          generate_audio: settings.generateAudio !== false,
        });
        prependVideoTask(data, {
          segmentOrder: task.segmentOrder,
          prompt: data.prompt || prompt,
        });
        refreshProjectState(selectedProject?.id).catch((error) => notify(error.message, 'error'));
        notify(`任务已重试：${data.api_task_id || data.id}`, 'success');
      }),
    [askVideoRetry, notify, prependVideoTask, refreshProjectState, run, selectedProject?.id],
  );

  const downloadVideoTask = useCallback(
    (task) =>
      run(`downloadVideoTask:${task.id}`, async () => {
        let current = task;
        if (!current.result_path && current.api_task_id) {
          const data = await recoverVideoTaskApi(task.id, current.api_task_id);
          current = {
            ...data,
            segmentOrder: task.segmentOrder,
            prompt: data.prompt || task.prompt,
            createdAt: task.createdAt || task.created_at,
          };
          setVideoTasks((prev) => prev.map((item) => (item.id === data.id ? { ...item, ...current } : item)));
          if (current.status === 'completed' && current.result_path) {
            await refreshVideoOutputs(selectedProject?.id);
          }
          refreshProjectState(selectedProject?.id).catch((error) => notify(error.message, 'error'));
          if (current.status !== 'completed' || !current.result_path) {
            notify(current.error_message || '视频尚未就绪，请稍后再试', 'error');
            return null;
          }
        }
        if (!current.result_path) {
          notify('视频尚未就绪', 'error');
          return null;
        }
        const url = videoTaskDownloadUrl(apiBase, current.id);
        const filename = displayResultFilename(current.result_path);
        await downloadRemoteFile(url, filename);
        notify(`已开始下载：${filename}`, 'success');
        return current;
      }),
    [apiBase, notify, refreshProjectState, refreshVideoOutputs, run, selectedProject?.id],
  );

  const recoverVideoTask = useCallback(
    (task, apiTaskId) =>
      run(`recoverVideoTask:${task.id}`, async () => {
        const remoteId = String(apiTaskId || task.api_task_id || '').trim();
        if (!remoteId) {
          notify('没有远端任务 ID，请在详情里粘贴网关返回的 task id 后再追回', 'error');
          return null;
        }
        const data = await recoverVideoTaskApi(task.id, remoteId);
        const next = {
          ...data,
          segmentOrder: task.segmentOrder,
          prompt: data.prompt || task.prompt,
          createdAt: task.createdAt || task.created_at,
        };
        setVideoTasks((prev) => prev.map((item) => (item.id === data.id ? { ...item, ...next } : item)));
        if (data.status === 'completed' && data.result_path) {
          await refreshVideoOutputs(selectedProject?.id);
        }
        refreshProjectState(selectedProject?.id).catch((error) => notify(error.message, 'error'));
        if (data.status === 'completed') {
          notify(`已追回成片：${data.api_task_id}`, 'success');
        } else if (data.status === 'processing') {
          notify(`远端任务仍在生成中：${data.api_task_id}`, 'info');
        } else {
          notify(data.error_message || `追回未完成：${data.status}`, 'error');
        }
        return next;
      }),
    [notify, refreshProjectState, refreshVideoOutputs, run, selectedProject?.id],
  );

  const deleteVideoTask = useCallback(
    (task) =>
      run(`deleteVideoTask:${task.id}`, async () => {
        const confirmed = await askConfirm({
          title: '删除视频任务',
          body: '这里只删除任务记录，已生成的归档文件不会从项目目录中移除。',
          tone: 'danger',
          confirmLabel: '删除',
          items: [
            { label: '片段', value: task.segmentOrder || task.segment_id },
            { label: '任务', value: `${task.is_preview ? '预览' : '完整'} / v${task.version}` },
            { label: '状态', value: task.status },
          ],
        });
        if (!confirmed) return;
        await deleteVideoTaskApi(task.id);
        setVideoTasks((prev) => prev.filter((item) => item.id !== task.id));
        setVideoOutputs((prev) => prev.filter((item) => item.video_task_id !== task.id));
        refreshProjectState(selectedProject?.id).catch((error) => notify(error.message, 'error'));
        notify('视频任务记录已删除', 'success');
      }),
    [askConfirm, notify, refreshProjectState, run, selectedProject?.id],
  );

  const adoptVideoOutput = useCallback(
    (output) =>
      run(`adoptVideoOutput:${output.id}`, async () => {
        const confirmed = await askConfirm({
          title: '采用该视频结果',
          body: '采用后，这条结果将成为当前提示词卡片的正式成片。已有采用结果会保留为候选。',
          confirmLabel: '采用',
          items: [
            { label: '版本', value: `v${output.metadata?.version || 1}` },
            { label: '文件', value: displayResultFilename(output.storage_path) },
          ],
        });
        if (!confirmed) return null;
        const data = await adoptVideoOutputApi(output.project_id, output.id);
        const adopted = data.output;
        setVideoOutputs((prev) =>
          prev.map((item) => ({
            ...item,
            adopted: item.prompt_card_id === adopted.prompt_card_id ? item.id === adopted.id : item.adopted,
          })),
        );
        notify('已采用该视频结果', 'success');
        return adopted;
      }),
    [askConfirm, notify, run],
  );

  useEffect(() => {
    if (!selectedProject?.id) return undefined;
    const hasProcessing = videoTasks.some((task) => task.status === 'processing');
    const intervalMs = hasProcessing ? 3000 : 15000;
    const timer = window.setInterval(() => {
      refreshVideoTasks(selectedProject.id, { sync: hasProcessing }).catch(() => {});
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [selectedProject?.id, videoTasks.some((task) => task.status === 'processing'), refreshVideoTasks]);

  return {
    videoTasks,
    setVideoTasks,
    videoOutputs,
    setVideoOutputs,
    refreshVideoTasks,
    refreshVideoOutputs,
    syncVideoTasks,
    prependVideoTask,
    retryVideoTask,
    recoverVideoTask,
    downloadVideoTask,
    deleteVideoTask,
    adoptVideoOutput,
  };
}
