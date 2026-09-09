import { useCallback, useRef } from 'react';

import { LLM_REQUEST_TIMEOUT_MS, request } from '../api/client';
import { llmUseCases, isXyqVideoProvider, xyqVideoModelOptions } from '../constants';

export function apiConfigFromForm(formElement) {
  const form = new FormData(formElement);
  const imageUseLlmCredentials = form.get('imageUseLlmCredentials') === 'on';
  const llmUseCaseConfig = Object.fromEntries(
    llmUseCases.map((useCase) => {
      const value = {
        model: form.get(`llmUseCases.${useCase.id}.model`),
        temperature: Number(form.get(`llmUseCases.${useCase.id}.temperature`) || 0),
        maxTokens: Number(form.get(`llmUseCases.${useCase.id}.maxTokens`) || 0),
        timeoutSeconds: Number(form.get(`llmUseCases.${useCase.id}.timeoutSeconds`) || 0),
      };
      if (useCase.id === 'workflow_agent') {
        Object.assign(value, {
          contextWindowTokens: Number(form.get('llmUseCases.workflow_agent.contextWindowTokens') || 128000),
          reservedOutputTokens: Number(form.get('llmUseCases.workflow_agent.reservedOutputTokens') || 12000),
          compressionThreshold: Number(form.get('llmUseCases.workflow_agent.compressionThreshold') || 0.8),
          compressionTarget: Number(form.get('llmUseCases.workflow_agent.compressionTarget') || 0.2),
          recentMessagesToKeep: Number(form.get('llmUseCases.workflow_agent.recentMessagesToKeep') || 8),
        });
      }
      return [useCase.id, value];
    }),
  );
  return {
    llmProvider: form.get('llmProvider'),
    llmBaseUrl: form.get('llmBaseUrl'),
    llmApiKey: form.get('clearLlmApiKey') === 'on' ? null : form.get('llmApiKey'),
    llmDefaultModel: form.get('llmDefaultModel'),
    llmUseCases: llmUseCaseConfig,
    videoProvider: form.get('videoProvider'),
    videoBaseUrl: form.get('videoBaseUrl'),
    videoApiKey: form.get('clearVideoApiKey') === 'on' ? null : form.get('videoApiKey'),
    xyqCliPath: form.get('xyqCliPath'),
    xyqOpenApiBase: form.get('xyqOpenApiBase'),
    imageProvider: form.get('imageProvider') || 'openai',
    imageProtocol: form.get('imageProtocol') || 'openai',
    imageUseLlmCredentials,
    imageBaseUrl: imageUseLlmCredentials ? undefined : form.get('imageBaseUrl'),
    imageModel: form.get('imageModel'),
    imageOutputSize: form.get('imageOutputSize') || '1024x1024',
    imageApiKey: imageUseLlmCredentials ? '' : form.get('clearImageApiKey') === 'on' ? null : form.get('imageApiKey'),
    videoAllowInsecureSsl: form.get('videoAllowInsecureSsl') === 'on',
  };
}

export function useApiConfig({ run, notify, apiConfig, setApiConfig, setPrecheck, setSettingsSaveVersion }) {
  const videoModelsCacheRef = useRef([]);

  const saveApiConfig = useCallback(
    (event) => {
      event.preventDefault();
      const formElement = event.currentTarget;
      return run('saveApiConfig', async () => {
        const nextConfig = apiConfigFromForm(formElement);
        const data = await request('/api/config/apis', {
          method: 'PUT',
          body: JSON.stringify({ data: nextConfig }),
        });
        setApiConfig(data.data);
        videoModelsCacheRef.current = [];
        setSettingsSaveVersion((version) => version + 1);
        const precheckData = await request('/api/config/precheck', { method: 'POST' });
        setPrecheck(precheckData);
        notify('API 配置已保存', 'success');
      });
    },
    [notify, run, setApiConfig, setPrecheck, setSettingsSaveVersion],
  );

  const testLlmConnection = useCallback(
    (useCase, formElement) =>
      run(`testLlm:${useCase}`, async () => {
        const dataOverride = formElement ? apiConfigFromForm(formElement) : undefined;
        const data = await request('/api/config/llm/test', {
          method: 'POST',
          timeoutMs: LLM_REQUEST_TIMEOUT_MS,
          body: JSON.stringify({ use_case: useCase, data: dataOverride }),
        });
        notify(`${data.label} 连通性通过：${data.model}`, 'success');
      }),
    [notify, run],
  );

  const testVideoConnection = useCallback(
    (formElement) =>
      run('testVideoConnection', async () => {
        const dataOverride = formElement ? apiConfigFromForm(formElement) : undefined;
        const data = await request('/api/config/video/test', {
          method: 'POST',
          body: JSON.stringify({ data: dataOverride }),
        });
        const target = data.base_url ? ` @ ${data.base_url}` : '';
        notify(`${data.detail || '视频服务连通性通过'}${target}`, 'success', '视频连通性测试');
      }),
    [notify, run],
  );

  const testImageConnection = useCallback(
    (formElement) =>
      run('testImageConnection', async () => {
        const dataOverride = formElement ? apiConfigFromForm(formElement) : undefined;
        const data = await request('/api/config/image/test', {
          method: 'POST',
          body: JSON.stringify({ data: dataOverride }),
        });
        if (!data.ok) throw new Error(data.detail || '图片服务连通性失败');
        const target = data.base_url ? ` @ ${data.base_url}` : '';
        notify(`${data.detail || '图片网关连通性通过'}${target}`, 'success', '图片服务测试');
      }),
    [notify, run],
  );

  const fetchVideoModels = useCallback(
    (formElement) =>
      run('fetchVideoModels', async () => {
        const dataOverride = formElement ? apiConfigFromForm(formElement) : undefined;
        const data = await request('/api/config/video/models', {
          method: 'POST',
          body: JSON.stringify({ data: dataOverride }),
        });
        const models = Array.isArray(data.models) ? data.models.filter(Boolean) : [];
        videoModelsCacheRef.current = models;
        notify(
          models.length
            ? `已获取 ${models.length} 个视频模型`
            : data.detail || '网关未返回模型列表，请在生成弹窗手动填写模型名',
          models.length ? 'success' : 'info',
          '获取模型列表',
        );
        return models;
      }),
    [notify, run],
  );

  const loadVideoModels = useCallback(
    async (options = {}) => {
      const provider = options.provider || apiConfig?.videoProvider;
      if (isXyqVideoProvider(provider)) {
        const models = xyqVideoModelOptions.map((item) => item.value).filter((value) => value && value !== '__custom__');
        videoModelsCacheRef.current = models;
        return models;
      }
      if (!options.force && videoModelsCacheRef.current.length > 0) {
        return videoModelsCacheRef.current;
      }
      const data = await request('/api/config/video/models');
      const models = Array.isArray(data.models) ? data.models.filter(Boolean) : [];
      videoModelsCacheRef.current = models;
      return models;
    },
    [apiConfig?.videoProvider],
  );

  const runPrecheck = useCallback(
    () =>
      run('precheck', async () => {
        const data = await request('/api/config/precheck', { method: 'POST' });
        setPrecheck(data);
        notify(data.ok ? '系统预检通过' : '系统预检存在警告或失败', data.ok ? 'success' : 'error');
      }),
    [notify, run, setPrecheck],
  );

  return {
    videoModelsCacheRef,
    saveApiConfig,
    testLlmConnection,
    testVideoConnection,
    testImageConnection,
    fetchVideoModels,
    loadVideoModels,
    runPrecheck,
  };
}
