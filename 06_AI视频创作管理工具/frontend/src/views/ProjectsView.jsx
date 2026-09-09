import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  BadgeCheck,
  ChevronUp,
  Database,
  Download,
  FolderInput,
  FolderOpen,
  LayoutGrid,
  List,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Shield,
  SlidersHorizontal,
  Trash2,
  Upload,
  UserPlus,
} from 'lucide-react';
import Empty from '../components/Empty';
import Metric from '../components/Metric';
import PanelTitle from '../components/PanelTitle';
import ProjectCard from '../components/ProjectCard';
import {
  fetchProjectMembers,
  fetchProjectMemberCandidates,
  removeProjectMember,
  updateProjectVisibility,
  upsertProjectMember,
} from '../api/auth';
import {
  videoAspectRatioOptions,
  videoResolutionOptions,
} from '../constants';
import VideoModelCombobox from '../components/VideoModelCombobox';
import { categoryLabel } from '../utils';
import {
  filterProjectsBySearch,
  formatProjectDate,
  projectDefaultSettings,
  projectListMeta,
  sortProjects,
  workflowStateLabel,
} from '../utils/projectUtils';
import {
  readProjectUiPrefs,
  startProjectColumnResize,
  writeProjectUiPrefs,
} from './projectViewUtils';

const assetUploadAccept = 'image/*,audio/*,video/*';

