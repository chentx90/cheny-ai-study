import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError, request, requestWithRetry } from '../api/client';
import {
  downloadBlob,
  exportProjectBundle,
  importProjectFolder,
  importProjectZip,
} from '../api/projects';
import { commitWorkspacePatch } from '../domain/workspace';
import { episodesToWorkspaceFields, listEpisodes } from '../api/episodes';
import {
  refreshSourceAssets as refreshSourceAssetsApi,
  saveProjectSettings,
} from '../api/workspace';
import { emptyProjectDraft, emptyWorkspace } from '../constants';
import { projectDefaultSettings } from '../utils/projectUtils';
import {
  normalizeEpisodeSegments,
  readStoredUiState,
  storeUiState,
  validViewIds,
} from '../app/uiStorage';

export function useProjectWorkspace({
  run,
  notify,
  setNotice,
  askConfirm,
  setView,
  view,
  resetCardDraft,
  refreshVideoTasks,
}) {
  const [projects, setProjects] = useState([]);
  const [projectListLoaded, setProjectListLoaded] = useState(false);
  const [projectListError, setProjectListError] = useState('');
  const [selectedProject, setSelectedProject] = useState(null);
  const [workspace, setWorkspace] = useState(emptyWorkspace);
  const [projectState, setProjectState] = useState(null);
  const [projectDraft, setProjectDraft] = useState({ ...emptyProjectDraft });
  const [entityCards, setEntityCards] = useState([]);
  const [entityMaterials, setEntityMaterials] = useState([]);
  const [assets, setAssets] = useState([]);
  const [promptCards, setPromptCards] = useState([]);
  const [workflowUi, setWorkflowUi] = useState(null);
  const [splitSuggestions, setSplitSuggestions] = useState([]);

  const workspaceRef = useRef(emptyWorkspace);
  const persistTimer = useRef(null);
  const pendingPersist = useRef(null);
  const persistQueue = useRef(Promise.resolve());
  const selectedProjectRef = useRef(null);
  const projectLoadSequence = useRef(0);
  const activeSegmentIdRef = useRef('');

  useEffect(() => {
    selectedProjectRef.current = selectedProject;
  }, [selectedProject]);

  const activeSegment = useMemo(
    () =>
      workspace.segments.find((segment) => segment.id === workspace.activeSegmentId) ||
      workspace.segments[0] ||
      null,
    [workspace.segments, workspace.activeSegmentId],
  );
  const activeScript = activeSegment ? workspace.scripts[activeSegment.id] || '' : '';
  activeSegmentIdRef.current = activeSegment?.id || '';

  const readStoredProjectId = useCallback(() => readStoredUiState().selectedProjectId, []);

  const storeSelectedProjectId = useCallback((projectId) => {
    storeUiState({ selectedProjectId: projectId || '' });
  }, []);

  const refreshProjects = useCallback(async (options = {}) => {
    setProjectListError('');
    try {
      const loader = options.retry ? requestWithRetry : request;
      const data = await loader('/api/projects?include_deleted=true', {}, { attempts: 5, delayMs: 400 });
      const nextProjects = data.projects || [];
      setProjects(nextProjects);
      setProjectListLoaded(true);
      return nextProjects;
    } catch (error) {
      setProjectListLoaded(true);
      setProjectListError(error.message || '项目列表加载失败');
      throw error;
    }
  }, []);

  const refreshProjectState = useCallback(async (projectId = selectedProjectRef.current?.id) => {
    if (!projectId) {
      setProjectState(null);
      return null;
    }
    const data = await request(`/api/projects/${projectId}/state`);
    if (selectedProjectRef.current?.id === projectId) setProjectState(data);
    return data;
  }, []);

  const refreshEntityCards = useCallback(async (projectId = selectedProjectRef.current?.id) => {
    if (!projectId) {
      setEntityCards([]);
      return [];
    }
    const data = await request(`/api/projects/${projectId}/entity-cards`);
    if (selectedProjectRef.current?.id === projectId) setEntityCards(data.cards);
    return data.cards;
  }, []);

  const refreshEntityMaterials = useCallback(async (projectId = selectedProjectRef.current?.id) => {
    if (!projectId) {
      setEntityMaterials([]);
      return [];
    }
    const data = await request(`/api/projects/${projectId}/entity-materials`);
    if (selectedProjectRef.current?.id === projectId) setEntityMaterials(data.materials);
    return data.materials;
  }, []);

  const refreshAssets = useCallback(async (projectId = selectedProjectRef.current?.id) => {
    if (!projectId) {
      setAssets([]);
      return [];
    }
    const data = await request(`/api/projects/${projectId}/assets`);
    if (selectedProjectRef.current?.id === projectId) setAssets(data.assets);
    return data.assets;
  }, []);

  const refreshPromptCards = useCallback(
    async (projectId = selectedProjectRef.current?.id, segmentId = activeSegment?.id) => {
      if (!projectId || !segmentId) {
        setPromptCards([]);
        return [];
      }
      let data;
      try {
        data = await request(`/api/projects/${projectId}/segments/${segmentId}/prompt-cards`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          if (
            selectedProjectRef.current?.id === projectId
            && activeSegmentIdRef.current === segmentId
          ) setPromptCards([]);
          return [];
        }
        throw error;
      }
      if (
        selectedProjectRef.current?.id === projectId
        && activeSegmentIdRef.current === segmentId
      ) setPromptCards(data.cards);
      return data.cards;
    },
    [activeSegment?.id],
  );

  const refreshWorkflowUi = useCallback(async (projectId = selectedProjectRef.current?.id) => {
    if (!projectId) {
      setWorkflowUi(null);
      return null;
    }
    const data = await request(`/api/projects/${projectId}/workflow/ui`);
    if (selectedProjectRef.current?.id === projectId) setWorkflowUi(data);
    return data;
  }, []);

  const cancelPendingPersist = useCallback(() => {
    if (persistTimer.current) {
      clearTimeout(persistTimer.current);
      persistTimer.current = null;
    }
    pendingPersist.current = null;
  }, []);

  const applyWorkspaceResponse = useCallback(
    (data) => {
      cancelPendingPersist();
      const nextWorkspace = {
        ...emptyWorkspace,
        ...(data || {}),
        segments: normalizeEpisodeSegments(data?.segments || []),
      };
      workspaceRef.current = nextWorkspace;
      setWorkspace(nextWorkspace);
      return nextWorkspace;
    },
    [cancelPendingPersist],
  );

  const persistWorkspace = useCallback(
    async (record) => {
      if (!record?.projectId || !record?.patch) return;
      const base = record.baseWorkspace || workspaceRef.current;
      const revision = workspaceRef.current?.revision ?? base?.revision;
      const baseForSave = revision != null ? { ...base, revision } : base;
      try {
        const saved = await commitWorkspacePatch(record.projectId, baseForSave, record.patch);
        if (selectedProjectRef.current?.id === record.projectId) {
          applyWorkspaceResponse(saved);
          refreshProjectState(record.projectId).catch((error) => notify(error.message, 'error'));
          refreshWorkflowUi(record.projectId).catch(() => {});
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          if (selectedProjectRef.current?.id === record.projectId) {
            const saved = await request(`/api/projects/${record.projectId}/session`);
            applyWorkspaceResponse(saved.data || {});
          }
          return;
        }
        throw error;
      }
    },
    [applyWorkspaceResponse, notify, refreshProjectState, refreshWorkflowUi],
  );

  const flushPersist = useCallback(async () => {
    if (persistTimer.current) {
      clearTimeout(persistTimer.current);
      persistTimer.current = null;
    }
    const record = pendingPersist.current;
    pendingPersist.current = null;
    if (record) {
      persistQueue.current = persistQueue.current.then(() => persistWorkspace(record));
    }
    await persistQueue.current;
  }, [persistWorkspace]);

  const schedulePersist = useCallback(
    (patch, project = selectedProjectRef.current, baseWorkspace = workspaceRef.current) => {
      if (!project || !patch || !Object.keys(patch).length) return;
      const previous = pendingPersist.current;
      pendingPersist.current = {
        projectId: project.id,
        baseWorkspace: JSON.parse(JSON.stringify(baseWorkspace)),
        patch: { ...(previous?.projectId === project.id ? previous.patch : {}), ...patch },
      };
      if (persistTimer.current) clearTimeout(persistTimer.current);
      persistTimer.current = setTimeout(() => {
        const record = pendingPersist.current;
        pendingPersist.current = null;
        persistQueue.current = persistQueue.current
          .then(() => persistWorkspace(record))
          .catch((error) => setNotice(error.message));
      }, 350);
    },
    [persistWorkspace, setNotice],
  );

  const persistPendingWorkspace = useCallback(({ clearTimer = false } = {}) => {
    if (clearTimer && persistTimer.current) {
      clearTimeout(persistTimer.current);
      persistTimer.current = null;
    }
    // Do not PUT legacy workspace blob on page hide — granular autosave handles edits.
    pendingPersist.current = null;
  }, []);

  const updateWorkspace = useCallback(
    (patchOrFn) => {
      const prev = workspaceRef.current;
      const resolved = typeof patchOrFn === 'function' ? patchOrFn(prev) : patchOrFn;
      if (!resolved || typeof resolved !== 'object') return;
      const next = { ...prev, ...resolved };
      const patch =
        typeof patchOrFn === 'function'
          ? Object.keys(next).reduce((acc, key) => {
              if (next[key] !== prev[key]) acc[key] = next[key];
              return acc;
            }, {})
          : resolved;
      if (!Object.keys(patch).length) return;
      workspaceRef.current = next;
      setWorkspace(next);
      // Schedule outside React setState so flushPersist() right after updateWorkspace sees the patch.
      schedulePersist(patch, selectedProjectRef.current, prev);
    },
    [schedulePersist],
  );

  const updateProjectDefaults = useCallback((patch) => updateWorkspace(patch), [updateWorkspace]);

  const persistProjectDefaultsNow = useCallback(async () => {
    const project = selectedProjectRef.current;
    if (!project) throw new Error('请先选择项目');
    cancelPendingPersist();
    const current = workspaceRef.current;
    const settings = projectDefaultSettings(current);
    const payload = {
      expected_total_duration_seconds: settings.expectedTotalDurationSeconds,
      default_aspect_ratio: settings.defaultAspectRatio,
      default_video_duration: settings.defaultVideoDuration,
      default_video_model: settings.defaultVideoModel,
      default_resolution: settings.defaultResolution,
      project_style_prompt: settings.projectStylePrompt,
      output_root: settings.outputRoot,
      source_assets_root: settings.sourceAssetsRoot,
      data_root: settings.dataRoot,
    };
    if (current.revision != null) payload.revision = current.revision;
    const saved = await saveProjectSettings(project.id, payload);
    applyWorkspaceResponse(saved);
    await refreshProjectState(project.id);
    return saved;
  }, [applyWorkspaceResponse, cancelPendingPersist, refreshProjectState]);

  const refreshWorkspace = useCallback(
    async (projectId = selectedProjectRef.current?.id) => {
      if (!projectId) return emptyWorkspace;
      const [saved, episodes] = await Promise.all([
        request(`/api/projects/${projectId}/session`),
        listEpisodes(projectId),
      ]);
      const data = {
        ...(saved.data || {}),
        ...episodesToWorkspaceFields(episodes),
      };
      if (selectedProjectRef.current?.id !== projectId) return data;
      return applyWorkspaceResponse(data);
    },
    [applyWorkspaceResponse],
  );

  const syncWorkspacePatch = useCallback(
    async (patch, expectedProjectId = selectedProjectRef.current?.id) => {
      const project = selectedProjectRef.current;
      if (!project) throw new Error('请先选择项目');
      if (expectedProjectId && project.id !== expectedProjectId) {
        throw new Error('项目已切换，已取消旧项目的保存操作');
      }
      if (!patch || !Object.keys(patch).length) return workspaceRef.current;
      cancelPendingPersist();
      const prev = workspaceRef.current;
      const next = { ...prev, ...patch };
      workspaceRef.current = next;
      setWorkspace(next);
      try {
        const saved = await commitWorkspacePatch(project.id, next, patch);
        applyWorkspaceResponse(saved);
        return saved;
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          return refreshWorkspace(project.id);
        }
        throw error;
      }
    },
    [applyWorkspaceResponse, cancelPendingPersist, refreshWorkspace],
  );

  const refreshSourceAssets = useCallback(
    async (projectId = selectedProjectRef.current?.id) => {
      if (!projectId) {
        throw new Error('请先选择项目');
      }
      if (selectedProjectRef.current?.id === projectId) {
        await persistProjectDefaultsNow();
      }
      const data = await refreshSourceAssetsApi(projectId);
      if (selectedProjectRef.current?.id === projectId) setAssets(data.assets || []);
      if (selectedProjectRef.current?.id === projectId) {
        refreshWorkspace(projectId).catch((error) => notify(error.message, 'error'));
      }
      return data;
    },
    [notify, persistProjectDefaultsNow, refreshWorkspace],
  );

  const clearProjectContext = useCallback(() => {
    projectLoadSequence.current += 1;
    storeSelectedProjectId('');
    selectedProjectRef.current = null;
    setSelectedProject(null);
    setProjectState(null);
    setEntityCards([]);
    setEntityMaterials([]);
    setAssets([]);
    setPromptCards([]);
    setSplitSuggestions([]);
    setWorkflowUi(null);
    workspaceRef.current = emptyWorkspace;
    setWorkspace(emptyWorkspace);
    resetCardDraft?.();
  }, [resetCardDraft, storeSelectedProjectId]);

  const loadProject = useCallback(
    async (projectId, { restoreView = false } = {}) => {
      const loadSequence = ++projectLoadSequence.current;
      await flushPersist();
      if (loadSequence !== projectLoadSequence.current) return null;
      const [project, saved, episodes, state, workflow, cards, materials, assetData] = await Promise.all([
        request(`/api/projects/${projectId}`),
        request(`/api/projects/${projectId}/session`),
        listEpisodes(projectId),
        request(`/api/projects/${projectId}/state`),
        request(`/api/projects/${projectId}/workflow/ui`),
        request(`/api/projects/${projectId}/entity-cards`),
        request(`/api/projects/${projectId}/entity-materials`),
        request(`/api/projects/${projectId}/assets`),
      ]);
      if (loadSequence !== projectLoadSequence.current) return null;
      selectedProjectRef.current = project;
      applyWorkspaceResponse({
        ...(saved.data || {}),
        ...episodesToWorkspaceFields(episodes),
      });
      storeSelectedProjectId(project.id);
      setSelectedProject(project);
      setProjectState(state);
      setWorkflowUi(workflow);
      setEntityCards(cards.cards);
      setEntityMaterials(materials.materials);
      setAssets(assetData.assets);
      await refreshVideoTasks?.(projectId);
      if (loadSequence !== projectLoadSequence.current) return null;
      setPromptCards([]);
      setSplitSuggestions([]);
      if (restoreView) {
        const savedView = readStoredUiState().projectLastViews?.[projectId];
        if (savedView && validViewIds.has(savedView) && savedView !== 'projects') {
          setView(savedView);
        }
      }
      return project;
    },
    [applyWorkspaceResponse, flushPersist, notify, refreshVideoTasks, setView, storeSelectedProjectId],
  );

  const restoreStoredProject = useCallback(
    async (projectList) => {
      const storedProjectId = readStoredProjectId();
      const storedProject = projectList.find((project) => project.id === storedProjectId && !project.deleted_at);
      if (storedProject) {
        try {
          await loadProject(storedProject.id);
        } catch (error) {
          storeSelectedProjectId('');
          notify(`恢复上次项目失败：${error.message || '项目加载失败'}`, 'error');
        }
      } else if (storedProjectId) {
        storeSelectedProjectId('');
        if (view !== 'settings') setView('projects');
      }
    },
    [loadProject, notify, readStoredProjectId, setView, storeSelectedProjectId, view],
  );

  const createProject = useCallback(
    () =>
      run('createProject', async () => {
        const name = String(projectDraft.name || '').trim();
        if (!name) throw new Error('请输入项目名称');
        const created = await request('/api/projects', {
          method: 'POST',
          body: JSON.stringify({
            name,
            category: projectDraft.category,
            description: String(projectDraft.description || '').trim(),
          }),
        });
        const initialWorkspace = {
          ...emptyWorkspace,
          dataRoot: String(projectDraft.dataRoot || '').trim(),
          outputRoot: String(projectDraft.outputRoot || '').trim(),
          sourceAssetsRoot: String(projectDraft.sourceAssetsRoot || '').trim(),
        };
        if (initialWorkspace.dataRoot || initialWorkspace.outputRoot || initialWorkspace.sourceAssetsRoot) {
          await saveProjectSettings(created.id, {
            ...(initialWorkspace.dataRoot ? { data_root: initialWorkspace.dataRoot } : {}),
            ...(initialWorkspace.outputRoot ? { output_root: initialWorkspace.outputRoot } : {}),
            ...(initialWorkspace.sourceAssetsRoot ? { source_assets_root: initialWorkspace.sourceAssetsRoot } : {}),
          });
        }
        await refreshProjects();
        await loadProject(created.id);
        setProjectDraft({ ...emptyProjectDraft, name: '新视频项目' });
        setNotice('项目已初始化，文件将写入该项目独立目录');
        return created.id;
      }),
    [loadProject, projectDraft, refreshProjects, run, setNotice],
  );

  const selectProject = useCallback(
    (projectId) => run('selectProject', () => loadProject(projectId, { restoreView: false })),
    [loadProject, run],
  );

  const switchProject = useCallback(
    (projectId) => run('switchProject', () => loadProject(projectId, { restoreView: true })),
    [loadProject, run],
  );

  const updateProjectInfo = useCallback(
    (patch = {}) =>
      run('updateProject', async () => {
        if (!selectedProjectRef.current) return;
        const body = {};
        if (patch.name !== undefined) {
          const trimmed = String(patch.name || '').trim();
          if (!trimmed) throw new Error('项目名称不能为空');
          body.name = trimmed;
        }
        if (patch.description !== undefined) {
          body.description = String(patch.description || '').trim();
        }
        if (!Object.keys(body).length) return;
        const project = await request(`/api/projects/${selectedProjectRef.current.id}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        });
        setSelectedProject(project);
        await refreshProjects();
        await refreshProjectState(project.id);
        notify('项目信息已更新', 'success');
      }),
    [notify, refreshProjectState, refreshProjects, run],
  );

  const updateProjectName = useCallback(
    (name) => updateProjectInfo({ name }),
    [updateProjectInfo],
  );

  const openProjectView = useCallback(
    (nextView) => {
      if (!selectedProjectRef.current) {
        notify('请先选择项目', 'error');
        return;
      }
      if (nextView !== 'projects') setView(nextView);
    },
    [notify, setView],
  );

  const openProjectsHub = useCallback(() => setView('projects'), [setView]);

  const saveProjectDefaults = useCallback(
    () =>
      run('saveProjectDefaults', async () => {
        await persistProjectDefaultsNow();
        notify('项目路径与默认设置已保存', 'success');
      }),
    [notify, persistProjectDefaultsNow, run],
  );

  const exportSelectedProject = useCallback(
    async (projectId = selectedProjectRef.current?.id) => {
      if (!projectId) {
        throw new Error('请先选择项目');
      }
      if (selectedProjectRef.current?.id === projectId) {
        await persistProjectDefaultsNow();
      }
      const { blob, filename } = await exportProjectBundle(projectId);
      downloadBlob(blob, filename);
      return filename;
    },
    [persistProjectDefaultsNow],
  );

  const importProjectFromZip = useCallback(
    async (file, { name } = {}) => {
      if (!file) {
        throw new Error('请选择项目压缩包');
      }
      if (selectedProjectRef.current) {
        await persistProjectDefaultsNow().catch(() => {});
      }
      const data = await importProjectZip(file, { name });
      const project = data.project;
      await refreshProjects();
      if (project?.id) {
        await loadProject(project.id);
      }
      return project;
    },
    [loadProject, persistProjectDefaultsNow, refreshProjects],
  );

  const importProjectFromFolder = useCallback(
    async (path, { name } = {}) => {
      const clean = String(path || '').trim();
      if (!clean) {
        throw new Error('请填写项目文件夹路径');
      }
      if (selectedProjectRef.current) {
        await persistProjectDefaultsNow().catch(() => {});
      }
      const data = await importProjectFolder(clean, { name });
      const project = data.project;
      await refreshProjects();
      if (project?.id) {
        await loadProject(project.id);
      }
      return project;
    },
    [loadProject, persistProjectDefaultsNow, refreshProjects],
  );

  const deleteProject = useCallback(
    (project) =>
      run(`deleteProject:${project.id}`, async () => {
        const confirmed = await askConfirm({
          title: '删除项目',
          body: '项目会进入回收站，项目文件和历史数据不会立刻从磁盘删除。',
          tone: 'danger',
          confirmLabel: '删除',
          items: [
            { label: '项目', value: project.name },
            { label: '编号', value: project.id },
          ],
        });
        if (!confirmed) return;
        await flushPersist();
        await request(`/api/projects/${project.id}`, { method: 'DELETE' });
        await refreshProjects();
        if (selectedProjectRef.current?.id === project.id) {
          clearProjectContext();
          setView('projects');
        }
        notify(`项目已移入回收站：${project.name}`, 'success');
      }),
    [askConfirm, clearProjectContext, flushPersist, notify, refreshProjects, run, setView],
  );

  const restoreProject = useCallback(
    (project) =>
      run(`restoreProject:${project.id}`, async () => {
        await request(`/api/projects/${project.id}/restore`, { method: 'POST' });
        await refreshProjects();
        notify(`项目已恢复：${project.name}`, 'success');
      }),
    [notify, refreshProjects, run],
  );

  useEffect(() => {
    if (!selectedProject?.id || !activeSegment?.id) {
      setPromptCards([]);
      return;
    }
    refreshPromptCards(selectedProject.id, activeSegment.id).catch(() => {});
  }, [selectedProject?.id, activeSegment?.id, refreshPromptCards, notify]);

  useEffect(() => {
    const persistBeforeUnload = () => persistPendingWorkspace({ clearTimer: true });
    const persistWhenHidden = () => {
      if (document.visibilityState === 'hidden') persistPendingWorkspace();
    };
    window.addEventListener('beforeunload', persistBeforeUnload);
    document.addEventListener('visibilitychange', persistWhenHidden);
    return () => {
      window.removeEventListener('beforeunload', persistBeforeUnload);
      document.removeEventListener('visibilitychange', persistWhenHidden);
    };
  }, [persistPendingWorkspace]);

  return {
    projects,
    projectListLoaded,
    projectListError,
    selectedProject,
    workspace,
    workspaceRef,
    projectState,
    projectDraft,
    setProjectDraft,
    entityCards,
    setEntityCards,
    entityMaterials,
    setEntityMaterials,
    assets,
    promptCards,
    setPromptCards,
    splitSuggestions,
    setSplitSuggestions,
    workflowUi,
    refreshWorkflowUi,
    refreshWorkspace,
    applyWorkspaceResponse,
    activeSegment,
    activeScript,
    refreshProjects,
    refreshProjectState,
    refreshEntityCards,
    refreshEntityMaterials,
    refreshAssets,
    refreshSourceAssets,
    refreshPromptCards,
    loadProject,
    clearProjectContext,
    schedulePersist,
    flushPersist,
    updateWorkspace,
    syncWorkspacePatch,
    restoreStoredProject,
    createProject,
    selectProject,
    switchProject,
    updateProjectName,
    updateProjectInfo,
    openProjectView,
    openProjectsHub,
    updateProjectDefaults,
    saveProjectDefaults,
    exportSelectedProject,
    importProjectFromZip,
    importProjectFromFolder,
    deleteProject,
    restoreProject,
  };
}
