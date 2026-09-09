import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, Palette, PlugZap, RefreshCw, Save, Server, Settings, ListTree } from 'lucide-react';
import Empty from '../components/Empty';
import PanelTitle from '../components/PanelTitle';
import SegmentedControl from '../components/SegmentedControl';
import { llmUseCases } from '../constants';
import { readStorageJson, removeStorageItem, writeStorageJson } from '../app/uiStorage';
import { statusLabel } from '../utils';
import {
  BORDER_RADIUS_OPTIONS,
  FONT_SCALE_OPTIONS,
  THEME_MODE_OPTIONS,
  baseContentFontSize,
} from '../themeUtils';

const SETTINGS_DRAFT_KEY = 'ai-video-manager:settings-draft:v1';
const SETTINGS_FIELDS = [
  'llmProvider',
  'llmBaseUrl',
  'llmDefaultModel',
  'videoProvider',
  'videoBaseUrl',
  'videoAllowInsecureSsl',
  'xyqCliPath',
  'xyqOpenApiBase',
  'imageProvider',
  'imageUseLlmCredentials',
  'imageBaseUrl',
  'imageModel',
  'imageOutputSize',
];
const USE_CASE_FIELDS = [
  'model', 'temperature', 'maxTokens', 'timeoutSeconds',
  'contextWindowTokens', 'reservedOutputTokens', 'compressionThreshold',
  'compressionTarget', 'recentMessagesToKeep',
];
const EMPTY_SECRET_DRAFT = {
  llmApiKey: '',
  videoApiKey: '',
  imageApiKey: '',
  clearLlmApiKey: false,
  clearVideoApiKey: false,
  clearImageApiKey: false,
};

function defaultUseCaseConfig(useCaseId) {
  const isSplitUseCase = useCaseId === 'prompt_split';
  const isWriteUseCase = useCaseId === 'video_generate' || useCaseId === 'prompt_rerun';
  const result = {
    model: '',
    temperature: isWriteUseCase ? 0.6 : isSplitUseCase ? 0.3 : useCaseId === 'subject_match' ? 0.1 : 0.2,
    maxTokens: 100000,
    timeoutSeconds: isSplitUseCase || isWriteUseCase ? 180 : 120,
  };
  if (useCaseId === 'workflow_agent') {
    Object.assign(result, {
      contextWindowTokens: 128000,
      reservedOutputTokens: 12000,
      compressionThreshold: 0.8,
      compressionTarget: 0.2,
      recentMessagesToKeep: 8,
    });
  }
  return result;
}

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object || {}, key);
}

function sanitizeDraft(draft) {
  const clean = {};
  SETTINGS_FIELDS.forEach((field) => {
    if (hasOwn(draft, field)) clean[field] = draft[field];
  });
  const incomingUseCases = draft?.llmUseCases && typeof draft.llmUseCases === 'object' ? draft.llmUseCases : {};
  const cleanUseCases = {};
  llmUseCases.forEach((useCase) => {
    const source = incomingUseCases[useCase.id];
    if (!source || typeof source !== 'object') return;
    const next = {};
    USE_CASE_FIELDS.forEach((field) => {
      if (hasOwn(source, field)) next[field] = source[field];
    });
    if (Object.keys(next).length) cleanUseCases[useCase.id] = next;
  });
  if (Object.keys(cleanUseCases).length) clean.llmUseCases = cleanUseCases;
  return clean;
}

function readSettingsDraft() {
  return sanitizeDraft(readStorageJson(SETTINGS_DRAFT_KEY, {}));
}

function persistSettingsDraft(draft) {
  const clean = sanitizeDraft(draft);
  if (!Object.keys(clean).length) {
    removeStorageItem(SETTINGS_DRAFT_KEY);
    return;
  }
  writeStorageJson(SETTINGS_DRAFT_KEY, clean);
}

function valueFrom(draft, apiConfig, field, fallback = '') {
  if (hasOwn(draft, field)) return draft[field];
  return apiConfig?.[field] ?? fallback;
}

