import React, { useEffect, useState } from 'react';
import {
  Bot, Check, File, Film, GitBranch, GitFork, ImageIcon, Loader2, Music2,
  PanelRightClose, PanelRightOpen, Plus, Send, ShieldCheck, Square, Upload, X,
} from 'lucide-react';
import { useStickyBottom } from '../hooks/useStickyBottom';

const APPROVAL_OPTIONS = [
  { id: 'manual', label: '逐步确认' },
  { id: 'project', label: '项目内自动' },
  { id: 'trusted', label: '非删除自动' },
];

function inferAssetType(file) {
  const mimeType = String(file?.type || '').toLowerCase();
  const filename = String(file?.name || '').toLowerCase();
  if (mimeType.startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp|svg|avif)$/.test(filename)) return 'image';
  if (mimeType.startsWith('audio/') || /\.(mp3|wav|m4a|aac|flac|ogg|opus)$/.test(filename)) return 'audio';
  if (mimeType.startsWith('video/') || /\.(mp4|mov|m4v|webm|avi|mkv)$/.test(filename)) return 'video';
  return 'file';
}

function attachmentUrl(apiBase, projectId, attachment) {
  if (!projectId || !attachment?.path) return '';
  const encoded = String(attachment.path).split('/').map(encodeURIComponent).join('/');
  return `${apiBase || ''}/api/projects/${encodeURIComponent(projectId)}/assets/${encoded}`;
}

function messageAttachments(message) {
  const values = message.metadata?.ui_context?.active_context?.attachments;
  return Array.isArray(values) ? values : [];
}

function AttachmentPreview({ attachment, apiBase, projectId }) {
  const url = attachmentUrl(apiBase, projectId, attachment);
  if (attachment.asset_type === 'image') return <img src={url} alt="" />;
  if (attachment.asset_type === 'video') return <video src={url} muted preload="metadata" />;
  if (attachment.asset_type === 'audio') return <Music2 />;
  if (attachment.asset_type === 'file') return <File />;
  return <ImageIcon />;
}

function commandLabel(item) {
  return item.command || item.command_id || '未知命令';
}

function toolResultText(value) {
  if (value == null) return '';
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > 12000 ? `${text.slice(0, 12000)}\n...结果过长，已截断` : text;
  } catch (_error) {
    return String(value);
  }
}

function toolStatus(message, index) {
  if (message.metadata.results?.[index]) return '已完成';
  if (message.metadata.status === 'waiting_approval') return '待确认';
  if (message.metadata.status === 'cancelled') return '已取消';
  if (message.metadata.status === 'failed') return '失败';
  return '已规划';
}

function threadLabel(item) {
  const date = item.updated_at ? new Date(item.updated_at) : null;
  const stamp = date && !Number.isNaN(date.getTime())
    ? date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
    : String(item.id || '').slice(-6);
  return `${item.branch_depth ? `${'  '.repeat(item.branch_depth)}↳ ` : ''}${item.title} · ${stamp} · ${String(item.id || '').slice(-6)}`;
}

