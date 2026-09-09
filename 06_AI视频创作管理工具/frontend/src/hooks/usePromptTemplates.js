import { useCallback } from 'react';

import { request } from '../api/client';

function sortTemplates(items) {
  return [...items].sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
}

export function usePromptTemplates({ run, notify, askConfirm, setTemplates, setSelectedTemplateId }) {
  const savePromptTemplate = useCallback(
    (templateId, payload) =>
      run('savePromptTemplate', async () => {
        const template = await request(
          templateId ? `/api/prompts/templates/${encodeURIComponent(templateId)}` : '/api/prompts/templates',
          { method: templateId ? 'PUT' : 'POST', body: JSON.stringify(payload) },
        );
        setTemplates((prev) =>
          sortTemplates(templateId ? prev.map((item) => (item.id === template.id ? template : item)) : [...prev, template]),
        );
        setSelectedTemplateId(template.id);
        notify(`提示词预设已保存：${template.name}`, 'success');
        return template;
      }),
    [notify, run, setSelectedTemplateId, setTemplates],
  );

  const deletePromptTemplate = useCallback(
    (template) =>
      run(`deletePromptTemplate:${template.id}`, async () => {
        const confirmed = await askConfirm({
          title: '删除提示词预设',
          body: '删除后，该预设不会再用于对应 LLM 调用点。',
          tone: 'danger',
          confirmLabel: '删除',
          items: [
            { label: '预设', value: template.name },
            { label: '分类', value: template.category },
          ],
        });
        if (!confirmed) return;
        await request(`/api/prompts/templates/${encodeURIComponent(template.id)}`, { method: 'DELETE' });
        setTemplates((prev) => prev.filter((item) => item.id !== template.id));
        setSelectedTemplateId('');
        notify(`提示词预设已删除：${template.name}`, 'success');
      }),
    [askConfirm, notify, run, setSelectedTemplateId, setTemplates],
  );

  const loadPromptTemplateVersions = useCallback(async (templateId) => {
    if (!templateId) return [];
    const data = await request(`/api/prompts/templates/${encodeURIComponent(templateId)}/versions`);
    return data.versions || [];
  }, []);

  const restorePromptTemplateVersion = useCallback(
    (template, version) =>
      run(`restorePromptTemplate:${template.id}`, async () => {
        const confirmed = await askConfirm({
          title: '恢复提示词历史版本',
          body: '历史内容会作为一个新版本保存，现有版本仍保留在记录中。',
          confirmLabel: '恢复',
          items: [
            { label: '预设', value: template.name },
            { label: '历史版本', value: `v${version}` },
          ],
        });
        if (!confirmed) return;
        const restored = await request(
          `/api/prompts/templates/${encodeURIComponent(template.id)}/versions/${version}/restore`,
          { method: 'POST' },
        );
        setTemplates((prev) => sortTemplates(prev.map((item) => (item.id === restored.id ? restored : item))));
        setSelectedTemplateId(restored.id);
        notify(`已恢复为新版本：${restored.name} v${restored.version}`, 'success');
      }),
    [askConfirm, notify, run, setSelectedTemplateId, setTemplates],
  );

  return { savePromptTemplate, deletePromptTemplate, loadPromptTemplateVersions, restorePromptTemplateVersion };
}
