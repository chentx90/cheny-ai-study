import { expect, test } from '@playwright/test';

test('resource production tabs persist and native image settings are reachable', async ({ page }) => {
  await page.goto('/projects');
  const project = await page.evaluate(async () => {
    const response = await fetch('http://127.0.0.1:8001/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ name: 'V3 资产生产项目', category: 'active' }),
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  });

  await page.reload();
  await page.getByRole('button', { name: new RegExp(`^${project.name}`) }).first().click();
  await page.goto(`/projects/${project.id}/resources`);
  for (const label of ['实体清单', '实体卡库', '资产生成', '项目素材']) {
    await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByText('分析范围', { exact: true })).toBeVisible();
  await expect(page.getByText('项目暂无分集', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '分析剧本', exact: true })).toBeDisabled();

  await page.evaluate(async (projectId) => {
    const episodes = [
      { order: 1, title: '第一集', source_text: '原文一', script_text: '场景：书房\n人物：林舟\n林舟翻开桌上的旧信。' },
      { order: 2, title: '第二集', source_text: '原文二', script_text: '' },
    ];
    for (const episode of episodes) {
      const response = await fetch(`http://127.0.0.1:8001/api/v2/projects/${projectId}/episodes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(episode),
      });
      if (!response.ok) throw new Error(await response.text());
    }
  }, project.id);
  await page.reload();
  await expect(page.getByRole('button', { name: '取消全选', exact: true })).toBeVisible();
  await expect(page.getByText('已选 1 / 1', { exact: true })).toBeVisible();
  await expect(page.getByLabel('第一集', { exact: true })).toBeEnabled();
  await expect(page.getByLabel('第二集 · 无剧本', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('第一集', { exact: true })).toBeChecked();
  await page.getByRole('button', { name: '取消全选', exact: true }).click();
  await expect(page.getByText('已选 0 / 1', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('第一集', { exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: '全选', exact: true }).click();
  await page.screenshot({ path: '../.tmp/e2e-artifacts/resource-v3-profiles-desktop.png', fullPage: true });

  await page.getByRole('button', { name: '实体卡库', exact: true }).click();
  await expect(page.getByText('实体卡库', { exact: true }).last()).toBeVisible();
  await page.getByRole('button', { name: '项目素材', exact: true }).click();
  await expect(page.getByText('项目素材', { exact: true }).last()).toBeVisible();
  await page.getByRole('button', { name: '资产生成', exact: true }).click();
  await expect(page.getByRole('button', { name: '提示词与任务', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '风格与预设', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '风格与预设', exact: true }).click();
  await expect(page.getByText('项目视觉风格', { exact: true })).toBeVisible();
  await expect(page.getByText('分类生成预设', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '保存人物预设', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '保存场景预设', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '保存物品预设', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: '资产生成', exact: true })).toHaveClass(/active/);
  await expect(page.getByRole('button', { name: '风格与预设', exact: true })).toHaveClass(/active/);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
  await page.screenshot({ path: '../.tmp/e2e-artifacts/resource-v3-desktop.png', fullPage: true });

  await page.getByRole('button', { name: '设置', exact: true }).click();
  await expect(page.getByText('图片生成服务', { exact: true })).toBeVisible();
  await expect(page.locator('input[name="imageBaseUrl"]')).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${project.id}/resources`);
  await expect(page.getByRole('button', { name: '资产生成', exact: true })).toBeVisible();
  const sidebarBox = await page.locator('.sidebar').boundingBox();
  const workspaceBox = await page.locator('.workspace').boundingBox();
  expect(sidebarBox?.height || 999).toBeLessThan(220);
  expect(workspaceBox?.y || 999).toBeLessThan(220);
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(mobileOverflow).toBe(false);
  await page.screenshot({ path: '../.tmp/e2e-artifacts/resource-v3-mobile.png', fullPage: true });
});