function buildFormConfig(apiConfig = {}, draft = {}) {
  const savedUseCases = apiConfig.llmUseCases && typeof apiConfig.llmUseCases === 'object' ? apiConfig.llmUseCases : {};
  const draftUseCases = draft.llmUseCases && typeof draft.llmUseCases === 'object' ? draft.llmUseCases : {};
  return {
    llmProvider: valueFrom(draft, apiConfig, 'llmProvider', 'newapi'),
    llmBaseUrl: valueFrom(draft, apiConfig, 'llmBaseUrl', ''),
    llmDefaultModel: valueFrom(draft, apiConfig, 'llmDefaultModel', ''),
    llmUseCases: Object.fromEntries(
      llmUseCases.map((useCase) => {
        const defaults = defaultUseCaseConfig(useCase.id);
        const saved = savedUseCases[useCase.id] || {};
        const patched = draftUseCases[useCase.id] || {};
        const resolved = {
            model: hasOwn(patched, 'model') ? patched.model : saved.model ?? defaults.model,
            temperature: hasOwn(patched, 'temperature') ? patched.temperature : saved.temperature ?? defaults.temperature,
            maxTokens: hasOwn(patched, 'maxTokens') ? patched.maxTokens : saved.maxTokens ?? defaults.maxTokens,
            timeoutSeconds: hasOwn(patched, 'timeoutSeconds')
              ? patched.timeoutSeconds
              : saved.timeoutSeconds ?? defaults.timeoutSeconds,
        };
        if (useCase.id === 'workflow_agent') {
          ['contextWindowTokens', 'reservedOutputTokens', 'compressionThreshold', 'compressionTarget', 'recentMessagesToKeep']
            .forEach((field) => {
              resolved[field] = hasOwn(patched, field) ? patched[field] : saved[field] ?? defaults[field];
            });
        }
        return [useCase.id, resolved];
      }),
    ),
    videoProvider: valueFrom(draft, apiConfig, 'videoProvider', 'newapi'),
    videoBaseUrl: valueFrom(draft, apiConfig, 'videoBaseUrl', ''),
    videoAllowInsecureSsl: valueFrom(draft, apiConfig, 'videoAllowInsecureSsl', false),
    xyqCliPath: valueFrom(draft, apiConfig, 'xyqCliPath', ''),
    xyqOpenApiBase: valueFrom(draft, apiConfig, 'xyqOpenApiBase', 'https://xyq.jianying.com'),
    imageProvider: valueFrom(draft, apiConfig, 'imageProvider', 'openai'),
    imageUseLlmCredentials: valueFrom(draft, apiConfig, 'imageUseLlmCredentials', true),
    imageBaseUrl: valueFrom(draft, apiConfig, 'imageBaseUrl', ''),
    imageModel: valueFrom(draft, apiConfig, 'imageModel', ''),
    imageOutputSize: valueFrom(draft, apiConfig, 'imageOutputSize', '1024x1024'),
    imageProtocol: valueFrom(draft, apiConfig, 'imageProtocol', 'openai'),
  };
}

