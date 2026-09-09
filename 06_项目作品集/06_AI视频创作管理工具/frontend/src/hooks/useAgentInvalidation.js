import { useEffect, useRef } from 'react';

export function useAgentInvalidation({
  mutationEvent,
  projectId,
  activeSegmentId,
  notify,
  refreshProjects,
  refreshProjectState,
  refreshWorkflow,
  refreshWorkspace,
  refreshEntities,
  refreshAssets,
  refreshPromptCards,
  refreshVideos,
  refreshTemplates,
}) {
  const handledMutationRef = useRef('');

  useEffect(() => {
    if (!mutationEvent || handledMutationRef.current === mutationEvent.id) return undefined;
    if (mutationEvent.projectId && mutationEvent.projectId !== projectId) return undefined;
    handledMutationRef.current = mutationEvent.id;
    const effects = new Set(mutationEvent.effects);
    const refreshes = [];

    if (effects.has('projects')) {
      refreshes.push(refreshProjects());
      if (projectId) refreshes.push(refreshProjectState(projectId), refreshWorkflow(projectId));
    }
    if (effects.has('workspace') && projectId) refreshes.push(refreshWorkspace(projectId));
    if (effects.has('entities') && projectId) refreshes.push(refreshEntities(projectId));
    if (effects.has('assets') && projectId) refreshes.push(refreshAssets(projectId));
    if (effects.has('prompt-cards') && projectId) {
      refreshes.push(refreshPromptCards(projectId, activeSegmentId));
    }
    if (effects.has('videos') && projectId) refreshes.push(refreshVideos(projectId));
    if (effects.has('templates')) refreshes.push(refreshTemplates());

    Promise.allSettled(refreshes).then((results) => {
      const failed = results.find((result) => result.status === 'rejected');
      if (failed) {
        notify(
          `Agent 已完成操作，但部分页面数据刷新失败：${failed.reason?.message || '未知错误'}`,
          'error',
        );
      }
    });
    return undefined;
  }, [
    activeSegmentId,
    mutationEvent,
    notify,
    projectId,
    refreshAssets,
    refreshEntities,
    refreshProjectState,
    refreshProjects,
    refreshPromptCards,
    refreshTemplates,
    refreshVideos,
    refreshWorkflow,
    refreshWorkspace,
  ]);
}
