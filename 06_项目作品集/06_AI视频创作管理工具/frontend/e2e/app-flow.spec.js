import { expect, test } from '@playwright/test';

test('project route survives refresh and production pages remain usable', async ({ page }) => {
  await page.goto('/projects');
  const loginButton = page.getByRole('button', { name: '登录' });
  if (await loginButton.isVisible().catch(() => false)) {
    await page.getByPlaceholder('请输入用户名').fill('e2eadmin');
    await page.getByPlaceholder('请输入密码').fill('e2e-password');
    await loginButton.click();
  }
  await expect(page.getByText('项目管理', { exact: true }).first()).toBeVisible();

  const project = await page.evaluate(async () => {
    const response = await fetch('http://127.0.0.1:8001/api/projects', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'V2 E2E 项目', category: 'active' }),
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  });

  await page.reload();
  await page.getByRole('button', { name: new RegExp(`^${project.name}`) }).first().click();
  await page.goto(`/projects/${project.id}/preprocess`);
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/preprocess$`));
  await expect(page.getByText('预处理', { exact: true }).first()).toBeVisible();
  const contentType = page.locator('.content-type-field input');
  await contentType.evaluate((input) => {
    input.focus();
    input.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setValue.call(input, '分集原文，剧本格式');
    input.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      data: '剧本格式',
      inputType: 'insertCompositionText',
      isComposing: true,
    }));
    input.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '剧本格式' }));
    input.blur();
  });
  await page.waitForTimeout(700);
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/preprocess$`));
  await expect(contentType).toHaveValue('分集原文，剧本格式');

  for (const [label, route] of [
    ['资源管理', 'resources'],
    ['视频生成', 'video'],
    ['提示词管理', 'prompts'],
  ]) {
    await page.getByText(label, { exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/${route}$`));
  }
  await expect(page.locator('.template-row.selected')).toHaveCount(1);
  await expect(page.locator('#prompt-template-form input').first()).not.toHaveValue('');
  await expect(page.locator('.template-warning')).toHaveCount(0);

  const layout = await page.evaluate(() => {
    const nav = document.querySelector('.sidebar');
    const rect = nav?.getBoundingClientRect();
    return {
      bodyOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      navTop: rect?.top,
      navHeight: rect?.height,
      viewportHeight: window.innerHeight,
    };
  });
  expect(layout.bodyOverflow).toBe(false);
  expect(layout.navTop).toBe(0);
  expect(layout.navHeight).toBeGreaterThanOrEqual(layout.viewportHeight - 2);

  await page.screenshot({ path: '../.tmp/e2e-artifacts/v2-ui-desktop.png', fullPage: true });
});