export default function SettingsView({
  apiConfig,
  precheck,
  saveApiConfig,
  testLlmConnection,
  testVideoConnection,
  testImageConnection,
  fetchVideoModels,
  runPrecheck,
  busy,
  settingsSaveVersion,
  appearance,
  setAppearance,
}) {
  const [draft, setDraft] = useState(readSettingsDraft);
  const [secretDraft, setSecretDraft] = useState(EMPTY_SECRET_DRAFT);
  const [videoModelsPreview, setVideoModelsPreview] = useState([]);
  const config = useMemo(() => buildFormConfig(apiConfig, draft), [apiConfig, draft]);

  useEffect(() => {
    persistSettingsDraft(draft);
  }, [draft]);

  useEffect(() => {
    if (!settingsSaveVersion) return;
    setDraft({});
    setSecretDraft(EMPTY_SECRET_DRAFT);
    removeStorageItem(SETTINGS_DRAFT_KEY);
  }, [settingsSaveVersion]);

  function updateDraftField(field, value) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  function updateUseCaseField(useCaseId, field, value) {
    setDraft((prev) => ({
      ...prev,
      llmUseCases: {
        ...(prev.llmUseCases || {}),
        [useCaseId]: {
          ...(prev.llmUseCases?.[useCaseId] || {}),
          [field]: value,
        },
      },
    }));
  }

  function updateSecretField(field, value) {
    setSecretDraft((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <div className="work-grid settings-grid">
      <div className="settings-primary-column">
        <section className="panel settings-main-panel">
          <PanelTitle icon={Palette} title="基础主题设置" />
          <div className="settings-form settings-appearance-form">
            <div className="settings-section">
              <h4>明暗主题</h4>
              <p className="settings-hint">选择浅色、深色，或跟随系统黑白模式自动切换。</p>
              <SegmentedControl
                ariaLabel="明暗主题"
                options={THEME_MODE_OPTIONS}
                value={appearance.themeMode}
                onChange={(value) => setAppearance({ themeMode: value })}
              />
            </div>

            <div className="settings-section">
              <h4>字体方案</h4>
              <p className="settings-hint">
                统一全站基础字号，当前内容基准为 {baseContentFontSize(appearance.fontScale)}px（视频页分镜/剧本可在此基础上微调）。
              </p>
              <SegmentedControl
                ariaLabel="字体方案"
                options={FONT_SCALE_OPTIONS}
                value={appearance.fontScale}
                onChange={(value) => setAppearance({ fontScale: value })}
              />
            </div>

            <div className="settings-section">
              <h4>圆角大小</h4>
              <p className="settings-hint">调整按钮、输入框、卡片等界面元素的圆角风格。</p>
              <SegmentedControl
                ariaLabel="圆角大小"
                options={BORDER_RADIUS_OPTIONS}
                value={appearance.borderRadius}
                onChange={(value) => setAppearance({ borderRadius: value })}
              />
            </div>
          </div>
        </section>

        <section className="panel settings-main-panel">
          <PanelTitle icon={Settings} title="我的 API 配置" />
          <p className="settings-hint">LLM、视频网关与小云雀 Key 保存在本地配置中。</p>
          <form className="settings-form" onSubmit={saveApiConfig}>
          <div className="settings-section">
            <h4>LLM 服务</h4>
            <div className="settings-row">
              <label>
                服务商
                <input
                  name="llmProvider"
                  value={config.llmProvider}
                  onChange={(event) => updateDraftField('llmProvider', event.target.value)}
                />
              </label>
              <label>
                默认模型
                <input
                  name="llmDefaultModel"
                  value={config.llmDefaultModel}
                  placeholder="可选，使用点未填时兜底"
                  onChange={(event) => updateDraftField('llmDefaultModel', event.target.value)}
                />
              </label>
            </div>
            <label>
              Base URL
              <input
                name="llmBaseUrl"
                value={config.llmBaseUrl}
                placeholder="https://api.example.com/v1"
                onChange={(event) => updateDraftField('llmBaseUrl', event.target.value)}
              />
            </label>
            <label>
              API Key
              <input
                name="llmApiKey"
                type="password"
                value={secretDraft.llmApiKey}
                placeholder={apiConfig.llmApiKeySet ? `已配置 (${apiConfig.llmApiKey})，留空不修改` : '未配置'}
                autoComplete="off"
                disabled={secretDraft.clearLlmApiKey}
                onChange={(event) => updateSecretField('llmApiKey', event.target.value)}
              />
            </label>
            <label className="checkbox-row">
              <input
                name="clearLlmApiKey"
                type="checkbox"
                checked={secretDraft.clearLlmApiKey}
                onChange={(event) => updateSecretField('clearLlmApiKey', event.target.checked)}
              />
              清除已保存的 LLM API Key
            </label>
          </div>

          <div className="settings-section">
            <h4>LLM 使用点</h4>
            <div className="llm-use-case-list">
              {llmUseCases.map((useCase) => {
                const useCaseConfig = config.llmUseCases[useCase.id] || defaultUseCaseConfig(useCase.id);
                const busyKey = `testLlm:${useCase.id}`;
                return (
                  <div className="llm-use-case-row" key={useCase.id}>
                    <strong>{useCase.label}</strong>
                    <label>
                      模型
                      <input
                        name={`llmUseCases.${useCase.id}.model`}
                        value={useCaseConfig.model}
                        placeholder={config.llmDefaultModel ? `默认：${config.llmDefaultModel}` : '模型名'}
                        onChange={(event) => updateUseCaseField(useCase.id, 'model', event.target.value)}
                      />
                    </label>
                    <label>
                      温度
                      <input
                        name={`llmUseCases.${useCase.id}.temperature`}
                        type="number"
                        min="0"
                        max="2"
                        step="0.1"
                        value={useCaseConfig.temperature}
                        onChange={(event) => updateUseCaseField(useCase.id, 'temperature', event.target.value)}
                      />
                    </label>
                    <label>
                      Max Tokens
                      <input
                        name={`llmUseCases.${useCase.id}.maxTokens`}
                        type="number"
                        min="1"
                        step="1"
                        value={useCaseConfig.maxTokens}
                        onChange={(event) => updateUseCaseField(useCase.id, 'maxTokens', event.target.value)}
                      />
                    </label>
                    <label>
                      超时秒
                      <input
                        name={`llmUseCases.${useCase.id}.timeoutSeconds`}
                        type="number"
                        min="5"
                        max="600"
                        step="5"
                        value={useCaseConfig.timeoutSeconds}
                        onChange={(event) => updateUseCaseField(useCase.id, 'timeoutSeconds', event.target.value)}
                      />
                    </label>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy.has(busyKey)}
                      onClick={(event) => testLlmConnection(useCase.id, event.currentTarget.form)}
                    >
                      {busy.has(busyKey) ? <Loader2 className="spin" /> : <PlugZap />}
                      测试
                    </button>
                    {useCase.id === 'workflow_agent' && (
                      <div className="workflow-context-settings">
                        <label>
                          上下文窗口
                          <input name="llmUseCases.workflow_agent.contextWindowTokens" type="number" min="16000" step="1000" value={useCaseConfig.contextWindowTokens} onChange={(event) => updateUseCaseField(useCase.id, 'contextWindowTokens', event.target.value)} />
                        </label>
                        <label>
                          输出预留
                          <input name="llmUseCases.workflow_agent.reservedOutputTokens" type="number" min="1000" step="1000" value={useCaseConfig.reservedOutputTokens} onChange={(event) => updateUseCaseField(useCase.id, 'reservedOutputTokens', event.target.value)} />
                        </label>
                        <label>
                          压缩阈值
                          <input name="llmUseCases.workflow_agent.compressionThreshold" type="number" min="0.5" max="0.98" step="0.05" value={useCaseConfig.compressionThreshold} onChange={(event) => updateUseCaseField(useCase.id, 'compressionThreshold', event.target.value)} />
                        </label>
                        <label>
                          压缩目标
                          <input name="llmUseCases.workflow_agent.compressionTarget" type="number" min="0.05" max="0.5" step="0.05" value={useCaseConfig.compressionTarget} onChange={(event) => updateUseCaseField(useCase.id, 'compressionTarget', event.target.value)} />
                        </label>
                        <label>
                          保留消息
                          <input name="llmUseCases.workflow_agent.recentMessagesToKeep" type="number" min="2" max="30" step="1" value={useCaseConfig.recentMessagesToKeep} onChange={(event) => updateUseCaseField(useCase.id, 'recentMessagesToKeep', event.target.value)} />
                        </label>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="settings-section">
            <h4>视频服务</h4>
            {config.videoProvider === 'xyq' ? (
              <p className="settings-hint">
                使用字节小云雀官方 CLI（<code>pippit-tool-cli</code>）生成视频。请先在终端安装：
                {' '}
                <code>npx @pippit-dev/cli@latest install</code>
                ，再在小云雀首页「CLI/API」创建 Access Key 并填入下方。
                {apiConfig.videoRuntimeMode === 'real'
                  ? ` 当前运行时：${apiConfig.videoRuntimeProvider || 'xyq'}（已接入）`
                  : ' 当前尚未完成配置，视频生成不可用。'}
              </p>
            ) : (
              <p className="settings-hint">
                星链云 / vjimeng：Base URL 填 <code>https://www.vjimeng.vip/v1</code>（或站点根地址），API Key 在控制台「令牌」页创建。
                视频提交走官方 demo 协议 <code>POST /v1/video/submit/generate</code>，查询 <code>GET /v1/video/fetch/&#123;taskId&#125;</code>；
                参考素材经独立 OSS 直传 <code>https://oss.vjimeng.vip</code>（sign → PUT → complete），再用顶层 <code>images</code>/<code>audios</code>/<code>videos</code> 提交。
                不要使用已废弃的 <code>/v1/videos</code> 或 <code>/v1/files</code>。
                {' '}
                <a href="https://www.vjimeng.vip/docs" target="_blank" rel="noreferrer">
                  星链云接入文档
                </a>
                {apiConfig.videoRuntimeMode === 'real'
                  ? ` 当前运行时：${apiConfig.videoRuntimeProvider || config.videoProvider || '已配置'}（已接入）`
                  : ' 当前尚未完成配置，视频生成不可用。'}
              </p>
            )}
            <div className="settings-row">
              <label>
                视频通道
                <select
                  name="videoProvider"
                  value={config.videoProvider || 'newapi'}
                  onChange={(event) => updateDraftField('videoProvider', event.target.value)}
                >
                  <option value="newapi">OpenAI 兼容网关（星链云 / vjimeng）</option>
                  <option value="xyq">小云雀 CLI</option>
                </select>
              </label>
              {config.videoProvider !== 'xyq' && (
                <label>
                  Base URL
                  <input
                    name="videoBaseUrl"
                    value={config.videoBaseUrl}
                    onChange={(event) => updateDraftField('videoBaseUrl', event.target.value)}
                    placeholder="https://www.vjimeng.vip/v1"
                  />
                  <p className="settings-hint">星链云参考图走独立 OSS 直传（自动用 https://oss.vjimeng.vip），不是 /v1/files</p>
                </label>
              )}
            </div>
            {config.videoProvider === 'xyq' && (
              <div className="settings-row">
                <label>
                  CLI 路径（可选）
                  <input
                    name="xyqCliPath"
                    value={config.xyqCliPath}
                    onChange={(event) => updateDraftField('xyqCliPath', event.target.value)}
                    placeholder="留空则使用 PATH 中的 pippit-tool-cli"
                  />
                </label>
                <label>
                  OpenAPI 地址
                  <input
                    name="xyqOpenApiBase"
                    value={config.xyqOpenApiBase}
                    onChange={(event) => updateDraftField('xyqOpenApiBase', event.target.value)}
                    placeholder="https://xyq.jianying.com"
                  />
                </label>
              </div>
            )}
            <label>
              {config.videoProvider === 'xyq' ? 'Access Key' : 'API Key'}
              <input
                name="videoApiKey"
                type="password"
                value={secretDraft.videoApiKey}
                placeholder={
                  apiConfig.videoApiKeySet
                    ? `已配置 (${apiConfig.videoApiKey})，留空不修改`
                    : config.videoProvider === 'xyq'
                      ? '小云雀 Access Key'
                      : '未配置'
                }
                autoComplete="off"
                disabled={secretDraft.clearVideoApiKey}
                onChange={(event) => updateSecretField('videoApiKey', event.target.value)}
              />
            </label>
            <label className="checkbox-row">
              <input
                name="clearVideoApiKey"
                type="checkbox"
                checked={secretDraft.clearVideoApiKey}
                onChange={(event) => updateSecretField('clearVideoApiKey', event.target.checked)}
              />
              清除已保存的视频 API Key
            </label>
            {config.videoProvider !== 'xyq' && (
              <label className="checkbox-row">
                <input
                  name="videoAllowInsecureSsl"
                  type="checkbox"
                  checked={Boolean(config.videoAllowInsecureSsl)}
                  onChange={(event) => updateDraftField('videoAllowInsecureSsl', event.target.checked)}
                />
                跳过 SSL 证书验证（仅用于本地/自签网关）
              </label>
            )}
            <div className="settings-inline-actions">
              <button
                type="button"
                className="secondary"
                disabled={busy.has('testVideoConnection')}
                onClick={(event) => testVideoConnection(event.currentTarget.form)}
              >
                {busy.has('testVideoConnection') ? <Loader2 className="spin" /> : <PlugZap />}
                测试视频连接
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy.has('fetchVideoModels')}
                onClick={async (event) => {
                  const models = await fetchVideoModels(event.currentTarget.form);
                  setVideoModelsPreview(models || []);
                }}
              >
                {busy.has('fetchVideoModels') ? <Loader2 className="spin" /> : <ListTree />}
                获取模型列表
              </button>
            </div>
            {videoModelsPreview.length > 0 && (
              <div className="video-models-preview">
                <strong>可用模型 {videoModelsPreview.length} 个</strong>
                <div className="video-models-preview-list">
                  {videoModelsPreview.map((modelId) => (
                    <span className="video-model-chip" key={modelId}>
                      {modelId}
                    </span>
                  ))}
                </div>
                <small>模型将在「生成视频请求」弹窗中选择，此处仅用于验证网关配置。</small>
              </div>
            )}
          </div>

          <div className="settings-section">
            <h4>图片生成服务</h4>
            <p className="settings-hint">配置 OpenAI 兼容图片网关。人物、场景、物品的实际模型与尺寸在资源管理的资产生成标签分别设置。</p>
            <label className="checkbox-row">
              <input
                type="checkbox"
                name="imageUseLlmCredentials"
                checked={Boolean(config.imageUseLlmCredentials)}
                onChange={(event) => updateDraftField('imageUseLlmCredentials', event.target.checked)}
              />
              复用 LLM 网关的 Base URL 和 API Key
            </label>
            {apiConfig.imageUsingLlmCredentials && <small className="settings-runtime-note">当前图片请求复用：{apiConfig.imageRuntimeBaseUrl}</small>}
            <div className="settings-row">
              <label>
                服务商
                <input
                  name="imageProvider"
                  value={config.imageProvider || 'openai'}
                  onChange={(event) => updateDraftField('imageProvider', event.target.value)}
                />
              </label>
              <label>
                Base URL
                <input name="imageBaseUrl" value={config.imageBaseUrl} disabled={Boolean(config.imageUseLlmCredentials)} onChange={(event) => updateDraftField('imageBaseUrl', event.target.value)} placeholder="https://api.example.com/v1" />
              </label>
            </div>
            <div className="settings-row">
              <label>
                默认模型
                <input name="imageModel" value={config.imageModel} onChange={(event) => updateDraftField('imageModel', event.target.value)} placeholder="gpt-image-1" />
              </label>
              <label>
                默认尺寸
                <input name="imageOutputSize" value={config.imageOutputSize} onChange={(event) => updateDraftField('imageOutputSize', event.target.value)} />
              </label>
            </div>
            <div className="settings-row">
              <label>
                API Key {apiConfig.imageApiKeySet ? '（已保存）' : ''}
                <input type="password" name="imageApiKey" disabled={Boolean(config.imageUseLlmCredentials)} value={secretDraft.imageApiKey} onChange={(event) => setSecretDraft({ ...secretDraft, imageApiKey: event.target.value })} placeholder={apiConfig.imageApiKeySet ? '留空保持现有密钥' : '填写 API Key'} />
              </label>
              <label className="checkbox-row"><input type="checkbox" name="clearImageApiKey" disabled={Boolean(config.imageUseLlmCredentials)} checked={secretDraft.clearImageApiKey} onChange={(event) => setSecretDraft({ ...secretDraft, clearImageApiKey: event.target.checked })} />清除图片 API Key</label>
            </div>
            <div className="settings-actions-row">
                <button
                  type="button"
                  className="secondary"
                  disabled={busy.has('testImageConnection')}
                  onClick={(event) => testImageConnection?.(event.currentTarget.form)}
                >
                  {busy.has('testImageConnection') ? <Loader2 className="spin" /> : <PlugZap />}
                  测试图片网关
                </button>
            </div>
            <input type="hidden" name="imageProtocol" value={config.imageProtocol || 'openai'} />
          </div>

          <button disabled={busy.has('saveApiConfig')}>
            {busy.has('saveApiConfig') ? <Loader2 className="spin" /> : <Save />}
            保存配置
          </button>
        </form>
      </section>
      </div>
      <section className="panel precheck-panel">
        <PanelTitle icon={Server} title="系统预检">
          <button type="button" onClick={runPrecheck} disabled={busy.has('precheck')}>
            {busy.has('precheck') ? <Loader2 className="spin" /> : <RefreshCw />}
            重新预检
          </button>
        </PanelTitle>
        <div className="precheck-list">
          {!precheck && <Empty text="尚未执行预检" />}
          {precheck?.checks?.map((item) => (
            <div className={`precheck-item ${item.status}`} key={item.id}>
              <strong>{item.label}</strong>
              <span>{statusLabel(item.status)}</span>
              <small>{item.detail}</small>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
