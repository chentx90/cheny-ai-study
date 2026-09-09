import React, { useEffect, useMemo, useState } from 'react';
import { Film, Loader2, SlidersHorizontal } from 'lucide-react';
import {
  defaultVideoRequestSettings,
  isXyqVideoProvider,
  videoAspectRatioOptions,
  videoDurationMaxSeconds,
  videoDurationMinSeconds,
  videoReferenceModeOptions,
  videoResolutionOptions,
  xyqVideoAspectRatioOptions,
  xyqVideoModelOptions,
  xyqVideoResolutionOptions,
} from '../../constants';
import { cardAssetPaths, entityCardsForAnchorText } from './videoViewUtils';

function clampDuration(value, fallback = defaultVideoRequestSettings.duration) {
  const parsed = Number(value ?? fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(videoDurationMaxSeconds, Math.max(videoDurationMinSeconds, Math.round(parsed)));
}

function resolveModelValue(model, availableModels = []) {
  const clean = String(model || '').trim();
  if (!clean) return availableModels[0] || '';
  if (availableModels.includes(clean)) return clean;
  return '__custom__';
}

function inferAssetType(path = '', assetType = '') {
  const typed = String(assetType || '').trim().toLowerCase();
  if (typed === 'image' || typed === 'video' || typed === 'audio') return typed;
  const lower = String(path || '').toLowerCase();
  if (lower.startsWith('assets/videos/') || /\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(lower)) return 'video';
  if (lower.startsWith('assets/audio/') || /\.(mp3|wav|m4a|aac|flac|ogg|opus)$/i.test(lower)) return 'audio';
  return 'image';
}

/** Collect reference paths from entity cards linked in the prompt card anchor text. */
export function collectEntityReferenceSelections(card, entityCards = [], assets = []) {
  const related = entityCardsForAnchorText(card?.anchor_text || '', entityCards);
  // 人物卡优先，场景/道具靠后，保证 @图1 更可能锁角色
  const ordered = [...related].sort((a, b) => {
    const rank = (item) => {
      const typ = String(item?.type || '').toLowerCase();
      if (typ.includes('character') || typ === '人物' || typ === '角色') return 0;
      if (typ.includes('prop') || typ === '物品') return 1;
      return 2;
    };
    return rank(a) - rank(b);
  });
  const assetByPath = new Map(assets.map((asset) => [asset.path, asset]));
  const referenceImages = [];
  const referenceVideos = [];
  const referenceAudios = [];
  const seen = new Set();

  ordered.forEach((entityCard) => {
    cardAssetPaths(entityCard).forEach((path) => {
      const clean = String(path || '').trim();
      if (!clean || seen.has(clean)) return;
      seen.add(clean);
      const asset = assetByPath.get(clean);
      const type = inferAssetType(clean, asset?.asset_type);
      if (type === 'video') referenceVideos.push(clean);
      else if (type === 'audio') referenceAudios.push(clean);
      else referenceImages.push(clean);
    });
  });

  return { referenceImages, referenceVideos, referenceAudios, entityCount: ordered.length };
}

function hasAnyReferences(settings) {
  return Boolean(
    (settings.referenceImages && settings.referenceImages.length) ||
      (settings.referenceVideos && settings.referenceVideos.length) ||
      (settings.referenceAudios && settings.referenceAudios.length) ||
      settings.firstFrame ||
      settings.lastFrame,
  );
}

function normalizeSettings(settings = {}, fallbackDuration = 5, availableModels = [], autoRefs = null, isXyq = false) {
  const duration = clampDuration(settings.duration, fallbackDuration);
  const model = String(settings.model || '').trim();
  const xyqDefaultModel = 'Seedance_2.0_mini_lite';
  let referenceImages = Array.isArray(settings.referenceImages)
    ? settings.referenceImages
    : Array.isArray(settings.reference_images)
      ? settings.reference_images
      : [];
  let referenceVideos = Array.isArray(settings.referenceVideos)
    ? settings.referenceVideos
    : Array.isArray(settings.reference_videos)
      ? settings.reference_videos
      : [];
  let referenceAudios = Array.isArray(settings.referenceAudios)
    ? settings.referenceAudios
    : Array.isArray(settings.reference_audios)
      ? settings.reference_audios
      : [];
  const firstFrame = String(settings.firstFrame || settings.first_frame || '');
  const lastFrame = String(settings.lastFrame || settings.last_frame || '');
  let referenceMode = String(
    settings.referenceMode || settings.reference_mode || defaultVideoRequestSettings.referenceMode,
  );
  const resolvedModel = resolveModelValue(
    model || (isXyq ? xyqDefaultModel : ''),
    isXyq ? xyqVideoModelOptions.map((item) => item.value).filter(Boolean) : availableModels,
  );

  const draft = {
    referenceImages: referenceImages.map(String).filter(Boolean),
    referenceVideos: referenceVideos.map(String).filter(Boolean),
    referenceAudios: referenceAudios.map(String).filter(Boolean),
    firstFrame,
    lastFrame,
  };

  // 有关联实体素材时优先自动引用，并默认 Omni 多模态
  const hasAutoRefs = Boolean(
    autoRefs &&
      (autoRefs.referenceImages?.length || autoRefs.referenceVideos?.length || autoRefs.referenceAudios?.length),
  );
  if (hasAutoRefs) {
    draft.referenceImages = [...(autoRefs.referenceImages || [])];
    draft.referenceVideos = [...(autoRefs.referenceVideos || [])];
    draft.referenceAudios = [...(autoRefs.referenceAudios || [])];
    referenceMode = 'omni';
  } else if (!hasAnyReferences(draft) && (referenceMode === 'none' || !referenceMode)) {
    referenceMode = defaultVideoRequestSettings.referenceMode;
  }

  // 小云雀仅支持纯提示词 / Omni 多模态参考，避免网关首尾帧模式干扰
  if (isXyq && (referenceMode === 'first_last' || referenceMode === 'multi')) {
    referenceMode = hasAutoRefs || hasAnyReferences(draft) ? 'omni' : 'none';
  }

  return {
    model: resolvedModel,
    customModel: resolvedModel === '__custom__' ? model : String(settings.customModel || ''),
    aspectRatio: String(settings.aspectRatio || settings.aspect_ratio || defaultVideoRequestSettings.aspectRatio),
    duration,
    resolution: String(settings.resolution || defaultVideoRequestSettings.resolution),
    referenceMode: referenceMode || defaultVideoRequestSettings.referenceMode,
    generateAudio:
      settings.generateAudio === undefined && settings.generate_audio === undefined
        ? Boolean(defaultVideoRequestSettings.generateAudio)
        : Boolean(settings.generateAudio ?? settings.generate_audio),
    firstFrame: draft.firstFrame,
    lastFrame: draft.lastFrame,
    referenceImages: draft.referenceImages,
    referenceVideos: draft.referenceVideos,
    referenceAudios: draft.referenceAudios,
  };
}

function resolveModel(form) {
  return form.model === '__custom__' ? String(form.customModel || '').trim() : String(form.model || '').trim();
}

function toggleListValue(list, value) {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

export default function VideoRequestDialog({
  dialog,
  savedSettings,
  assets = [],
  entityCards = [],
  videoProvider = '',
  loadVideoModels,
  onCancel,
  onSubmit,
}) {
  const isRetry = dialog?.mode === 'retry';
  const isXyq = isXyqVideoProvider(videoProvider);
  const card = dialog?.card || {};
  const task = dialog?.task || null;
  const fallbackDuration =
    Number(task?.duration || task?.assets?.settings?.duration || card.duration || defaultVideoRequestSettings.duration) ||
    defaultVideoRequestSettings.duration;
  const [promptText, setPromptText] = useState(() => String(task?.prompt || card.prompt_text || ''));
  const [availableModels, setAvailableModels] = useState(() =>
    isXyq
      ? xyqVideoModelOptions.map((item) => item.value).filter((value) => value && value !== '__custom__')
      : [],
  );
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState('');

  const autoRefs = useMemo(() => {
    if (isRetry) return null;
    return collectEntityReferenceSelections(dialog?.card, entityCards, assets);
  }, [isRetry, dialog?.card, entityCards, assets]);

  const [form, setForm] = useState(() =>
    normalizeSettings(savedSettings, fallbackDuration, availableModels, autoRefs, isXyq),
  );

  useEffect(() => {
    if (!dialog) return;
    setPromptText(String(task?.prompt || card.prompt_text || ''));
  }, [dialog?.mode, dialog?.task?.id, dialog?.card?.id, task?.prompt, card.prompt_text]);

  useEffect(() => {
    const dialogKey = isRetry ? dialog?.task?.id : dialog?.card?.id;
    if (!dialogKey || !loadVideoModels) return undefined;

    setForm(normalizeSettings(savedSettings, fallbackDuration, availableModels, autoRefs, isXyq));
    if (isXyq) {
      const models = xyqVideoModelOptions
        .map((item) => item.value)
        .filter((value) => value && value !== '__custom__');
      setAvailableModels(models);
      setModelsLoading(false);
      setModelsError('');
      setForm((prev) => {
        const next = normalizeSettings(savedSettings, fallbackDuration, models, autoRefs, isXyq);
        return { ...next, duration: prev.duration || next.duration };
      });
      return undefined;
    }

    let cancelled = false;
    setModelsLoading(true);
    setModelsError('');
    loadVideoModels({ provider: videoProvider })
      .then((models) => {
        if (cancelled) return;
        const list = Array.isArray(models) ? models.filter(Boolean) : [];
        setAvailableModels(list);
        setForm((prev) => {
          const next = normalizeSettings(savedSettings, fallbackDuration, list, autoRefs, isXyq);
          return { ...next, duration: prev.duration || next.duration };
        });
      })
      .catch((error) => {
        if (cancelled) return;
        setAvailableModels([]);
        setModelsError(error.message || '无法获取模型列表');
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // 仅在打开弹窗/切换卡片或任务时拉取模型，避免父组件轮询导致反复刷新。
  }, [
    dialog?.mode,
    dialog?.task?.id,
    dialog?.card?.id,
    videoProvider,
    savedSettings,
    fallbackDuration,
    isRetry,
    autoRefs?.referenceImages?.join('|'),
    autoRefs?.referenceVideos?.join('|'),
    autoRefs?.referenceAudios?.join('|'),
  ]);

  const modelOptions = useMemo(() => {
    if (isXyq) {
      return xyqVideoModelOptions;
    }
    const fromApi = availableModels.map((modelId) => ({ value: modelId, label: modelId }));
    return [...fromApi, { value: '__custom__', label: '手动输入模型 ID' }];
  }, [availableModels, isXyq]);

  const entityPathSet = useMemo(() => {
    const paths = new Set([
      ...(autoRefs?.referenceImages || []),
      ...(autoRefs?.referenceVideos || []),
      ...(autoRefs?.referenceAudios || []),
    ]);
    if (isRetry) {
      form.referenceImages.forEach((path) => paths.add(path));
      form.referenceVideos.forEach((path) => paths.add(path));
      form.referenceAudios.forEach((path) => paths.add(path));
    }
    return paths;
  }, [autoRefs, isRetry, form.referenceImages, form.referenceVideos, form.referenceAudios]);

  const imageAssets = useMemo(() => {
    const images = assets.filter((asset) => asset.asset_type === 'image');
    return [...images].sort((a, b) => Number(entityPathSet.has(b.path)) - Number(entityPathSet.has(a.path)));
  }, [assets, entityPathSet]);
  const videoAssets = useMemo(() => {
    const videos = assets.filter((asset) => asset.asset_type === 'video');
    return [...videos].sort((a, b) => Number(entityPathSet.has(b.path)) - Number(entityPathSet.has(a.path)));
  }, [assets, entityPathSet]);
  const audioAssets = useMemo(() => {
    const audios = assets.filter((asset) => asset.asset_type === 'audio');
    return [...audios].sort((a, b) => Number(entityPathSet.has(b.path)) - Number(entityPathSet.has(a.path)));
  }, [assets, entityPathSet]);

  const payload = useMemo(
    () => ({
      model: resolveModel(form),
      aspectRatio: form.aspectRatio,
      duration: Number(form.duration || fallbackDuration || defaultVideoRequestSettings.duration),
      resolution: form.resolution,
      referenceMode: form.referenceMode,
      generateAudio: form.generateAudio !== false,
      firstFrame: form.firstFrame,
      lastFrame: form.lastFrame,
      referenceImages: form.referenceImages,
      referenceVideos: form.referenceVideos,
      referenceAudios: form.referenceAudios,
    }),
    [form, fallbackDuration],
  );

  if (!dialog) return null;

  const mode = form.referenceMode;
  const xyqReferenceModes = videoReferenceModeOptions.filter((item) => item.value === 'none' || item.value === 'omni');
  const referenceModeOptions = isXyq ? xyqReferenceModes : videoReferenceModeOptions;
  const aspectRatioOptions = isXyq ? xyqVideoAspectRatioOptions : videoAspectRatioOptions;
  const resolutionOptions = isXyq ? xyqVideoResolutionOptions : videoResolutionOptions;
  const modeValid =
    mode === 'none' ||
    (mode === 'first_last' && Boolean(form.firstFrame || form.lastFrame)) ||
    (mode === 'multi' && form.referenceImages.length > 0) ||
    (mode === 'omni' &&
      (form.referenceImages.length > 0 || form.referenceVideos.length > 0 || form.referenceAudios.length > 0));
  const modelReady = Boolean(resolveModel(form));
  const promptReady = !isRetry || Boolean(promptText.trim());
  const canSubmit = !dialog.busy && !modelsLoading && modelReady && modeValid && promptReady;
  const autoRefCount =
    (autoRefs?.referenceImages?.length || 0) +
    (autoRefs?.referenceVideos?.length || 0) +
    (autoRefs?.referenceAudios?.length || 0);

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="video-request-dialog" role="dialog" aria-modal="true" aria-labelledby="video-request-title">
        <header>
          <span className="dialog-icon">
            <Film />
          </span>
          <div>
            <h3 id="video-request-title">{isRetry ? '重试视频生成' : isXyq ? '小云雀生成视频' : '网关生成视频'}</h3>
            <p>
              {isRetry
                ? '可修改提示词、模型与参考素材后重新提交，会创建新版本任务。'
                : isXyq
                  ? '使用 pippit-tool-cli 提交，需填写模型 / 比例 / 时长 / 分辨率（与网关参数相互独立）。'
                  : '从 OpenAI 兼容网关拉取模型并选择参数，确认后创建任务。'}
            </p>
          </div>
        </header>

        <div className="video-request-summary">
          <div>
            <span>通道</span>
            <strong>{isXyq ? '小云雀 CLI' : 'OpenAI 兼容网关'}</strong>
          </div>
          <div>
            <span>{isRetry ? '任务' : '卡片'}</span>
            <strong>
              {isRetry
                ? `${task?.is_preview ? '预览' : '完整'} / v${task?.version || '?'}`
                : card.title || card.id || '当前提示词卡片'}
            </strong>
          </div>
          <div>
            <span>{isRetry ? '原任务时长' : '提示词时长'}</span>
            <strong>{Math.round(Number(fallbackDuration || 0)) || defaultVideoRequestSettings.duration} 秒</strong>
          </div>
        </div>

        {isRetry && (
          <div className="video-request-prompt">
            <label>
              <span>提示词</span>
              <textarea
                rows={8}
                value={promptText}
                placeholder="编辑本次视频请求的提示词正文"
                onChange={(event) => setPromptText(event.target.value)}
              />
            </label>
          </div>
        )}

        <div className="video-request-form">
          <label>
            <span>模型</span>
            <select
              value={form.model}
              disabled={modelsLoading || modelOptions.length === 0}
              onChange={(event) => setForm((prev) => ({ ...prev, model: event.target.value }))}
            >
              {modelsLoading && <option value="">加载模型列表…</option>}
              {!modelsLoading && modelOptions.length === 0 && <option value="">请先在设置中配置视频服务</option>}
              {!modelsLoading &&
                modelOptions.map((option) => (
                  <option value={option.value} key={option.value || 'default'}>
                    {option.label}
                  </option>
                ))}
            </select>
          </label>
          {modelsError && <small className="video-request-models-error">{modelsError}，可改用手动输入。</small>}
          {form.model === '__custom__' && (
            <label>
              <span>自定义模型 ID</span>
              <input
                value={form.customModel}
                placeholder={isXyq ? '例如 Seedance_2.0_mini_lite' : '例如 kling-v2.1 / veo3-fast'}
                onChange={(event) => setForm((prev) => ({ ...prev, customModel: event.target.value }))}
              />
            </label>
          )}
          <label>
            <span>{isXyq ? '比例（ratio）' : '比例'}</span>
            <select
              value={form.aspectRatio}
              onChange={(event) => setForm((prev) => ({ ...prev, aspectRatio: event.target.value }))}
            >
              {aspectRatioOptions.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{isXyq ? '时长 duration_sec（秒）' : '时长（秒）'}</span>
            <input
              type="number"
              min={videoDurationMinSeconds}
              max={videoDurationMaxSeconds}
              step={1}
              value={form.duration}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  duration: clampDuration(event.target.value, prev.duration),
                }))
              }
            />
          </label>
          <label>
            <span>分辨率</span>
            <select value={form.resolution} onChange={(event) => setForm((prev) => ({ ...prev, resolution: event.target.value }))}>
              {resolutionOptions.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>参考模式</span>
            <select
              value={form.referenceMode}
              onChange={(event) => setForm((prev) => ({ ...prev, referenceMode: event.target.value }))}
            >
              {referenceModeOptions.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox-row video-request-audio-toggle">
            <input
              type="checkbox"
              checked={form.generateAudio !== false}
              onChange={(event) => setForm((prev) => ({ ...prev, generateAudio: event.target.checked }))}
            />
            {isXyq ? '生成有声视频' : '生成有声视频（generate_audio）'}
          </label>
        </div>

        {mode === 'first_last' && (
          <div className="video-request-refs">
            <label>
              <span>首帧</span>
              <select value={form.firstFrame} onChange={(event) => setForm((prev) => ({ ...prev, firstFrame: event.target.value }))}>
                <option value="">未选择</option>
                {imageAssets.map((asset) => (
                  <option value={asset.path} key={`first-${asset.path}`}>
                    {asset.filename}
                    {entityPathSet.has(asset.path) ? ' · 实体' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>尾帧</span>
              <select value={form.lastFrame} onChange={(event) => setForm((prev) => ({ ...prev, lastFrame: event.target.value }))}>
                <option value="">未选择</option>
                {imageAssets.map((asset) => (
                  <option value={asset.path} key={`last-${asset.path}`}>
                    {asset.filename}
                    {entityPathSet.has(asset.path) ? ' · 实体' : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {mode === 'multi' && (
          <div className="video-request-ref-list">
            <span>多图参考</span>
            {autoRefCount > 0 && (
              <small className="video-request-auto-ref-hint">
                已根据 {autoRefs.entityCount} 个引用实体预选 {autoRefCount} 个素材，可继续勾选或取消
              </small>
            )}
            {imageAssets.length === 0 && <small>暂无图片素材，请先到资源管理上传</small>}
            {imageAssets.map((asset) => (
              <label key={asset.path} className="checkbox-row">
                <input
                  type="checkbox"
                  checked={form.referenceImages.includes(asset.path)}
                  onChange={() =>
                    setForm((prev) => ({
                      ...prev,
                      referenceImages: toggleListValue(prev.referenceImages, asset.path),
                    }))
                  }
                />
                {asset.filename}
                {entityPathSet.has(asset.path) ? ' · 实体' : ''}
              </label>
            ))}
          </div>
        )}

        {mode === 'omni' && (
          <div className="video-request-ref-list">
            <span>Omni 参考（图 / 视频 / 音频）</span>
            {autoRefCount > 0 && (
              <small className="video-request-auto-ref-hint">
                已根据 {autoRefs.entityCount} 个引用实体预选 {autoRefCount} 个素材，可继续勾选或取消
              </small>
            )}
            {autoRefCount === 0 && (
              <small className="video-request-auto-ref-hint">当前卡片暂无关联实体素材，请手动勾选或先解析 @ 主体</small>
            )}
            {[...imageAssets, ...videoAssets, ...audioAssets].map((asset) => {
              const key =
                asset.asset_type === 'video'
                  ? 'referenceVideos'
                  : asset.asset_type === 'audio'
                    ? 'referenceAudios'
                    : 'referenceImages';
              return (
                <label key={asset.path} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={form[key].includes(asset.path)}
                    onChange={() =>
                      setForm((prev) => ({
                        ...prev,
                        [key]: toggleListValue(prev[key], asset.path),
                      }))
                    }
                  />
                  [{asset.asset_type}] {asset.filename}
                  {entityPathSet.has(asset.path) ? ' · 实体' : ''}
                </label>
              );
            })}
          </div>
        )}

        <div className="video-request-preview">
          {modelsLoading ? <Loader2 className="spin" /> : <SlidersHorizontal />}
          <span>
            {payload.model || '未选择模型'} / {payload.aspectRatio} / {payload.duration} 秒 / {payload.resolution} /{' '}
            {payload.referenceMode}
            {payload.generateAudio ? ' / 有声' : ' / 无声'}
          </span>
        </div>

        <footer>
          <button type="button" className="secondary" onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => onSubmit(isRetry ? { ...payload, prompt: promptText.trim() } : payload)}
          >
            {isRetry ? '重试生成' : '生成视频请求'}
          </button>
        </footer>
      </section>
    </div>
  );
}
