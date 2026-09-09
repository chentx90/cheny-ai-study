import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { API_BASE, request, requestWithRetry, setUnauthorizedHandler } from './api/client';
import { navItems, isXyqVideoProvider } from './constants';
import { readStoredUiState, storeUiState } from './app/uiStorage';
import { readRouteState, syncRouteState } from './app/routeState';
import { readVideoRequestSettings, sanitizeVideoRequestSettings } from './app/videoRequestSettings';
import { useAsyncRun } from './hooks/useAsyncRun';
import { useApiConfig } from './hooks/useApiConfig';
import { useAuth } from './hooks/useAuth';
import { useSegmentLocks } from './hooks/useSegmentLocks';
import { useProjectWorkspace } from './hooks/useProjectWorkspace';
import { useVideoTasks } from './hooks/useVideoTasks';
import { useEntityAssets } from './hooks/useEntityAssets';
import { usePreprocess } from './hooks/usePreprocess';
import { usePromptCards } from './hooks/usePromptCards';
import { usePromptTemplates } from './hooks/usePromptTemplates';
import { useWorkflowAgent } from './hooks/useWorkflowAgent';
import { useAgentInvalidation } from './hooks/useAgentInvalidation';
import ProjectGate from './components/ProjectGate';
import ProjectsView from './views/ProjectsView';
import PreprocessView from './views/PreprocessView';
import ResourceHubView from './views/ResourceHubView';
import VideoView from './views/VideoView';
import PromptsView from './views/PromptsView';
import SettingsView from './views/SettingsView';
import ConfirmDialog from './components/ConfirmDialog';
import ToastHost from './components/ToastHost';
import VideoRequestDialog from './views/video/VideoRequestDialog';
import { taskVideoRequestSettings } from './views/video/videoViewUtils';
import AgentDock from './components/AgentDock';
import { ProjectSidebar, TopNavigation } from './components/AppNavigation';
import { applyAppearance, readAppearanceSettings, writeAppearanceSettings } from './themeUtils';
import './styles.css';

