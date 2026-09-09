import { useEffect, useId, useMemo, useState } from 'react';

import { isXyqVideoProvider, videoModelOptions, xyqVideoModelOptions } from '../constants';

function staticFallbackModels(isXyq) {
  const source = isXyq ? xyqVideoModelOptions : videoModelOptions;
  return source.map((item) => item.value).filter((value) => value && value !== '__custom__');
}

export default function VideoModelCombobox({
  value = '',
  onChange,
  disabled = false,
  videoProvider = '',
  loadVideoModels,
  placeholder = '从列表选择或手动输入模型 ID；留空表示服务默认',
}) {
  const listId = useId();
  const isXyq = isXyqVideoProvider(videoProvider);
  const [models, setModels] = useState(() => staticFallbackModels(isXyq));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!loadVideoModels) {
      setModels(staticFallbackModels(isXyq));
      setLoading(false);
      setError('');
      return undefined;
    }

    let cancelled = false;
    setLoading(true);
    setError('');
    loadVideoModels({ provider: videoProvider })
      .then((list) => {
        if (cancelled) return;
        const next = Array.isArray(list) ? list.filter(Boolean) : [];
        setModels(next.length ? next : staticFallbackModels(isXyq));
      })
      .catch((fetchError) => {
        if (cancelled) return;
        setError(fetchError.message || '无法获取模型列表');
        setModels(staticFallbackModels(isXyq));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isXyq, loadVideoModels, videoProvider]);

  const labelByValue = useMemo(() => {
    const source = isXyq ? xyqVideoModelOptions : videoModelOptions;
    return Object.fromEntries(source.map((item) => [item.value, item.label]));
  }, [isXyq]);

  const options = useMemo(() => {
    const unique = new Set(models);
    const current = String(value || '').trim();
    if (current) unique.add(current);
    return Array.from(unique).map((modelId) => ({
      value: modelId,
      label: labelByValue[modelId] || modelId,
    }));
  }, [labelByValue, models, value]);

  return (
    <>
      <input
        type="text"
        list={listId}
        value={value}
        disabled={disabled || loading}
        placeholder={loading ? '加载模型列表…' : placeholder}
        onChange={(event) => onChange?.(event.target.value)}
      />
      <datalist id={listId}>
        <option value="">服务默认</option>
        {options.map((option) => (
          <option key={option.value} value={option.value} label={option.label} />
        ))}
      </datalist>
      {error ? <small className="project-overview-hint">{error}，仍可手动输入模型 ID。</small> : null}
      {!error && !loading && options.length > 0 ? (
        <small className="project-overview-hint">已加载 {options.length} 个模型，可直接输入未列出的 ID。</small>
      ) : null}
    </>
  );
}
