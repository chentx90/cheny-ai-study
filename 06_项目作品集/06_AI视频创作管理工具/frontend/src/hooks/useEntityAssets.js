import { useCallback, useState } from 'react';

import { request, uploadBinary } from '../api/client';
import { encodeAssetPath } from '../app/uiStorage';
import { typeLabel } from '../utils';
import { useProjectScope } from './useProjectScope';

function inferAssetType(file) {
  const mimeType = (file.type || '').toLowerCase();
  const filename = (file.name || '').toLowerCase();
  if (mimeType.startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp|svg|avif)$/.test(filename)) return 'image';
  if (mimeType.startsWith('audio/') || /\.(mp3|wav|m4a|aac|flac|ogg|opus)$/.test(filename)) return 'audio';
  if (mimeType.startsWith('video/') || /\.(mp4|mov|m4v|webm|avi|mkv)$/.test(filename)) return 'video';
  throw new Error(`不支持的素材类型：${file.name}`);
}

async function uploadAssetFile(projectId, assetType, file) {
  const formData = new FormData();
  formData.append('file', file, file.name);
  formData.append('asset_type', assetType);
  const data = await uploadBinary(`/api/projects/${projectId}/assets/upload`, formData);
  return data.path;
}

export function useEntityAssets({
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
}) {
  const isCurrentProject = useProjectScope(selectedProject?.id);
  const [cardDraft, setCardDraft] = useState({
    entity_name: '',
    type: 'character',
    state: '',
    tags: '',
    existingAssets: [],
  });
  const [editingCardId, setEditingCardId] = useState('');

  const resetCardDraft = useCallback(() => {
    setEditingCardId('');
    setCardDraft({
      entity_name: '',
      type: 'character',
      state: '',
      tags: '',
      existingAssets: [],
    });
  }, []);

  const uploadProjectAssets = useCallback(
    (files, projectId = selectedProject?.id) =>
      run('uploadProjectAssets', async () => {
        const targetProjectId = projectId || selectedProject?.id;
        if (!targetProjectId) throw new Error('请先选择项目');
        const incomingFiles = Array.from(files || []);
        if (incomingFiles.length === 0) return;
        const uploadJobs = incomingFiles.map((file) => ({
          file,
          assetType: inferAssetType(file),
        }));
        const paths = await Promise.all(
          uploadJobs.map((job) => uploadAssetFile(targetProjectId, job.assetType, job.file)),
        );
        await refreshAssets(targetProjectId);
        if (!isCurrentProject(targetProjectId)) return paths;
        updateWorkspace({ assetsConfirmed: false });
        notify(`已导入 ${incomingFiles.length} 个项目素材`, 'success');
        return paths;
      }),
    [isCurrentProject, notify, refreshAssets, run, selectedProject?.id, updateWorkspace],
  );

  const createEntityCard = useCallback(
    (event) =>
      run('createEntityCard', async () => {
        event?.preventDefault();
        const formElement = event?.currentTarget;
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        const payload = {
          entity_name: cardDraft.entity_name.trim(),
          type: cardDraft.type,
          state: cardDraft.state.trim() || null,
          tags: cardDraft.tags
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean),
          assets: Array.from(new Set(cardDraft.existingAssets || [])),
        };
        if (!payload.entity_name) throw new Error('实体卡名称不能为空');
        const card = await request(
          editingCardId
            ? `/api/projects/${selectedProject.id}/entity-cards/${editingCardId}`
            : `/api/projects/${selectedProject.id}/entity-cards`,
          {
            method: editingCardId ? 'PUT' : 'POST',
            body: JSON.stringify(payload),
          },
        );
        if (!isCurrentProject(projectId)) return card;
        setEntityCards((prev) => {
          const next = editingCardId ? prev.map((item) => (item.id === card.id ? card : item)) : [...prev, card];
          return next.sort((a, b) => a.entity_name.localeCompare(b.entity_name));
        });
        const action = editingCardId ? '更新' : '创建';
        resetCardDraft();
        formElement?.reset();
        await refreshEntityMaterials(projectId);
        updateWorkspace({ assetsConfirmed: false });
        notify(`实体卡已${action}：${card.entity_name}`, 'success');
        return card;
      }),
    [
      cardDraft,
      editingCardId,
      isCurrentProject,
      notify,
      refreshEntityMaterials,
      resetCardDraft,
      run,
      selectedProject,
      setEntityCards,
      updateWorkspace,
    ],
  );

  const editEntityCard = useCallback((card) => {
    setEditingCardId(card.id);
    setCardDraft({
      entity_name: card.entity_name,
      type: card.type,
      state: card.state || '',
      tags: card.tags?.join(',') || '',
      existingAssets:
        card.assets || [...(card.reference_images || []), ...(card.audio_samples || []), ...(card.video_clips || [])],
    });
  }, []);

  const cancelEntityCardEdit = useCallback(() => {
    resetCardDraft();
  }, [resetCardDraft]);

  const deleteEntityCard = useCallback(
    (card) =>
      run(`deleteEntityCard:${card.id}`, async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        const confirmed = await askConfirm({
          title: '删除实体卡',
          body: '实体卡删除后，已绑定到该卡的实体会失去素材引用，请确认后再执行。',
          tone: 'danger',
          confirmLabel: '删除',
          items: [
            { label: '实体卡', value: card.entity_name },
            { label: '状态', value: card.state || '默认' },
          ],
        });
        if (!confirmed) return;
        const data = await request(`/api/projects/${selectedProject.id}/entity-cards/${card.id}`, {
          method: 'DELETE',
        });
        if (!isCurrentProject(projectId)) return data;
        setEntityCards((prev) => prev.filter((item) => item.id !== card.id));
        if (editingCardId === card.id) resetCardDraft();
        updateWorkspace((prev) => ({
          ...prev,
          assetsConfirmed: false,
          entities: prev.entities.map((entity) =>
            entity.binding?.cardId === card.id ? { ...entity, confirmed: false, binding: null } : entity,
          ),
        }));
        notify(`实体卡已删除：${card.entity_name}，解除绑定 ${data.removed_bindings || 0} 个`, 'success');
      }),
    [askConfirm, editingCardId, isCurrentProject, notify, resetCardDraft, run, selectedProject, setEntityCards, updateWorkspace],
  );

  const deleteAsset = useCallback(
    (asset) =>
      run(`deleteAsset:${asset.path}`, async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        const confirmed = await askConfirm({
          title: '删除素材文件',
          body: '素材文件删除后，引用它的实体卡需要重新选择文件。',
          tone: 'danger',
          confirmLabel: '删除',
          items: [
            { label: '文件', value: asset.filename },
            { label: '路径', value: asset.path },
          ],
        });
        if (!confirmed) return;
        const data = await request(`/api/projects/${selectedProject.id}/assets/${encodeAssetPath(asset.path)}`, {
          method: 'DELETE',
        });
        await refreshAssets(projectId);
        await refreshEntityCards(projectId);
        await refreshEntityMaterials(projectId);
        if (!isCurrentProject(projectId)) return data;
        setCardDraft((prev) => ({
          ...prev,
          existingAssets: (prev.existingAssets || []).filter((path) => path !== asset.path),
        }));
        updateWorkspace({ assetsConfirmed: false });
        notify(`素材已删除：${asset.filename}，清理引用 ${data.removed_references || 0} 条`, 'success');
      }),
    [
      askConfirm,
      isCurrentProject,
      notify,
      refreshAssets,
      refreshEntityCards,
      refreshEntityMaterials,
      run,
      selectedProject,
      updateWorkspace,
    ],
  );

  const renameAsset = useCallback(
    (asset, filename) =>
      run(`renameAsset:${asset.path}`, async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        const nextFilename = (filename || '').trim();
        if (!nextFilename) throw new Error('素材名称不能为空');
        const renamed = await request(`/api/projects/${selectedProject.id}/assets/${encodeAssetPath(asset.path)}`, {
          method: 'PATCH',
          body: JSON.stringify({ filename: nextFilename }),
        });
        await refreshAssets(projectId);
        await refreshEntityCards(projectId);
        await refreshEntityMaterials(projectId);
        if (!isCurrentProject(projectId)) return renamed;
        setCardDraft((prev) => ({
          ...prev,
          existingAssets: (prev.existingAssets || []).map((path) => (path === renamed.old_path ? renamed.path : path)),
        }));
        updateWorkspace({ assetsConfirmed: false });
        notify(`素材已重命名：${renamed.filename}`, 'success');
        return renamed;
      }),
    [isCurrentProject, notify, refreshAssets, refreshEntityCards, refreshEntityMaterials, run, selectedProject, updateWorkspace],
  );

  const addEntityMaterials = useCallback(
    ({ entityName, type, assetPaths }) =>
      run(`addEntityMaterials:${entityName}:${type}`, async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        const paths = Array.from(new Set(assetPaths || []));
        if (paths.length === 0) return;
        const data = await request(`/api/projects/${selectedProject.id}/entity-materials`, {
          method: 'POST',
          body: JSON.stringify({
            entity_name: entityName,
            type,
            asset_paths: paths,
          }),
        });
        if (!isCurrentProject(projectId)) return data;
        setEntityMaterials(data.materials);
        updateWorkspace({ assetsConfirmed: false });
        notify(`已加入 ${paths.length} 个实体素材`, 'success');
      }),
    [isCurrentProject, notify, run, selectedProject, setEntityMaterials, updateWorkspace],
  );

  const uploadEntityMaterialFiles = useCallback(
    ({ entityName, type, files }) =>
      run(`uploadEntityMaterials:${entityName}:${type}`, async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        const incomingFiles = Array.from(files || []);
        if (incomingFiles.length === 0) return;
        const paths = await Promise.all(
          incomingFiles.map((file) => uploadAssetFile(projectId, inferAssetType(file), file)),
        );
        await refreshAssets(projectId);
        const data = await request(`/api/projects/${projectId}/entity-materials`, {
          method: 'POST',
          body: JSON.stringify({
            entity_name: entityName,
            type,
            asset_paths: paths,
          }),
        });
        if (!isCurrentProject(projectId)) return data;
        setEntityMaterials(data.materials);
        updateWorkspace({ assetsConfirmed: false });
        notify(`已上传并加入 ${incomingFiles.length} 个实体素材`, 'success');
      }),
    [isCurrentProject, notify, refreshAssets, run, selectedProject, setEntityMaterials, updateWorkspace],
  );

  const deleteEntityMaterial = useCallback(
    (material) =>
      run(`deleteEntityMaterial:${material.id}`, async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        const confirmed = await askConfirm({
          title: '移除实体素材',
          body: '该素材只会从当前实体的小素材库移除，不会删除项目素材文件。',
          tone: 'danger',
          confirmLabel: '移除',
          items: [
            { label: '实体', value: material.entity_name },
            { label: '素材', value: material.asset_path },
          ],
        });
        if (!confirmed) return;
        await request(`/api/projects/${selectedProject.id}/entity-materials/${material.id}`, {
          method: 'DELETE',
        });
        await refreshEntityMaterials(projectId);
        if (!isCurrentProject(projectId)) return;
        updateWorkspace({ assetsConfirmed: false });
        notify('实体素材已移除', 'success');
      }),
    [askConfirm, isCurrentProject, notify, refreshEntityMaterials, run, selectedProject, updateWorkspace],
  );

  const deleteEntityMaterialPool = useCallback(
    ({ entityName, type, materials = [] }) =>
      run(`deleteEntityMaterialPool:${entityName}:${type}`, async () => {
        if (!selectedProject) throw new Error('请先选择项目');
        const projectId = selectedProject.id;
        if (materials.length === 0) return;
        const confirmed = await askConfirm({
          title: '清空实体素材库',
          body: '将移除该主体下全部小素材库条目，不会删除项目素材文件，也不会删除已创建的状态卡片。',
          tone: 'danger',
          confirmLabel: '清空',
          items: [
            { label: '主体', value: entityName },
            { label: '类型', value: typeLabel(type) },
            { label: '素材数', value: `${materials.length} 个` },
          ],
        });
        if (!confirmed) return;
        await Promise.all(
          materials.map((material) =>
            request(`/api/projects/${projectId}/entity-materials/${material.id}`, {
              method: 'DELETE',
            }),
          ),
        );
        await refreshEntityMaterials(projectId);
        if (!isCurrentProject(projectId)) return;
        updateWorkspace({ assetsConfirmed: false });
        notify(`已清空 ${entityName} 的素材库`, 'success');
      }),
    [askConfirm, isCurrentProject, notify, refreshEntityMaterials, run, selectedProject, updateWorkspace],
  );

  return {
    cardDraft,
    setCardDraft,
    editingCardId,
    resetCardDraft,
    uploadProjectAssets,
    createEntityCard,
    editEntityCard,
    cancelEntityCardEdit,
    deleteEntityCard,
    deleteAsset,
    renameAsset,
    addEntityMaterials,
    uploadEntityMaterialFiles,
    deleteEntityMaterial,
    deleteEntityMaterialPool,
  };
}
