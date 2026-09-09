import { useCallback, useEffect, useRef, useState } from 'react';
import {
  approveAgentRun,
  cancelAgentRun,
  createAgentBranch,
  createAgentThread,
  getAgentThread,
  listAgentThreads,
  sendAgentMessage,
} from '../api/agent';
import { agentMutationEvent } from '../domain/agent/commandEffects';
import { readStorageJson, readStorageText, writeStorageJson, writeStorageText } from '../app/uiStorage';

const STORAGE_KEY = 'ai-video-manager:agent-ui';
const NARROW_AGENT_QUERY = '(max-width: 900px)';
const APPROVAL_MODES = new Set(['manual', 'project', 'trusted']);

function readPrefs() {
  const value = readStorageJson(STORAGE_KEY, {});
  return {
    desktopCollapsed: Object.hasOwn(value, 'desktopCollapsed')
      ? Boolean(value.desktopCollapsed)
      : Boolean(value.collapsed),
    mobileCollapsed: Object.hasOwn(value, 'mobileCollapsed')
      ? Boolean(value.mobileCollapsed)
      : true,
    approvalMode: APPROVAL_MODES.has(value.approvalMode) ? value.approvalMode : 'manual',
    width: Math.min(520, Math.max(320, Number(value.width) || 360)),
  };
}

function savePrefs(value) {
  writeStorageJson(STORAGE_KEY, value);
}