export default function AgentDock({
  agent, projectName, projectId, assets = [], apiBase = '', uploadProjectAssets,
}) {
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [attachmentPickerOpen, setAttachmentPickerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const pending = agent.run?.status === 'waiting_approval';
  const lastMessageId = agent.messages.at(-1)?.id || '';
  const messageScroll = useStickyBottom({
    scopeId: agent.thread?.id || '',
    contentKey: lastMessageId,
    active: agent.busy,
  });

  useEffect(() => {
    setAttachments([]);
    setAttachmentPickerOpen(false);
  }, [projectId]);

  function submit(event) {
    event.preventDefault();
    if (!draft.trim() || agent.busy) return;
    const content = draft;
    const selectedAttachments = attachments;
    messageScroll.pinToBottom();
    setDraft('');
    setAttachments([]);
    setAttachmentPickerOpen(false);
    agent.send(content, selectedAttachments).catch(() => {});
  }

  function toggleAttachment(asset) {
    setAttachments((current) => (
      current.some((item) => item.path === asset.path)
        ? current.filter((item) => item.path !== asset.path)
        : [...current, {
          path: asset.path,
          filename: asset.filename || String(asset.path).split('/').pop(),
          asset_type: asset.asset_type || 'file',
        }]
    ));
  }

  async function uploadLocalAttachments(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length || !uploadProjectAssets || !projectId) return;
    setUploading(true);
    try {
      const paths = await uploadProjectAssets(files, projectId);
      setAttachments((current) => {
        const incoming = (paths || []).map((path, index) => ({
          path,
          filename: files[index]?.name || String(path).split('/').pop(),
          asset_type: inferAssetType(files[index]),
        }));
        return [...current, ...incoming.filter(
          (item) => !current.some((existing) => existing.path === item.path),
        )];
      });
    } catch (_error) {
      // The shared async runner already surfaces the upload error.
    } finally {
      setUploading(false);
    }
  }

  function handleComposerKeyDown(event) {
    if (
      event.key !== 'Enter'
      || event.shiftKey
      || event.nativeEvent?.isComposing
      || event.keyCode === 229
    ) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  return (
    <aside className={`agent-dock${agent.collapsed ? ' is-collapsed' : ''}`} style={{ '--agent-width': `${agent.width}px` }}>
      <div className="agent-dock-resizer" role="separator" aria-label="调整 Agent 面板宽度" onPointerDown={(event) => {
        const startX = event.clientX;
        const startWidth = agent.width;
        const onMove = (moveEvent) => agent.setWidth(startWidth - (moveEvent.clientX - startX));
        const onUp = () => {
          window.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointerup', onUp);
        };
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
      }} />
      <header className="agent-dock-header">
        <div className="agent-dock-heading">
          <Bot />
          {!agent.collapsed && <div><strong>工作流 Agent</strong><small>{projectName || '选择项目后可用'}</small></div>}
        </div>
        <button type="button" className="icon-button secondary" title={agent.collapsed ? '展开 Agent' : '折叠 Agent'} aria-label={agent.collapsed ? '展开 Agent' : '折叠 Agent'} onClick={agent.toggleCollapsed}>
          {agent.collapsed ? <PanelRightOpen /> : <PanelRightClose />}
        </button>
      </header>
      {!agent.collapsed && (
        <>
          <div className="agent-dock-context">
            <GitBranch />
            <select
              value={agent.thread?.id || ''}
              onChange={(event) => agent.selectThread(event.target.value)}
              disabled={!projectId || agent.busy}
              title="切换 Agent 会话分支"
              aria-label="切换 Agent 会话分支"
            >
              {(agent.threads || []).map((item) => (
                <option value={item.id} key={item.id}>
                  {threadLabel(item)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="icon-button secondary"
              title="从当前会话创建分支"
              aria-label="从当前会话创建分支"
              disabled={!agent.thread?.id || agent.busy}
              onClick={agent.branch}
            >
              <GitFork />
            </button>
          </div>
          <div ref={messageScroll.containerRef} className="agent-dock-messages" aria-live="polite" onScroll={messageScroll.onScroll}>
            {!projectId && <div className="agent-empty">先选择一个项目，再让 Agent 读取或操作项目内容。</div>}
            {projectId && !agent.messages.length && !agent.busy && <div className="agent-empty">可以查询分集、剧本、实体、素材和任务，也可以在确认后执行修改。</div>}
            {agent.messages.map((message) => (
              <article className={`agent-message ${message.role}${message.metadata?.status === 'failed' ? ' is-failed' : ''}`} key={message.id}>
                <div className="agent-message-role">{message.role === 'user' ? '你' : 'Agent'}</div>
                <p>{message.content}</p>
                {messageAttachments(message).length > 0 && (
                  <div className="agent-message-attachments">
                    {messageAttachments(message).map((attachment) => (
                      <div className="agent-message-attachment" key={attachment.path} title={attachment.filename || attachment.path}>
                        <AttachmentPreview attachment={attachment} apiBase={apiBase} projectId={projectId} />
                        <span>{attachment.filename || attachment.path}</span>
                      </div>
                    ))}
                  </div>
                )}
                {message.metadata?.commands?.length > 0 && (
                  <div className="agent-command-list">
                    {message.metadata.commands.map((item, index) => (
                      <div className="agent-command-card" key={`${commandLabel(item)}-${index}`}>
                        <div className="agent-command-head">
                          <strong>{commandLabel(item)}</strong>
                          <span>{toolStatus(message, index)}</span>
                        </div>
                        {item.reason && <small>{item.reason}</small>}
                        {item.cli_preview && <code>{item.cli_preview}</code>}
                        {message.metadata.results?.[index] && (
                          <details className="agent-command-result">
                            <summary>查看工具返回</summary>
                            <pre>{toolResultText(message.metadata.results[index])}</pre>
                          </details>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </article>
            ))}
            {agent.busy && <div className="agent-running"><Loader2 className="spin" /> 正在读取项目并规划操作</div>}
            {agent.error && <div className="agent-error">{agent.error}</div>}
            {pending && (
              <div className="agent-approval">
                <strong>该计划会修改项目或调用外部服务</strong>
                <div><button type="button" onClick={agent.approve} disabled={agent.busy}><Check />确认执行</button><button type="button" className="secondary" onClick={agent.cancel}><X />取消</button></div>
              </div>
            )}
          </div>
          <form className="agent-dock-composer" onSubmit={submit}>
            {attachmentPickerOpen && (
              <div className="agent-attachment-picker">
                <div className="agent-attachment-picker-head">
                  <strong>引用项目素材</strong>
                  <label className={uploading ? 'is-disabled' : ''} title="从本地上传到项目素材库">
                    {uploading ? <Loader2 className="spin" /> : <Upload />}
                    <span>{uploading ? '上传中' : '本地上传'}</span>
                    <input type="file" accept="image/*,audio/*,video/*" multiple disabled={uploading} onChange={uploadLocalAttachments} />
                  </label>
                </div>
                <div className="agent-attachment-grid">
                  {assets.length === 0 && <span className="agent-attachment-empty">项目素材库为空</span>}
                  {assets.map((asset) => {
                    const selected = attachments.some((item) => item.path === asset.path);
                    return (
                      <button
                        type="button"
                        className={selected ? 'agent-attachment-option selected' : 'agent-attachment-option'}
                        title={asset.filename}
                        aria-pressed={selected}
                        onClick={() => toggleAttachment(asset)}
                        key={asset.path}
                      >
                        <AttachmentPreview attachment={asset} apiBase={apiBase} projectId={projectId} />
                        <span>{asset.filename}</span>
                        {selected && <Check />}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="agent-composer-box">
              {attachments.length > 0 && (
                <div className="agent-composer-attachments">
                  {attachments.map((attachment) => (
                    <div className="agent-composer-attachment" key={attachment.path} title={attachment.filename}>
                      <AttachmentPreview attachment={attachment} apiBase={apiBase} projectId={projectId} />
                      <span>{attachment.filename}</span>
                      <button type="button" title="移除引用" aria-label={`移除 ${attachment.filename}`} onClick={() => toggleAttachment(attachment)}><X /></button>
                    </div>
                  ))}
                </div>
              )}
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder="告诉 Agent 要查询或执行什么"
                rows={3}
                disabled={!projectId || agent.busy}
              />
              <div className="agent-composer-footer">
                <div className="agent-composer-tools">
                  <button
                    type="button"
                    className={attachmentPickerOpen ? 'icon-button secondary active' : 'icon-button secondary'}
                    title="添加或引用素材"
                    aria-label="添加或引用素材"
                    disabled={!projectId || agent.busy}
                    onClick={() => setAttachmentPickerOpen((value) => !value)}
                  ><Plus /></button>
                  <label className="agent-approval-preset" title="设置本次及后续对话的自动审批范围">
                    <ShieldCheck />
                    <select value={agent.approvalMode} onChange={(event) => agent.setApprovalMode(event.target.value)} aria-label="审批权限预设">
                      {APPROVAL_OPTIONS.map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}
                    </select>
                  </label>
                </div>
                <div className="agent-dock-composer-actions">
                  {agent.run && agent.busy && <button type="button" className="icon-button secondary" title="停止当前运行" aria-label="停止当前运行" onClick={agent.cancel}><Square /></button>}
                  <button type="submit" className="icon-button agent-send-button" title="发送消息" aria-label="发送消息" disabled={!projectId || !draft.trim() || agent.busy}><Send /></button>
                </div>
              </div>
            </div>
          </form>
        </>
      )}
    </aside>
  );
}
