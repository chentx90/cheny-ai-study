import React, { useMemo, useState } from 'react';
import { Download, Eye, FileSearch, X } from 'lucide-react';

function taskSettings(task) {
  return task?.assets?.settings && typeof task.assets.settings === 'object' ? task.assets.settings : {};
}

function pathList(value) {
  if (!Array.isArray(value)) return [];
  return value.map(String).filter(Boolean);
}

function summarizeRefs(task) {
  const assets = task?.assets && typeof task.assets === 'object' ? task.assets : {};
  return {
    mode: String(assets.reference_mode || 'none'),
    firstFrame: String(assets.first_frame || ''),
    lastFrame: String(assets.last_frame || ''),
    images: pathList(assets.reference_images),
    videos: pathList(assets.reference_videos?.length ? assets.reference_videos : assets.video_clips),
    audios: pathList(assets.reference_audios?.length ? assets.reference_audios : assets.audio_samples),
    mixed: pathList(assets.assets),
  };
}

function statusLabel(status) {
  const map = {
    completed: '已完成',
    processing: '生成中',
    failed: '失败',
    pending: '等待中',
  };
  return map[status] || status || '未知';
}

export default function VideoTaskDetailDialog({
  task,
  onClose,
  onRecover,
  recoverBusy = false,
}) {
  const [remoteId, setRemoteId] = useState(() => String(task?.api_task_id || ''));
  const settings = useMemo(() => taskSettings(task), [task]);
  const refs = useMemo(() => summarizeRefs(task), [task]);

  if (!task) return null;

  const canRecover = Boolean(String(remoteId || '').trim()) || Boolean(task.api_task_id);

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section
        className="video-task-detail-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="video-task-detail-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <span className="dialog-icon">
            <FileSearch />
          </span>
          <div>
            <h3 id="video-task-detail-title">视频任务详情</h3>
            <p>查看本次请求参数，并可按远端任务 ID 追回成片。</p>
          </div>
          <button type="button" className="icon-button secondary" title="关闭" onClick={onClose}>
            <X />
          </button>
        </header>

        <div className="video-task-detail-grid">
          <div>
            <span>本地任务</span>
            <strong>{task.id}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong className={`video-output-status is-${task.status}`}>{statusLabel(task.status)}</strong>
          </div>
          <div>
            <span>版本</span>
            <strong>
              {task.is_preview ? '预览' : '完整'} / v{task.version}
            </strong>
          </div>
          <div>
            <span>服务商</span>
            <strong>{task.provider || '未配置'}</strong>
          </div>
          <div>
            <span>模型</span>
            <strong>{settings.model || '服务默认'}</strong>
          </div>
          <div>
            <span>参数</span>
            <strong>
              {[settings.aspect_ratio || settings.aspectRatio, settings.duration || task.duration ? `${settings.duration || task.duration}秒` : '', settings.resolution]
                .filter(Boolean)
                .join(' / ') || '—'}
            </strong>
          </div>
          <div className="span-2">
            <span>远端任务 ID</span>
            <strong className="mono">{task.api_task_id || '尚未拿到（创建阶段失败或未落库）'}</strong>
          </div>
          {task.result_path && (
            <div className="span-2">
              <span>成片路径</span>
              <strong className="mono">{task.result_path}</strong>
            </div>
          )}
          {task.error_message && (
            <div className="span-2">
              <span>错误</span>
              <strong className="error-text">{task.error_message}</strong>
            </div>
          )}
        </div>

        <div className="video-task-detail-block">
          <strong>参考模式 · {refs.mode}</strong>
          {refs.firstFrame && <small>首帧：{refs.firstFrame}</small>}
          {refs.lastFrame && <small>尾帧：{refs.lastFrame}</small>}
          {refs.images.length > 0 && <small>图片：{refs.images.join('、')}</small>}
          {refs.videos.length > 0 && <small>视频：{refs.videos.join('、')}</small>}
          {refs.audios.length > 0 && <small>音频：{refs.audios.join('、')}</small>}
          {refs.mode === 'none' && <small>无参考素材</small>}
          {refs.mode !== 'none' &&
            !refs.firstFrame &&
            !refs.lastFrame &&
            refs.images.length === 0 &&
            refs.videos.length === 0 &&
            refs.audios.length === 0 && <small>未记录具体参考路径</small>}
        </div>

        <div className="video-task-detail-block">
          <strong>提示词</strong>
          <pre>{task.prompt || '（空）'}</pre>
        </div>

        <div className="video-task-recover">
          <label>
            <span>追回用远端任务 ID</span>
            <input
              value={remoteId}
              placeholder="例如 task_xxxx（网关返回的 id）"
              onChange={(event) => setRemoteId(event.target.value)}
            />
          </label>
          <small>
            网络波动处理：若创建时已拿到远端 ID，用「追回」拉成片，不要反复「重试」（会重新扣次）。
            若创建阶段就失败（无远端 ID），修好参数后再重试；当前网关要求主参考为单张图。
          </small>
        </div>

        <footer>
          <button type="button" className="secondary" onClick={onClose}>
            关闭
          </button>
          <button
            type="button"
            disabled={recoverBusy || !canRecover}
            onClick={() => onRecover?.(String(remoteId || task.api_task_id || '').trim())}
          >
            {recoverBusy ? '追回中…' : (
              <>
                <Download />
                追回成片
              </>
            )}
          </button>
        </footer>
      </section>
    </div>
  );
}

export function VideoTaskDetailTrigger({ onClick, label = '查看' }) {
  return (
    <button type="button" className="secondary compact" onClick={onClick} title="查看请求与追回">
      <Eye />
      {label}
    </button>
  );
}