export function useWorkflowAgent({ projectId, currentView, activeContext }) {
  const [prefs, setPrefs] = useState(readPrefs);
  const [narrowViewport, setNarrowViewport] = useState(
    () => window.matchMedia(NARROW_AGENT_QUERY).matches,
  );
  const [thread, setThread] = useState(null);
  const [threads, setThreads] = useState([]);
  const [messages, setMessages] = useState([]);
  const [run, setRun] = useState(null);
  const [mutationEvent, setMutationEvent] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const projectRef = useRef(projectId || '');
  const threadRef = useRef('');
  const contextRef = useRef({ current_view: currentView, active_context: activeContext || {} });
  projectRef.current = projectId || '';
  threadRef.current = thread?.id || '';
  contextRef.current = { current_view: currentView, active_context: activeContext || {} };

  useEffect(() => {
    savePrefs(prefs);
  }, [prefs]);

  useEffect(() => {
    const media = window.matchMedia(NARROW_AGENT_QUERY);
    const updateViewport = (event) => setNarrowViewport(event.matches);
    setNarrowViewport(media.matches);
    media.addEventListener('change', updateViewport);
    return () => media.removeEventListener('change', updateViewport);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setThread(null);
    setThreads([]);
    setMessages([]);
    setRun(null);
    setMutationEvent(null);
    setBusy(false);
    setError('');
    if (!projectId) return undefined;
    listAgentThreads(projectId)
      .then(async (data) => {
        if (cancelled) return null;
        let available = data.threads || [];
        if (!available.length) {
          const created = await createAgentThread(projectId);
          available = [created.thread];
        }
        if (cancelled) return null;
        setThreads(available);
        const storedId = readStorageText(`ai-video-manager:agent-thread:${projectId}`);
        const selected = available.find((item) => item.id === storedId) || available[0];
        setThread(selected);
        return getAgentThread(selected.id);
      })
      .then((data) => {
        if (!cancelled && data?.messages) {
          setMessages(data.messages);
          setRun(data.run || null);
        }
      })
      .catch((nextError) => {
        if (!cancelled) setError(nextError.message || 'Agent 会话创建失败');
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const selectThread = useCallback(async (threadId) => {
    const selected = threads.find((item) => item.id === threadId);
    if (!selected || selected.id === thread?.id) return;
    const requestProjectId = projectId || '';
    setBusy(true);
    setError('');
    try {
      const data = await getAgentThread(selected.id);
      if (projectRef.current !== requestProjectId) return;
      setThread(data.thread);
      setMessages(data.messages || []);
      setRun(data.run || null);
      writeStorageText(`ai-video-manager:agent-thread:${projectId}`, selected.id);
    } catch (nextError) {
      if (projectRef.current !== requestProjectId) return;
      setError(nextError.message || 'Agent 分支加载失败');
    } finally {
      if (projectRef.current === requestProjectId) setBusy(false);
    }
  }, [projectId, thread?.id, threads]);

  const branch = useCallback(async () => {
    if (!thread?.id || busy) return;
    const requestProjectId = projectId || '';
    const sourceThreadId = thread.id;
    setBusy(true);
    setError('');
    try {
      const data = await createAgentBranch(thread.id);
      if (projectRef.current !== requestProjectId || threadRef.current !== sourceThreadId) return data;
      const nextThread = data.thread;
      setThreads((current) => [nextThread, ...current]);
      setThread(nextThread);
      setMessages(data.messages || []);
      setRun(null);
      writeStorageText(`ai-video-manager:agent-thread:${projectId}`, nextThread.id);
      return data;
    } catch (nextError) {
      if (projectRef.current !== requestProjectId || threadRef.current !== sourceThreadId) return undefined;
      setError(nextError.message || 'Agent 分支创建失败');
      throw nextError;
    } finally {
      if (projectRef.current === requestProjectId) setBusy(false);
    }
  }, [busy, projectId, thread?.id]);

  const send = useCallback(async (content, attachments = []) => {
    if (!thread?.id || !content.trim()) return;
    const messageContent = content.trim();
    const uiContext = {
      ...contextRef.current,
      active_context: {
        ...(contextRef.current.active_context || {}),
        attachments: attachments.map((item) => ({
          path: item.path,
          filename: item.filename,
          asset_type: item.asset_type,
        })),
      },
    };
    const optimisticId = `optimistic_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const requestProjectId = projectId || '';
    const requestThreadId = thread.id;
    const requestIsCurrent = () => (
      projectRef.current === requestProjectId && threadRef.current === requestThreadId
    );
    setMessages((current) => [...current, {
      id: optimisticId,
      role: 'user',
      content: messageContent,
      metadata: {
        status: 'sending',
        ui_context: uiContext,
      },
    }]);
    setError('');
    setBusy(true);
    try {
      const data = await sendAgentMessage(thread.id, messageContent, uiContext, prefs.approvalMode);
      if (!requestIsCurrent()) return data;
      setMessages(data.thread?.messages || data.messages || []);
      setRun(data.run || null);
      const nextMutation = agentMutationEvent(data);
      if (nextMutation) setMutationEvent(nextMutation);
      if (data.run?.status === 'failed') setError(data.run.state?.message || 'Agent 操作失败');
      return data;
    } catch (nextError) {
      if (!requestIsCurrent()) return undefined;
      setMessages((current) => current.map((message) => (
        message.id === optimisticId
          ? { ...message, metadata: { ...message.metadata, status: 'failed' } }
          : message
      )));
      setError(nextError.message || 'Agent 请求失败');
      throw nextError;
    } finally {
      if (requestIsCurrent()) setBusy(false);
    }
  }, [prefs.approvalMode, projectId, thread?.id]);

  const approve = useCallback(async () => {
    if (!run?.id) return;
    const requestProjectId = projectId || '';
    const requestThreadId = thread?.id || '';
    const requestIsCurrent = () => (
      projectRef.current === requestProjectId && threadRef.current === requestThreadId
    );
    setBusy(true);
    try {
      const data = await approveAgentRun(run.id);
      if (!requestIsCurrent()) return data;
      setRun(data.run || null);
      const nextMutation = agentMutationEvent(data);
      if (nextMutation) setMutationEvent(nextMutation);
      if (data.messages) setMessages(data.messages);
      else setMessages((current) => [...current, ...(data.run?.state?.message ? [{ id: `${run.id}:approved`, role: 'assistant', content: data.run.state.message, metadata: { run_id: run.id, status: 'completed' } }] : [])]);
      return data;
    } catch (nextError) {
      if (!requestIsCurrent()) return undefined;
      setError(nextError.message || 'Agent 执行失败');
      throw nextError;
    } finally {
      if (requestIsCurrent()) setBusy(false);
    }
  }, [projectId, run, thread?.id]);

  const cancel = useCallback(async () => {
    if (!run?.id) return;
    const requestProjectId = projectId || '';
    const requestThreadId = thread?.id || '';
    const data = await cancelAgentRun(run.id);
    if (projectRef.current !== requestProjectId || threadRef.current !== requestThreadId) return data;
    setRun(data.run || null);
    if (data.messages) setMessages(data.messages);
    return data;
  }, [projectId, run, thread?.id]);

  return {
    thread,
    threads,
    messages,
    run,
    mutationEvent,
    busy,
    error,
    collapsed: narrowViewport ? prefs.mobileCollapsed : prefs.desktopCollapsed,
    width: prefs.width,
    approvalMode: prefs.approvalMode,
    setApprovalMode: (approvalMode) => setPrefs((value) => ({
      ...value,
      approvalMode: APPROVAL_MODES.has(approvalMode) ? approvalMode : 'manual',
    })),
    toggleCollapsed: () => setPrefs((value) => (
      narrowViewport
        ? { ...value, mobileCollapsed: !value.mobileCollapsed }
        : { ...value, desktopCollapsed: !value.desktopCollapsed }
    )),
    setWidth: (width) => setPrefs((value) => ({ ...value, width: Math.min(520, Math.max(320, Number(width) || 360)) })),
    send,
    approve,
    cancel,
    selectThread,
    branch,
  };
}
