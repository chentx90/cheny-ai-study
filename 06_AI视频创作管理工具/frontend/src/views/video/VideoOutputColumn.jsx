import React, { useMemo, useState } from 'react';
import { Check, Download, Film, RefreshCw, Trash2 } from 'lucide-react';
import PanelTitle from '../../components/PanelTitle';
import VideoTaskDetailDialog, { VideoTaskDetailTrigger } from './VideoTaskDetailDialog';
import {
  buildGeneratedUrl,
  buildTaskDownloadUrl,
  displayResultFilename,
  formatSeconds,
  providerDisplayLabel,
  taskSettingSummary,
  taskStatusHint,
  videoRuntimeInfo,
} from './videoViewUtils';

function statusLabel(status) {
  const map = {
    completed: '已完成',
    processing: '生成中',
    failed: '失败',
    pending: '等待中',
  };
  return map[status] || status;
}

export default function VideoOutputColumn({
  apiBase,
  selectedProject,
  apiConfig = {},
  activeShot,
  shotTasks = [],
  shotOutputs = [],
  activeTasks = [],
  retryVideoTask,
  downloadVideoTask,
  recoverVideoTask,
  deleteVideoTask,
  syncVideoTasks,
  adoptVideoOutput,
  syncBusy = false,
  recoverBusyId = '',
  downloadBusyId = '',
}) {
  const runtime = videoRuntimeInfo(apiConfig);
  const latest = shotTasks[0] || null;
  const adoptedOutput = shotOutputs.find((output) => output.adopted) || null;
  const monitorOutput = adoptedOutput || shotOutputs[0] || null;
  const monitorTask = monitorOutput
    ? shotTasks.find((task) => task.id === monitorOutput.video_task_id) || latest
    : latest;
  const monitorPath = monitorOutput?.storage_path || monitorTask?.result_path || '';
  const resultUrl = monitorPath
    ? buildTaskDownloadUrl(apiBase, monitorTask, { inline: true }) || buildGeneratedUrl(apiBase, selectedProject, monitorPath)
    : '';
  const currentTasks = useMemo(() => activeTasks.filter((task) => !task.orphaned), [activeTasks]);
  const orphanedTasks = useMemo(() => activeTasks.filter((task) => task.orphaned), [activeTasks]);
  const hasProcessing = useMemo(() => currentTasks.some((task) => task.status === 'processing'), [currentTasks]);
  const [detailTask, setDetailTask] = useState(null);
  const monitorHint = monitorTask ? taskStatusHint(monitorTask) : '';

  return (
    <section className="panel video-output-panel">
      <PanelTitle icon={Film} title="成片与任务">
        <button
          type="button"
          className="secondary compact"
          disabled={syncBusy || !selectedProject?.id}
          title="向远端网关查询最新状态"
          onClick={() => syncVideoTasks?.(selectedProject?.id)}
        >
          <RefreshCw className={syncBusy || hasProcessing ? 'spin' : undefined} />
          同步状态
        </button>
        <span className={`video-output-runtime ${runtime.ready ? 'is-ready' : 'is-pending'}`}>{runtime.pill}</span>
      </PanelTitle>

      <div className="video-output-body">
        <div className="video-output-monitor">
          <div className="video-output-section-head">
            <strong>监视器</strong>
            {activeShot ? (
              <span>
                {activeShot.title || `镜头 ${activeShot.order}`} · {formatSeconds(activeShot.duration)}
              </span>
            ) : (
              <span className="video-output-muted">未选择镜头</span>
            )}
          </div>

          {!activeShot && <p className="video-output-empty">选择提示词卡片以预览成片</p>}
          {activeShot && !monitorTask && <p className="video-output-empty">该提示词卡片暂无视频任务，点击「生成视频请求」开始</p>}
          {activeShot && monitorTask && (
            <div className="video-output-monitor-body">
              <div className="video-output-task-meta">
                <span>{monitorTask.is_preview ? '预览' : '完整'}</span>
                <span>v{monitorTask.version}</span>
                {monitorOutput?.adopted && <span className="video-output-adopted">已采用</span>}
                <span className={`video-output-status is-${monitorTask.status}`}>{statusLabel(monitorTask.status)}</span>
              </div>
              {monitorTask.status === 'processing' && (
                <p className="monitor-processing">{monitorHint || '视频生成中，请稍候…'}</p>
              )}
              {monitorTask.status === 'completed' && resultUrl && (
                <video className="monitor-player" src={resultUrl} controls />
              )}
              {monitorTask.error_message && <p className="monitor-error">{monitorTask.error_message}</p>}
              {monitorTask.api_task_id && (
                <small className="video-output-task-note mono">远端：{monitorTask.api_task_id}</small>
              )}
            </div>
          )}
        </div>

        <div className="video-output-candidates">
          <div className="video-output-section-head">
            <strong>候选结果</strong>
            <span>{shotOutputs.length} 个</span>
          </div>
          {shotOutputs.length === 0 ? (
            <p className="video-output-empty">任务完成并下载后会出现在这里</p>
          ) : (
            <div className="video-output-candidate-list">
              {shotOutputs.map((output) => {
                const task = shotTasks.find((item) => item.id === output.video_task_id);
                return (
                  <article className={`video-output-candidate ${output.adopted ? 'is-adopted' : ''}`} key={output.id}>
                    <div>
                      <strong>v{output.metadata?.version || task?.version || 1}</strong>
                      <span>{displayResultFilename(output.storage_path)}</span>
                    </div>
                    <div className="video-output-candidate-actions">
                      {task && (
                        <button type="button" className="icon-button" title="下载候选视频" onClick={() => downloadVideoTask?.(task)}>
                          <Download />
                        </button>
                      )}
                      <button
                        type="button"
                        className={output.adopted ? 'secondary compact is-selected' : 'secondary compact'}
                        disabled={output.adopted}
                        onClick={() => adoptVideoOutput?.(output)}
                      >
                        <Check />
                        {output.adopted ? '已采用' : '采用'}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>

        <div className="video-output-tasks">
          <div className="video-output-section-head">
            <strong>任务列表</strong>
            <span>{currentTasks.length} 个当前任务</span>
          </div>

          {currentTasks.length === 0 && orphanedTasks.length === 0 ? (
            <p className="video-output-empty">暂无当前集视频任务</p>
          ) : (
            <div className="video-output-task-list">
              {currentTasks.map((task) => (
                <article className="video-output-task-item" key={task.id}>
                  <div className="video-output-task-main">
                    <strong>
                      {task.is_preview ? '预览' : '完整'} / v{task.version}
                      <em>{providerDisplayLabel(task.provider)}</em>
                    </strong>
                    <span className={`video-output-status is-${task.status}`}>{statusLabel(task.status)}</span>
                  </div>
                  <div className="video-output-task-settings">{taskSettingSummary(task)}</div>
                  {taskStatusHint(task) && <small className="video-output-task-note">{taskStatusHint(task)}</small>}
                  <div className="video-output-task-actions">
                    <VideoTaskDetailTrigger onClick={() => setDetailTask(task)} />
                    {(task.result_path || task.api_task_id || task.status === 'failed' || task.status === 'processing') && (
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={downloadBusyId === task.id || recoverBusyId === task.id}
                        title={task.result_path ? '下载成片文件' : '同步远端成片并下载'}
                        onClick={() => downloadVideoTask?.(task)}
                      >
                        <Download />
                        下载
                      </button>
                    )}
                    <button type="button" className="secondary compact" onClick={() => retryVideoTask(task)}>
                      <RefreshCw />
                      重试
                    </button>
                    <button
                      type="button"
                      className="icon-button danger"
                      disabled={!['completed', 'failed'].includes(task.status)}
                      title="删除任务"
                      onClick={() => deleteVideoTask(task)}
                    >
                      <Trash2 />
                    </button>
                  </div>
                  {task.api_task_id && <small className="video-output-task-note mono">远端：{task.api_task_id}</small>}
                  {(task.error_message || task.result_path) && !taskStatusHint(task)?.includes(task.error_message || '') && (
                    <small className="video-output-task-note">
                      {task.error_message || displayResultFilename(task.result_path)}
                    </small>
                  )}
                </article>
              ))}
            </div>
          )}

          {orphanedTasks.length > 0 && (
            <div className="video-output-orphaned">
              <div className="video-output-section-head">
                <strong>历史版本</strong>
                <span>{orphanedTasks.length} 个</span>
              </div>
              {orphanedTasks.map((task) => (
                <article className="video-output-task-item is-orphaned" key={task.id}>
                  <div className="video-output-task-main">
                    <strong>
                      {task.is_preview ? '预览' : '完整'} / v{task.version}
                    </strong>
                    <span className={`video-output-status is-${task.status}`}>{statusLabel(task.status)}</span>
                  </div>
                  <div className="video-output-task-actions">
                    <VideoTaskDetailTrigger onClick={() => setDetailTask(task)} />
                    <button
                      type="button"
                      className="icon-button danger"
                      disabled={!['completed', 'failed'].includes(task.status)}
                      title="删除任务"
                      onClick={() => deleteVideoTask(task)}
                    >
                      <Trash2 />
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>

      <VideoTaskDetailDialog
        task={detailTask}
        recoverBusy={Boolean(detailTask && recoverBusyId === detailTask.id)}
        onClose={() => setDetailTask(null)}
        onRecover={async (apiTaskId) => {
          if (!detailTask) return;
          const updated = await recoverVideoTask?.(detailTask, apiTaskId);
          if (updated) setDetailTask(updated);
        }}
      />
    </section>
  );
}