export default function App() {
  const initialRoute = useMemo(() => readRouteState(), []);
  const [health, setHealth] = useState('checking');
  const [templates, setTemplates] = useState([]);
  const [apiConfig, setApiConfig] = useState({});
  const [settingsSaveVersion, setSettingsSaveVersion] = useState(0);
  const [precheck, setPrecheck] = useState(null);
  const videoProvider = apiConfig?.videoProvider || '';
  const isXyq = isXyqVideoProvider(videoProvider);
  const [videoRequestSettings, setVideoRequestSettings] = useState(() => readVideoRequestSettings(videoProvider));
  const [videoRequestDialog, setVideoRequestDialog] = useState(null);
  const { busy, notice, toasts, confirmDialog, notify, dismissToast, askConfirm, resolveConfirm, run, setNotice } =
    useAsyncRun();
  const auth = useAuth({ notify });
  const {
    user,
    capabilities,
    authState,
    authDisabled,
    isAdmin,
    canWriteProject,
    canDeleteProject,
    canManageMembers,
    refreshMe,
  } = auth;
  const [view, setView] = useState(() => initialRoute.view || readStoredUiState().view);
  const [selectedTemplateId, setSelectedTemplateId] = useState(() => readStoredUiState().selectedTemplateId);
  const [projectFilter, setProjectFilter] = useState(() => readStoredUiState().projectFilter);
  const [promptCategory, setPromptCategory] = useState(() => readStoredUiState().promptCategory);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readStoredUiState().sidebarCollapsed);
  const [projectListLayout, setProjectListLayout] = useState(() => readStoredUiState().projectListLayout);
  const [projectSortBy, setProjectSortBy] = useState(() => readStoredUiState().projectSortBy);
  const [appearance, setAppearanceState] = useState(() => readAppearanceSettings());
  const resetCardDraftRef = useRef(() => {});
  const refreshVideoTasksRef = useRef(async () => {});
  const authStateRef = useRef(authState);
  authStateRef.current = authState;

  const workspaceApi = useProjectWorkspace({
    run,
    notify,
    setNotice,
    askConfirm,
    setView,
    view,
    resetCardDraft: () => resetCardDraftRef.current(),
    refreshVideoTasks: (projectId) => refreshVideoTasksRef.current(projectId),
  });

  const {
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
    activeSegment,
    activeScript,
    refreshProjects,
    refreshProjectState,
    refreshEntityCards,
    refreshEntityMaterials,
    refreshAssets,
    refreshSourceAssets,
    loadProject,
    updateWorkspace,
    restoreStoredProject,
    createProject,
    selectProject,
    switchProject,
    openProjectView,
    openProjectsHub,
    updateProjectName,
    updateProjectInfo,
    updateProjectDefaults,
    saveProjectDefaults,
    exportSelectedProject,
    importProjectFromZip,
    importProjectFromFolder,
    deleteProject,
    restoreProject,
    schedulePersist,
    flushPersist,
  } = workspaceApi;

  const workflowAgent = useWorkflowAgent({
    projectId: selectedProject?.id,
    currentView: view,
    activeContext: {
      segment_id: activeSegment?.id || '',
      segment_title: activeSegment?.title || '',
      has_script: Boolean(activeScript?.trim()),
    },
  });

  useEffect(() => {
    syncRouteState(view, selectedProject?.id || '');
  }, [view, selectedProject?.id]);

  const segmentLocks = useSegmentLocks({
    selectedProject,
    activeSegment,
    user,
    canWriteProject,
    notify,
  });
  const {
    lockForSegment,
    isLockedByOther,
    canEditSegment,
    selectSegment: selectSegmentWithLock,
    segmentLockError,
  } = segmentLocks;
  const segmentReadOnly = !canWriteProject || !canEditSegment(activeSegment?.id);
  const documentReadOnly = !canWriteProject;

  const askVideoRequest = useCallback(
    (card) =>
      new Promise((resolve) => {
        setVideoRequestDialog({ mode: 'create', card, resolve });
      }),
    [],
  );

  const askVideoRetry = useCallback(
    (task) =>
      new Promise((resolve) => {
        const card = promptCards.find((item) => item.id === task.prompt_card_id) || null;
        setVideoRequestDialog({ mode: 'retry', task, card, resolve });
      }),
    [promptCards],
  );

  const videoTasksApi = useVideoTasks({
    run,
    notify,
    askConfirm,
    askVideoRetry,
    selectedProject,
    refreshProjectState,
    apiBase: API_BASE,
  });
  refreshVideoTasksRef.current = videoTasksApi.refreshVideoTasks;

  const entityAssets = useEntityAssets({
    run,
    notify,
    askConfirm,
    selectedProject,
    refreshAssets,
    refreshEntityCards,
    refreshEntityMaterials,
    setEntityCards,
    setEntityMaterials,
    updateWorkspace,
  });
  resetCardDraftRef.current = entityAssets.resetCardDraft;

  const preprocess = usePreprocess({
    run,
    notify,
    askConfirm,
    selectedProject,
    workspace,
    workspaceRef,
    activeSegment,
    videoTasks: videoTasksApi.videoTasks,
    setSplitSuggestions,
    setPromptCards,
    updateWorkspace,
    refreshVideoTasks: videoTasksApi.refreshVideoTasks,
    refreshProjectState,
    refreshWorkspace: workspaceApi.refreshWorkspace,
    applyWorkspaceResponse: workspaceApi.applyWorkspaceResponse,
    syncWorkspacePatch: workspaceApi.syncWorkspacePatch,
  });

  const promptCardsApi = usePromptCards({
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
    videoProvider,
    prependVideoTask: videoTasksApi.prependVideoTask,
  });

  const {
    saveApiConfig,
    testLlmConnection,
    testVideoConnection,
    testImageConnection,
    fetchVideoModels,
    loadVideoModels,
    runPrecheck,
  } = useApiConfig({ run, notify, apiConfig, setApiConfig, setPrecheck, setSettingsSaveVersion });

  function setAppearance(patch) {
    setAppearanceState((prev) => {
      const next = { ...prev, ...(patch || {}) };
      writeAppearanceSettings(next);
      applyAppearance(next);
      return next;
    });
  }

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (authStateRef.current === 'authenticated') {
        refreshMe().catch(() => {});
      }
    });
  }, [refreshMe]);

  useEffect(() => {
    if (authState !== 'authenticated') return undefined;
    boot();
    return undefined;
  }, [authState]);

  useEffect(() => {
    if (!selectedProject?.id || authState !== 'authenticated') return;
    refreshMe(selectedProject.id).catch(() => {});
  }, [selectedProject?.id, authState, refreshMe]);

  useEffect(() => {
    applyAppearance(appearance);
    if (appearance.themeMode !== 'system') return undefined;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => applyAppearance(appearance);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [appearance]);

  useEffect(() => {
    storeUiState({
      view,
      projectFilter,
      selectedTemplateId,
      promptCategory,
      sidebarCollapsed,
      projectListLayout,
      projectSortBy,
      ...(selectedProject?.id ? { selectedProjectId: selectedProject.id } : {}),
    });
  }, [
    view,
    projectFilter,
    selectedTemplateId,
    promptCategory,
    sidebarCollapsed,
    projectListLayout,
    projectSortBy,
    selectedProject?.id,
  ]);

  useEffect(() => {
    if (!selectedProject?.id || view === 'projects') return;
    const prev = readStoredUiState().projectLastViews || {};
    if (prev[selectedProject.id] === view) return;
    storeUiState({ projectLastViews: { ...prev, [selectedProject.id]: view } });
  }, [view, selectedProject?.id]);

  async function loadStartupSettings() {
    const [templateResult, configResult, precheckResult] = await Promise.allSettled([
      requestWithRetry('/api/prompts/templates', {}, { attempts: 3, delayMs: 300 }),
      requestWithRetry('/api/config/apis', {}, { attempts: 3, delayMs: 300 }),
      requestWithRetry('/api/config/precheck', { method: 'POST' }, { attempts: 3, delayMs: 300 }),
    ]);
    if (templateResult.status === 'fulfilled') {
      const loadedTemplates = templateResult.value.templates || [];
      setTemplates(loadedTemplates);
      setSelectedTemplateId((current) => {
        if (loadedTemplates.some((template) => template.id === current)) return current;
        return loadedTemplates.find((template) => template.category === promptCategory)?.id || loadedTemplates[0]?.id || '';
      });
    } else {
      notify(`提示词模板加载失败：${templateResult.reason?.message || '未知错误'}`, 'error');
    }
    if (configResult.status === 'fulfilled') {
      setApiConfig(configResult.value.data);
    } else {
      notify(`API 配置加载失败：${configResult.reason?.message || '未知错误'}`, 'error');
    }
    if (precheckResult.status === 'fulfilled') {
      setPrecheck(precheckResult.value);
    }
  }

  async function boot() {
    await run('boot', async () => {
      let projectList = [];
      try {
        await requestWithRetry('/api/health', { timeoutMs: 5000 }, { attempts: 8, delayMs: 400 });
        setHealth('ok');
        projectList = await refreshProjects({ retry: true });
      } catch (error) {
        setHealth('error');
        // Avoid infinite "项目列表加载中" when backend is hung/unreachable.
        try {
          await refreshProjects({ retry: false });
        } catch (_listError) {
          // refreshProjects already records projectListError / loaded flag
        }
        throw error;
      }
      await loadStartupSettings();
      const routeProject = projectList.find(
        (project) => project.id === initialRoute.projectId && !project.deleted_at,
      );
      if (routeProject) await loadProject(routeProject.id);
      else await restoreStoredProject(projectList);
    });
  }

  function resolveVideoRequest(value) {
    if (videoRequestDialog?.resolve) videoRequestDialog.resolve(value);
    setVideoRequestDialog(null);
  }

  const promptTemplatesApi = usePromptTemplates({
    run,
    notify,
    askConfirm,
    setTemplates,
    setSelectedTemplateId,
  });

  const refreshTemplatesAfterAgent = useCallback(async () => {
    const data = await request('/api/prompts/templates');
    const loadedTemplates = data.templates || [];
    setTemplates(loadedTemplates);
    setSelectedTemplateId((current) => (
      loadedTemplates.some((template) => template.id === current)
        ? current
        : loadedTemplates[0]?.id || ''
    ));
  }, []);

  const refreshEntitiesAfterAgent = useCallback(
    (projectId) => Promise.all([
      refreshEntityCards(projectId),
      refreshEntityMaterials(projectId),
    ]),
    [refreshEntityCards, refreshEntityMaterials],
  );

  useAgentInvalidation({
    mutationEvent: workflowAgent.mutationEvent,
    projectId: selectedProject?.id || '',
    activeSegmentId: activeSegment?.id || '',
    notify,
    refreshProjects,
    refreshProjectState,
    refreshWorkflow: workspaceApi.refreshWorkflowUi,
    refreshWorkspace: workspaceApi.refreshWorkspace,
    refreshEntities: refreshEntitiesAfterAgent,
    refreshAssets,
    refreshPromptCards: workspaceApi.refreshPromptCards,
    refreshVideos: videoTasksApi.refreshVideoTasks,
    refreshTemplates: refreshTemplatesAfterAgent,
  });

  const filteredProjects = projects.filter((project) => {
    if (projectFilter === 'trash') return Boolean(project.deleted_at);
    if (project.deleted_at) return false;
    return projectFilter === 'all' || project.category === projectFilter;
  });

  useEffect(() => {
    setVideoRequestSettings(readVideoRequestSettings(videoProvider));
  }, [videoProvider]);

  const effectiveVideoRequestSettings = useMemo(() => {
    if (videoRequestDialog?.mode === 'retry' && videoRequestDialog?.task) {
      return sanitizeVideoRequestSettings(taskVideoRequestSettings(videoRequestDialog.task), videoProvider);
    }
    const scoped = sanitizeVideoRequestSettings(videoRequestSettings, videoProvider);
    if (isXyq) {
      // 小云雀不使用项目里可能残留的网关默认模型
      return scoped;
    }
    return sanitizeVideoRequestSettings(
      {
        ...scoped,
        model: workspace.defaultVideoModel || scoped.model,
        aspectRatio: workspace.defaultAspectRatio || scoped.aspectRatio,
        duration: workspace.defaultVideoDuration || scoped.duration,
        resolution: workspace.defaultResolution || scoped.resolution,
      },
      videoProvider,
    );
  }, [
    videoRequestDialog,
    videoRequestSettings,
    videoProvider,
    isXyq,
    workspace.defaultVideoModel,
    workspace.defaultAspectRatio,
    workspace.defaultVideoDuration,
    workspace.defaultResolution,
  ]);

  const visibleNavItems = navItems.filter((item) => !item.adminOnly);

  const currentView = [...visibleNavItems, { id: 'settings', label: '设置' }].find((item) => item.id === view);

  if (authState !== 'authenticated') {
    return (
      <main className="login-screen">
        <div className="login-status-card">
          <Loader2 className="spin" />
          <span>正在连接本地服务…</span>
        </div>
      </main>
    );
  }

  return (
    <main
      className={`${sidebarCollapsed ? 'app-shell sidebar-collapsed' : 'app-shell'}${workflowAgent.collapsed ? ' agent-collapsed' : ''}`}
      style={{ '--agent-dock-width': `${workflowAgent.width}px` }}
    >
      <ProjectSidebar
        authDisabled={authDisabled}
        health={health}
        projects={projects}
        selectedProject={selectedProject}
        sidebarCollapsed={sidebarCollapsed}
        user={user}
        onOpenProjects={openProjectsHub}
        onSwitchProject={switchProject}
        onToggle={() => setSidebarCollapsed((value) => !value)}
      />

      <section className="workspace">
        <TopNavigation
          currentViewLabel={currentView?.label}
          items={visibleNavItems}
          notice={notice}
          selectedProject={selectedProject}
          view={view}
          onChangeView={setView}
        />
        {view === 'projects' && (
          <ProjectsView
            projects={filteredProjects}
            projectListLoaded={projectListLoaded}
            projectListError={projectListError}
            selectedProject={selectedProject}
            projectState={projectState}
            workspace={workspace}
            projectDraft={projectDraft}
            projectFilter={projectFilter}
            projectListLayout={projectListLayout}
            projectSortBy={projectSortBy}
            entityCardCount={entityCards.length}
            busy={busy}
            setProjectDraft={setProjectDraft}
            setProjectFilter={setProjectFilter}
            setProjectListLayout={setProjectListLayout}
            setProjectSortBy={setProjectSortBy}
            createProject={createProject}
            selectProject={selectProject}
            refreshProjects={() => run('refreshProjects', () => refreshProjects({ retry: true }))}
            updateProjectName={updateProjectName}
            updateProjectInfo={updateProjectInfo}
            updateProjectDefaults={updateProjectDefaults}
            saveProjectDefaults={() =>
              saveProjectDefaults().catch((error) => notify(error.message, 'error'))
            }
            exportSelectedProject={(projectId) =>
              run('exportProject', async () => {
                const filename = await exportSelectedProject(projectId);
                notify(`项目已导出：${filename}`, 'success');
              })
            }
            importProjectFromZip={(file, options) =>
              run('importProjectZip', async () => {
                const project = await importProjectFromZip(file, options);
                notify(`项目已导入：${project?.name || '新项目'}`, 'success');
              })
            }
            importProjectFromFolder={(path, options) =>
              run('importProjectFolder', async () => {
                const project = await importProjectFromFolder(path, options);
                notify(`项目已导入：${project?.name || '新项目'}`, 'success');
              })
            }
            deleteProject={deleteProject}
            restoreProject={restoreProject}
            canDeleteProject={canDeleteProject}
            canManageMembers={canManageMembers}
            canWriteProject={canWriteProject}
            isAdmin={isAdmin && !authDisabled}
            notify={notify}
            run={run}
            uploadProjectAssets={entityAssets.uploadProjectAssets}
            refreshSourceAssets={(projectId) =>
              run('refreshSourceAssets', async () => {
                const data = await refreshSourceAssets(projectId || selectedProject?.id);
                notify(`已刷新原始素材：导入 ${data.imported || 0} 个文件`, 'success');
              })
            }
            videoTaskCount={videoTasksApi.videoTasks.length}
            videoProvider={videoProvider}
            loadVideoModels={loadVideoModels}
          />
        )}
        {view === 'preprocess' && (
          <ProjectGate selectedProject={selectedProject}>
            <PreprocessView
              workspace={workspace}
              activeSegment={activeSegment}
              activeScript={activeScript}
              splitSuggestions={splitSuggestions}
              busy={busy}
              projectName={selectedProject?.name}
              templates={templates}
              updateWorkspace={updateWorkspace}
              flushPersist={flushPersist}
              splitDocument={preprocess.splitDocument}
              applySplitSuggestion={preprocess.applySplitSuggestion}
              uploadProjectDocument={preprocess.uploadProjectDocument}
              convertCurrentSegment={preprocess.convertCurrentSegment}
              convertAllSegments={preprocess.convertAllSegments}
              saveAllSegmentSources={preprocess.saveAllSegmentSources}
              saveAllScriptSources={preprocess.saveAllScriptSources}
              saveActiveSegmentSource={preprocess.saveActiveSegmentSource}
              saveActiveScriptSource={preprocess.saveActiveScriptSource}
              enterScriptStage={preprocess.enterScriptStage}
              updateActiveScript={preprocess.updateActiveScript}
              readOnly={segmentReadOnly}
              documentReadOnly={documentReadOnly}
              segmentLocks={segmentLocks.locks}
              lockForSegment={lockForSegment}
              isLockedByOther={isLockedByOther}
              segmentLockError={segmentLockError}
              onSelectSegment={(segment) =>
                selectSegmentWithLock(segment, (segmentId) => updateWorkspace({ activeSegmentId: segmentId }))
              }
            />
          </ProjectGate>
        )}
        {view === 'resources' && (
          <ProjectGate selectedProject={selectedProject}>
            <ResourceHubView
              key={selectedProject?.id || 'no-project'}
              entityCards={entityCards}
              entityMaterials={entityMaterials}
              assets={assets}
              cardDraft={entityAssets.cardDraft}
              editingCardId={entityAssets.editingCardId}
              selectedProject={selectedProject}
              apiBase={API_BASE}
              apiConfig={apiConfig}
              busy={busy}
              workspace={workspace}
              agentMutation={workflowAgent.mutationEvent}
              run={run}
              notify={notify}
              askConfirm={askConfirm}
              refreshEntityCards={refreshEntityCards}
              refreshAssets={refreshAssets}
              setCardDraft={entityAssets.setCardDraft}
              createEntityCard={entityAssets.createEntityCard}
              editEntityCard={entityAssets.editEntityCard}
              cancelEntityCardEdit={entityAssets.cancelEntityCardEdit}
              deleteEntityCard={entityAssets.deleteEntityCard}
              uploadProjectAssets={entityAssets.uploadProjectAssets}
              renameAsset={entityAssets.renameAsset}
              addEntityMaterials={entityAssets.addEntityMaterials}
              uploadEntityMaterialFiles={entityAssets.uploadEntityMaterialFiles}
              deleteEntityMaterial={entityAssets.deleteEntityMaterial}
              deleteEntityMaterialPool={entityAssets.deleteEntityMaterialPool}
              deleteAsset={entityAssets.deleteAsset}
            />
          </ProjectGate>
        )}
        {view === 'video' && (
          <ProjectGate selectedProject={selectedProject}>
            <VideoView
              workspace={workspace}
              entityCards={entityCards}
              assets={assets}
              selectedProject={selectedProject}
              apiBase={API_BASE}
              apiConfig={apiConfig}
              appearance={appearance}
              videoTasks={videoTasksApi.videoTasks}
              videoOutputs={videoTasksApi.videoOutputs}
              promptCards={promptCards}
              templates={templates}
              selectedTemplateId={selectedTemplateId}
              activeScript={activeScript}
              busy={busy}
              setActiveSegment={(id) => {
                const segment = workspace.segments.find((item) => item.id === id);
                if (segment) {
                  selectSegmentWithLock(segment, (segmentId) => updateWorkspace({ activeSegmentId: segmentId }));
                  return;
                }
                updateWorkspace({ activeSegmentId: id });
              }}
              readOnly={segmentReadOnly}
              setSelectedTemplateId={setSelectedTemplateId}
              updateWorkspace={updateWorkspace}
              generatePromptCards={promptCardsApi.generatePromptCards}
              rerunPromptCard={promptCardsApi.rerunPromptCard}
              togglePromptCardLock={promptCardsApi.togglePromptCardLock}
              matchPromptCardSubjects={promptCardsApi.matchPromptCardSubjects}
              updatePromptCardSubjects={promptCardsApi.updatePromptCardSubjects}
              savePromptCard={promptCardsApi.savePromptCard}
              deletePromptCard={promptCardsApi.deletePromptCard}
              resolveMentions={promptCardsApi.resolveMentions}
              generatePromptCardVideo={promptCardsApi.generatePromptCardVideo}
              retryVideoTask={videoTasksApi.retryVideoTask}
              downloadVideoTask={videoTasksApi.downloadVideoTask}
              recoverVideoTask={videoTasksApi.recoverVideoTask}
              deleteVideoTask={videoTasksApi.deleteVideoTask}
              syncVideoTasks={videoTasksApi.syncVideoTasks}
              adoptVideoOutput={videoTasksApi.adoptVideoOutput}
            />
          </ProjectGate>
        )}
        {view === 'prompts' && (
          <PromptsView
            templates={templates}
            selectedTemplateId={selectedTemplateId}
            promptCategory={promptCategory}
            busy={busy}
            setSelectedTemplateId={setSelectedTemplateId}
            setPromptCategory={setPromptCategory}
            savePromptTemplate={promptTemplatesApi.savePromptTemplate}
            deletePromptTemplate={promptTemplatesApi.deletePromptTemplate}
            loadPromptTemplateVersions={promptTemplatesApi.loadPromptTemplateVersions}
            restorePromptTemplateVersion={promptTemplatesApi.restorePromptTemplateVersion}
          />
        )}
        {view === 'settings' && (
          <SettingsView
            apiConfig={apiConfig}
            precheck={precheck}
            saveApiConfig={saveApiConfig}
            testLlmConnection={testLlmConnection}
            testVideoConnection={testVideoConnection}
            testImageConnection={testImageConnection}
            fetchVideoModels={fetchVideoModels}
            runPrecheck={runPrecheck}
            busy={busy}
            settingsSaveVersion={settingsSaveVersion}
            appearance={appearance}
            setAppearance={setAppearance}
          />
        )}
      </section>
      <AgentDock
        agent={workflowAgent}
        projectName={selectedProject?.name}
        projectId={selectedProject?.id}
        assets={assets}
        apiBase={API_BASE}
        uploadProjectAssets={entityAssets.uploadProjectAssets}
      />
      <ToastHost toasts={toasts} onDismiss={dismissToast} />
      <ConfirmDialog
        dialog={confirmDialog}
        onCancel={() => resolveConfirm(false)}
        onConfirm={(value) => resolveConfirm(value)}
      />
      <VideoRequestDialog
        dialog={videoRequestDialog}
        savedSettings={effectiveVideoRequestSettings}
        assets={assets}
        entityCards={entityCards}
        videoProvider={apiConfig?.videoProvider}
        loadVideoModels={loadVideoModels}
        onCancel={() => resolveVideoRequest(false)}
        onSubmit={(settings) => resolveVideoRequest(settings)}
      />
    </main>
  );
}