export default function ProjectsView({
  projects,
  projectListLoaded = true,
  projectListError = '',
  selectedProject,
  projectState,
  workspace,
  projectDraft,
  projectFilter,
  projectListLayout = 'list',
  projectSortBy = 'updated',
  entityCardCount = 0,
  busy,
  setProjectDraft,
  setProjectFilter,
  setProjectListLayout,
  setProjectSortBy,
  createProject,
  selectProject,
  refreshProjects,
  updateProjectName,
  updateProjectInfo,
  updateProjectDefaults,
  saveProjectDefaults,
  exportSelectedProject,
  importProjectFromZip,
  importProjectFromFolder,
  deleteProject,
  restoreProject,
  canDeleteProject = false,
  canManageMembers = false,
  canWriteProject = true,
  isAdmin = false,
  notify,
  run,
  uploadProjectAssets,
  refreshSourceAssets,
  videoTaskCount = 0,
  videoProvider = '',
  loadVideoModels,
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [columnLayout, setColumnLayout] = useState(() => readProjectUiPrefs());
  const [members, setMembers] = useState([]);
  const [memberDraft, setMemberDraft] = useState({ userIds: [], role: 'editor' });
  const [memberCandidates, setMemberCandidates] = useState([]);
  const [memberCandidatesLoading, setMemberCandidatesLoading] = useState(false);
  const [projectNameDraft, setProjectNameDraft] = useState('');
  const [projectDescriptionDraft, setProjectDescriptionDraft] = useState('');
  const [projectStylePromptDraft, setProjectStylePromptDraft] = useState('');
  const projectStyleComposing = useRef(false);
  const [importFolderPath, setImportFolderPath] = useState('');
  const [showCreateExtras, setShowCreateExtras] = useState(false);
  const defaults = projectDefaultSettings(workspace);
  const saveDefaults = () => saveProjectDefaults?.().catch((error) => notify?.(error.message, 'error'));
  const saveDefaultsButton = (
    <button
      type="button"
      className="icon-button"
      title="保存项目默认设置"
      aria-label="保存项目默认设置"
      disabled={!canWriteProject || busy.has('saveProjectDefaults')}
      onClick={saveDefaults}
    >
      {busy.has('saveProjectDefaults') ? <Loader2 className="spin" /> : <Save />}
    </button>
  );

  const visibleProjects = useMemo(() => {
    const searched = filterProjectsBySearch(projects, searchQuery);
    return sortProjects(searched, projectSortBy);
  }, [projects, searchQuery, projectSortBy]);

  const overviewProject = projectState?.project || selectedProject;
  const segmentCount = workspace?.segments?.length || 0;

  const progressLabel = selectedProject
    ? workflowStateLabel(selectedProject.current_state)
    : '请先创建或选择项目';
  const progressMeta = selectedProject ? projectListMeta(selectedProject) : '';
  const uploadBusy = busy.has('uploadProjectAssets') || busy.has('createProject');

  useEffect(() => {
    setProjectNameDraft(selectedProject?.name || '');
    setProjectDescriptionDraft(selectedProject?.description || '');
  }, [selectedProject?.id, selectedProject?.name, selectedProject?.description]);

  useEffect(() => {
    if (!projectStyleComposing.current) {
      setProjectStylePromptDraft(workspace?.projectStylePrompt || '');
    }
  }, [selectedProject?.id, workspace?.projectStylePrompt]);

  function commitProjectStylePrompt(value) {
    const next = String(value || '').trim();
    setProjectStylePromptDraft(next);
    if (next !== (workspace?.projectStylePrompt || '')) {
      updateProjectDefaults({ projectStylePrompt: next });
    }
  }

  useEffect(() => {
    if (!selectedProject?.id || !canManageMembers) {
      setMembers([]);
      setMemberCandidates([]);
      setMemberDraft({ userIds: [], role: 'editor' });
      return;
    }
    fetchProjectMembers(selectedProject.id)
      .then((data) => setMembers(data.members || []))
      .catch((error) => notify?.(error.message, 'error'));
    setMemberCandidatesLoading(true);
    fetchProjectMemberCandidates(selectedProject.id)
      .then((data) => setMemberCandidates(data.users || []))
      .catch((error) => notify?.(error.message, 'error'))
      .finally(() => setMemberCandidatesLoading(false));
  }, [selectedProject?.id, canManageMembers, notify]);

  const toggleMemberCandidate = (userId) => {
    setMemberDraft((prev) => {
      const exists = prev.userIds.includes(userId);
      return {
        ...prev,
        userIds: exists ? prev.userIds.filter((id) => id !== userId) : [...prev.userIds, userId],
      };
    });
  };

  function updateLeftWidth(nextLeft) {
    setColumnLayout((prev) => {
      const next = { ...prev, leftWidth: nextLeft };
      writeProjectUiPrefs(next);
      return next;
    });
  }

  async function handleAssetImport(event) {
    const files = event.target.files;
    event.target.value = '';
    if (!files?.length) return;

    let projectId = selectedProject?.id;
    if (!projectId) {
      const name = projectDraft.name?.trim();
      if (!name) return;
      projectId = await createProject();
    }

    if (projectId) {
      await uploadProjectAssets?.(files, projectId);
    }
  }

  return (
    <div
      className="work-grid project-grid"
      style={{
        gridTemplateColumns: `minmax(240px, ${columnLayout.leftWidth}fr) 8px minmax(320px, ${100 - columnLayout.leftWidth}fr)`,
      }}
    >
      <div className="project-left-column">
        <section className="panel project-hub-panel">
          <div className="project-create-row">
            <span className="project-create-label">
              <Plus />
              新建项目
            </span>
            <input
              className="project-create-input"
              value={projectDraft.name}
              placeholder="项目标题"
              onChange={(event) => setProjectDraft({ ...projectDraft, name: event.target.value })}
            />
            <button
              type="button"
              className="icon-button project-create-btn"
              title="创建项目"
              aria-label="创建项目"
              disabled={!projectDraft.name?.trim() || busy.has('createProject')}
              onClick={createProject}
            >
              {busy.has('createProject') ? <Loader2 className="spin" /> : <Plus />}
            </button>
            <label
              className={`upload-control compact icon-button project-create-upload ${uploadBusy ? 'is-disabled' : ''}`}
              title="导入素材"
              aria-label="导入素材"
            >
              {uploadBusy ? <Loader2 className="spin" /> : <Upload />}
              <input
                type="file"
                accept={assetUploadAccept}
                multiple
                disabled={uploadBusy || (!selectedProject && !projectDraft.name?.trim())}
                onChange={handleAssetImport}
              />
            </label>
            <span
              className="project-create-progress-inline"
              title={progressMeta ? `${progressLabel} · ${progressMeta}` : progressLabel}
            >
              进度 <strong>{progressLabel}</strong>
            </span>
            <button
              type="button"
              className="secondary compact icon-button project-create-more-btn"
              title={showCreateExtras ? '收起选项' : '更多选项'}
              aria-label={showCreateExtras ? '收起选项' : '更多选项'}
              onClick={() => setShowCreateExtras((value) => !value)}
            >
              {showCreateExtras ? <ChevronUp /> : <SlidersHorizontal />}
            </button>
          </div>
          {showCreateExtras && (
            <div className="project-create-extras form-stack bordered">
              <label>
                项目简介（可选）
                <textarea
                  rows={2}
                  value={projectDraft.description || ''}
                  placeholder="创建时写入项目简介"
                  onChange={(event) => setProjectDraft({ ...projectDraft, description: event.target.value })}
                />
              </label>
              <label>
                项目数据目录（可选）
                <input
                  value={projectDraft.dataRoot || ''}
                  placeholder="留空使用 projects/{项目ID}；须在工作区内"
                  onChange={(event) => setProjectDraft({ ...projectDraft, dataRoot: event.target.value })}
                />
              </label>
              <label>
                成片输出位置（可选）
                <input
                  value={projectDraft.outputRoot || ''}
                  placeholder="留空使用项目 generated 目录"
                  onChange={(event) => setProjectDraft({ ...projectDraft, outputRoot: event.target.value })}
                />
              </label>
              <label>
                原始素材目录（可选）
                <input
                  value={projectDraft.sourceAssetsRoot || ''}
                  placeholder="创建后可配合「刷新原始素材」导入"
                  onChange={(event) => setProjectDraft({ ...projectDraft, sourceAssetsRoot: event.target.value })}
                />
              </label>
            </div>
          )}

          <div className="project-list-toolbar">
            <div className="project-list-heading">
              <FolderOpen />
              <span>项目列表</span>
            </div>
            <label className="project-search-field">
              <Search />
              <input
                type="search"
                value={searchQuery}
                placeholder="搜索名称或 ID"
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </label>
            <select className="project-toolbar-select" value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)}>
              <option value="all">全部</option>
              <option value="active">进行中</option>
              <option value="draft">草稿</option>
              <option value="archive">归档</option>
              <option value="trash">回收站</option>
            </select>
            <select className="project-toolbar-select" value={projectSortBy} onChange={(event) => setProjectSortBy(event.target.value)}>
              <option value="updated">最近更新</option>
              <option value="created">最近创建</option>
              <option value="name">名称</option>
            </select>
            <div className="project-layout-toggle" role="group" aria-label="列表视图">
              <button
                type="button"
                className={projectListLayout === 'list' ? 'secondary active' : 'secondary'}
                title="列表视图"
                onClick={() => setProjectListLayout('list')}
              >
                <List />
              </button>
              <button
                type="button"
                className={projectListLayout === 'cards' ? 'secondary active' : 'secondary'}
                title="卡片视图"
                onClick={() => setProjectListLayout('cards')}
              >
                <LayoutGrid />
              </button>
            </div>
            <button type="button" className="secondary project-toolbar-refresh" title="刷新列表" onClick={refreshProjects}>
              <RefreshCw />
            </button>
          </div>

          <div className={projectListLayout === 'cards' ? 'project-card-grid project-list-scroll' : 'project-list project-list-scroll'}>
            {!projectListLoaded && <Empty text="项目列表加载中" />}
            {projectListLoaded && projectListError && projects.length === 0 && <Empty text={`项目列表加载失败：${projectListError}`} />}
            {projectListLoaded && !projectListError && projects.length === 0 && <Empty text="暂无项目" />}
            {projectListLoaded && !projectListError && projects.length > 0 && visibleProjects.length === 0 && (
              <Empty text="没有匹配的项目" />
            )}
            {projectListLayout === 'cards'
              ? visibleProjects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    selected={selectedProject?.id === project.id}
                    onSelect={selectProject}
                    onDelete={canDeleteProject ? deleteProject : undefined}
                    onRestore={restoreProject}
                    canDelete={canDeleteProject}
                  />
                ))
              : visibleProjects.map((project) => (
                  <div className="project-list-item" key={project.id}>
                    <button
                      className={selectedProject?.id === project.id ? 'project-row selected' : 'project-row'}
                      disabled={Boolean(project.deleted_at)}
                      onClick={() => selectProject(project.id)}
                    >
                      <strong>{project.name}</strong>
                      <small>
                        {project.deleted_at ? '回收站' : categoryLabel(project.category)}
                        {project.visibility === 'public' ? ' · 公共' : ' · 私有'}
                        {project.my_role ? ` · ${project.my_role}` : ''} · 更新 {formatProjectDate(project.updated_at)}
                      </small>
                      {project.description ? (
                        <span className="project-row-desc">{project.description}</span>
                      ) : null}
                      <span className="project-row-meta">{projectListMeta(project)}</span>
                      {selectedProject?.id === project.id && <BadgeCheck />}
                    </button>
                    {project.deleted_at ? (
                      <button type="button" className="icon-button secondary" title="恢复项目" onClick={() => restoreProject(project)}>
                        <RotateCcw />
                      </button>
                    ) : canDeleteProject ? (
                      <button type="button" className="icon-button danger" title="删除项目" onClick={() => deleteProject(project)}>
                        <Trash2 />
                      </button>
                    ) : null}
                  </div>
                ))}
          </div>
        </section>
      </div>

      <div
        className="project-column-resizer"
        role="separator"
        aria-label="调整项目列表与概览列宽度"
        onPointerDown={(event) =>
          startProjectColumnResize({
            event,
            startLeft: columnLayout.leftWidth,
            onChange: updateLeftWidth,
          })
        }
      />

      <section className="panel project-overview-panel">
        <PanelTitle icon={Database} title="项目概览" />
        {!selectedProject && <Empty text="请选择一个项目查看概览与设置" />}
        {selectedProject && (
          <div className="project-overview">
            <div className="project-overview-section">
              <h4>项目信息</h4>
              <div className={`project-info-form${!canWriteProject ? ' is-readonly' : ''}`}>
                <label>
                  项目名称
                  <input
                    value={projectNameDraft}
                    placeholder="输入项目名称"
                    disabled={!canWriteProject}
                    onChange={(event) => setProjectNameDraft(event.target.value)}
                  />
                </label>
                <label>
                  项目简介
                  <textarea
                    rows={4}
                    value={projectDescriptionDraft}
                    placeholder="可选：记录项目主题、目标平台、风格说明等"
                    disabled={!canWriteProject}
                    onChange={(event) => setProjectDescriptionDraft(event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  className="icon-button"
                  title="保存项目信息"
                  aria-label="保存项目信息"
                  disabled={
                    !canWriteProject ||
                    !projectNameDraft.trim() ||
                    (projectNameDraft.trim() === (selectedProject.name || '') &&
                      projectDescriptionDraft.trim() === (selectedProject.description || '')) ||
                    busy.has('updateProject')
                  }
                  onClick={() =>
                    updateProjectInfo?.({
                      name: projectNameDraft,
                      description: projectDescriptionDraft,
                    }).catch((error) => notify?.(error.message, 'error'))
                  }
                >
                  {busy.has('updateProject') ? <Loader2 className="spin" /> : <Save />}
                </button>
              </div>
            </div>

            <div className="project-summary metrics">
              <Metric label="当前阶段" value={workflowStateLabel(overviewProject?.current_state)} />
              <Metric label="分集数量" value={segmentCount > 0 ? `${segmentCount} 集` : overviewProject?.has_segments ? '已分集' : '未分集'} />
              <Metric label="实体卡" value={entityCardCount > 0 ? `${entityCardCount} 张` : '暂无'} />
              <Metric label="视频任务" value={videoTaskCount > 0 ? `${videoTaskCount} 个` : '暂无'} />
              <Metric label="最近更新" value={formatProjectDate(selectedProject.updated_at)} />
              <Metric label="创建时间" value={formatProjectDate(selectedProject.created_at)} />
            </div>

            <div className="project-overview-section">
              <h4>访问与成员</h4>
              <div className="project-access-panel">
                <div className="project-access-row">
                  <span>
                    可见性：{selectedProject.visibility === 'public' ? '公共项目' : '私有项目'}
                    {selectedProject.my_role ? ` · 我的角色：${selectedProject.my_role}` : ''}
                  </span>
                  {canManageMembers ? (
                    <select
                      value={selectedProject.visibility || 'private'}
                      disabled={!canWriteProject || busy.has('projectVisibility')}
                      onChange={(event) =>
                        run?.('projectVisibility', async () => {
                          await updateProjectVisibility(selectedProject.id, event.target.value);
                          await refreshProjects?.();
                          notify?.('项目可见性已更新', 'success');
                        }).catch((error) => notify?.(error.message, 'error'))
                      }
                    >
                      <option value="private">私有</option>
                      <option value="public">公共</option>
                    </select>
                  ) : null}
                </div>
                {canManageMembers ? (
                  <>
                    <p className="project-overview-hint">
                      从系统已有账号中勾选协作者，并选择项目角色后批量添加或更新。项目所有者无需重复添加。
                    </p>
                    <form
                      className="project-member-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const userIds = memberDraft.userIds.filter(Boolean);
                        if (!userIds.length) return;
                        run?.('projectMember', async () => {
                          for (const userId of userIds) {
                            await upsertProjectMember(selectedProject.id, {
                              user_id: userId,
                              role: memberDraft.role,
                            });
                          }
                          const data = await fetchProjectMembers(selectedProject.id);
                          setMembers(data.members || []);
                          setMemberDraft((prev) => ({ ...prev, userIds: [] }));
                          notify?.(
                            userIds.length === 1 ? '成员已添加或更新' : `已更新 ${userIds.length} 名成员`,
                            'success',
                          );
                        }).catch((error) => notify?.(error.message, 'error'));
                      }}
                    >
                      <div className="project-member-candidates">
                        {memberCandidatesLoading ? (
                          <p className="project-overview-hint">加载用户列表…</p>
                        ) : memberCandidates.length ? (
                          memberCandidates.map((user) => {
                            const memberRole = members.find((member) => member.user_id === user.id)?.role;
                            return (
                              <label key={user.id} className="project-member-candidate">
                                <input
                                  type="checkbox"
                                  checked={memberDraft.userIds.includes(user.id)}
                                  onChange={() => toggleMemberCandidate(user.id)}
                                />
                                <span>
                                  {user.display_name || user.username}
                                  {user.username ? ` (@${user.username})` : ''}
                                  {memberRole ? ` · 当前：${memberRole}` : ''}
                                </span>
                              </label>
                            );
                          })
                        ) : (
                          <p className="project-overview-hint">
                            暂无可添加用户，请先在管理后台创建账号。
                          </p>
                        )}
                      </div>
                      <div className="project-member-form-actions">
                        <select
                          value={memberDraft.role}
                          onChange={(event) => setMemberDraft((prev) => ({ ...prev, role: event.target.value }))}
                        >
                          <option value="viewer">只读</option>
                          <option value="editor">编辑</option>
                        </select>
                        <button type="submit" disabled={busy.has('projectMember') || !memberDraft.userIds.length}>
                          {busy.has('projectMember') ? <Loader2 className="spin" /> : <UserPlus />}
                          添加/更新所选
                        </button>
                      </div>
                    </form>
                    <div className="project-member-list">
                      {members.map((member) => (
                        <div key={member.user_id} className="project-member-row">
                          <span>
                            {member.display_name || member.username}
                            {member.display_name && member.username ? ` (@${member.username})` : ''} · {member.role}
                          </span>
                          {member.user_id !== selectedProject.owner_id ? (
                            <button
                              type="button"
                              className="secondary"
                              disabled={busy.has(`memberRemove-${member.user_id}`)}
                              onClick={() =>
                                run?.(`memberRemove-${member.user_id}`, async () => {
                                  await removeProjectMember(selectedProject.id, member.user_id);
                                  const data = await fetchProjectMembers(selectedProject.id);
                                  setMembers(data.members || []);
                                  notify?.('成员已移除', 'success');
                                }).catch((error) => notify?.(error.message, 'error'))
                              }
                            >
                              移除
                            </button>
                          ) : (
                            <span className="project-member-owner-tag">所有者</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="project-overview-hint">
                    {isAdmin ? '管理员可管理全部项目成员。' : '仅项目所有者可管理成员与可见性。'}
                  </p>
                )}
              </div>
            </div>

            <div className="project-overview-section">
              <h4>数据存储与导入导出</h4>
              <p className="project-overview-hint">
                项目数据（素材、成片、manifest、实体卡与提示词卡 JSON）统一存放在数据目录。留空则使用默认路径
                <code> projects/&#123;项目ID&#125; </code>。修改路径后请先保存，再执行导出或导入。
              </p>
              <div className={`form-stack bordered project-defaults-form${!canWriteProject ? ' is-readonly' : ''}`}>
                <label>
                  项目数据目录（可选）
                  <input
                    value={defaults.dataRoot}
                    placeholder="留空使用默认目录；可填绝对路径或相对工作区路径"
                    disabled={!canWriteProject}
                    onChange={(event) => updateProjectDefaults({ dataRoot: event.target.value })}
                  />
                </label>
                <div className="project-path-actions">
                  {saveDefaultsButton}
                </div>
                <div className="project-path-actions">
                  <button
                    type="button"
                    className="secondary"
                    disabled={!selectedProject || busy.has('exportProject')}
                    onClick={() =>
                      exportSelectedProject?.(selectedProject?.id).catch((error) => notify?.(error.message, 'error'))
                    }
                  >
                    {busy.has('exportProject') ? <Loader2 className="spin" /> : <Download />}
                    导出项目包（ZIP）
                  </button>
                  <label className={`upload-control compact ${busy.has('importProjectZip') ? 'is-disabled' : ''}`}>
                    {busy.has('importProjectZip') ? <Loader2 className="spin" /> : <Upload />}
                    从 ZIP 导入
                    <input
                      type="file"
                      accept=".zip,application/zip"
                      disabled={busy.has('importProjectZip')}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.target.value = '';
                        if (!file) return;
                        importProjectFromZip?.(file).catch((error) => notify?.(error.message, 'error'));
                      }}
                    />
                  </label>
                </div>
                <label>
                  从服务器文件夹导入（可选）
                  <input
                    value={importFolderPath}
                    placeholder="填写服务器可访问的项目文件夹路径（含 manifest.json）"
                    onChange={(event) => setImportFolderPath(event.target.value)}
                  />
                </label>
                <div className="project-path-actions">
                  <button
                    type="button"
                    className="secondary"
                    disabled={!importFolderPath.trim() || busy.has('importProjectFolder')}
                    onClick={() =>
                      importProjectFromFolder?.(importFolderPath)
                        .then(() => setImportFolderPath(''))
                        .catch((error) => notify?.(error.message, 'error'))
                    }
                  >
                    {busy.has('importProjectFolder') ? <Loader2 className="spin" /> : <FolderInput />}
                    导入文件夹
                  </button>
                </div>
              </div>
            </div>

            <div className="project-overview-section">
              <h4>项目默认设置</h4>
              <p className="project-overview-hint">
                视频默认值与成片/素材路径会随输入自动暂存；点击下方「保存路径与默认设置」立即写入服务器。
              </p>
              <div className={`form-stack bordered project-defaults-form${!canWriteProject ? ' is-readonly' : ''}`}>
                <label className="project-style-prompt-field">
                  项目风格提示词 · $project_style_prompt
                  <textarea
                    value={projectStylePromptDraft}
                    placeholder="例如：高端3D国漫、写实东方人物比例、低饱和电影光影、统一时代与材质表现"
                    disabled={!canWriteProject}
                    onChange={(event) => setProjectStylePromptDraft(event.target.value)}
                    onCompositionStart={() => { projectStyleComposing.current = true; }}
                    onCompositionEnd={(event) => {
                      projectStyleComposing.current = false;
                      commitProjectStylePrompt(event.currentTarget.value);
                    }}
                    onBlur={(event) => {
                      projectStyleComposing.current = false;
                      commitProjectStylePrompt(event.currentTarget.value);
                    }}
                  />
                </label>
                <label>
                  默认模型
                  <VideoModelCombobox
                    value={defaults.defaultVideoModel}
                    videoProvider={videoProvider}
                    loadVideoModels={loadVideoModels}
                    disabled={!canWriteProject}
                    onChange={(nextValue) => updateProjectDefaults({ defaultVideoModel: nextValue })}
                  />
                </label>
                <label>
                  默认画幅
                  <select
                    value={defaults.defaultAspectRatio}
                    onChange={(event) => updateProjectDefaults({ defaultAspectRatio: event.target.value })}
                  >
                    {videoAspectRatioOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  默认分辨率
                  <select
                    value={defaults.defaultResolution}
                    onChange={(event) => updateProjectDefaults({ defaultResolution: event.target.value })}
                  >
                    {videoResolutionOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  成片输出位置（可选）
                  <input
                    value={defaults.outputRoot}
                    placeholder="留空则使用项目 generated 目录；可填绝对路径或相对工作区路径"
                    onChange={(event) => updateProjectDefaults({ outputRoot: event.target.value })}
                  />
                </label>
                <label>
                  原始素材导入位置（可选）
                  <input
                    value={defaults.sourceAssetsRoot}
                    placeholder="填写素材文件夹路径，配合下方按钮刷新导入"
                    onChange={(event) => updateProjectDefaults({ sourceAssetsRoot: event.target.value })}
                  />
                </label>
                <div className="project-path-actions">
                  {saveDefaultsButton}
                  <button
                    type="button"
                    className="secondary"
                    disabled={!selectedProject || !defaults.sourceAssetsRoot?.trim() || busy.has('refreshSourceAssets')}
                    onClick={() => refreshSourceAssets?.(selectedProject?.id)}
                  >
                    {busy.has('refreshSourceAssets') ? <Loader2 className="spin" /> : <RefreshCw />}
                    刷新原始素材
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
