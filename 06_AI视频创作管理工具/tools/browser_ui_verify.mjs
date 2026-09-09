/**
 * Browser UI verification per docs/10_功能操作验证手册.md (P-PATH-01/02, PRE-DOC-01).
 * Usage: node tools/browser_ui_verify.mjs [baseUrl]
 */
import { chromium } from 'playwright';

const BASE = process.argv[2] || 'http://127.0.0.1:8010';
const USER = process.env.AVM_VERIFY_USER || 'verify_manual_user';
const PASSWORD = 'verify123456';
const PROJECT = `手册验证_${Date.now().toString(36).slice(-6)}`;
const DOC_TEXT = '手册验证原文：第一章 开端。\n第二章 发展。';
const OUTPUT_ROOT = 'projects/manual_verify_out';
const SOURCE_ROOT = 'projects/manual_verify_src';

const results = [];

function record(id, ok, detail = '') {
  results.push({ id, ok, detail });
  const mark = ok ? 'PASS' : 'FAIL';
  console.log(`[${mark}] ${id}${detail ? ` — ${detail}` : ''}`);
}

async function selectProjectByName(page, name) {
  if (await page.getByPlaceholder('项目标题').isVisible().catch(() => false)) {
    const row = page.locator('.project-row', { hasText: name }).first();
    if (await row.isVisible().catch(() => false)) {
      await row.click();
      return;
    }
  }
  await page.getByRole('button', { name: '项目管理' }).click();
  await page.locator('.project-row', { hasText: name }).first().click();
}
async function ensureAdmin(page) {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const setupHeading = page.getByRole('heading', { name: '初始化管理员' });
  if (await setupHeading.isVisible().catch(() => false)) {
    await page.locator('input[autocomplete="username"]').fill(USER);
    await page.locator('input[autocomplete="new-password"]').first().fill(PASSWORD);
    await page.locator('input[autocomplete="new-password"]').nth(1).fill(PASSWORD);
    await page.getByRole('button', { name: '创建并进入' }).click();
    await page.waitForTimeout(1500);
    return;
  }
  const loginHeading = page.getByRole('heading', { name: 'AI 视频创作管理' });
  if (await loginHeading.isVisible().catch(() => false)) {
    await page.locator('input[autocomplete="username"]').fill(USER);
    await page.locator('input[type="password"]').fill(PASSWORD);
    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForTimeout(1500);
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    await ensureAdmin(page);
    await page.waitForSelector('button.nav-item', { timeout: 60000 });

    if (!(await page.getByPlaceholder('项目标题').isVisible().catch(() => false))) {
      await page.getByRole('button', { name: '项目管理' }).click();
    }

    // P-PATH-01: create with optional paths
    await page.getByPlaceholder('项目标题').fill(PROJECT);
    await page.getByRole('button', { name: '更多选项' }).click();
    await page.getByPlaceholder('创建时写入项目简介').fill('手册路径验证项目');
    await page.getByPlaceholder('留空使用 projects/{项目ID}').fill('');
    await page.getByPlaceholder('留空使用项目 generated 目录').fill(OUTPUT_ROOT);
    await page.getByPlaceholder('创建后可配合').fill(SOURCE_ROOT);
    await page.getByRole('button', { name: '创建' }).click();
    await page.waitForTimeout(2000);
    const createdVisible = await page.locator('.project-row strong', { hasText: PROJECT }).isVisible().catch(() => false);
    record('P-PATH-01', createdVisible, createdVisible ? PROJECT : '项目未出现在列表');

    // P-PATH-02: paths persist after reload
    await page.getByPlaceholder('留空则使用项目 generated 目录').fill(OUTPUT_ROOT);
    await page.getByPlaceholder('填写素材文件夹路径').fill(SOURCE_ROOT);
    await page.getByRole('button', { name: '保存路径与默认设置' }).click();
    await page.waitForTimeout(1500);
    await page.reload({ waitUntil: 'networkidle' });
    await selectProjectByName(page, PROJECT);
    await page.waitForTimeout(1000);
    const outVal = await page.getByPlaceholder('留空则使用项目 generated 目录').inputValue();
    const srcVal = await page.getByPlaceholder('填写素材文件夹路径').inputValue();
    record('P-PATH-02', outVal === OUTPUT_ROOT && srcVal === SOURCE_ROOT, `out=${outVal} src=${srcVal}`);

    // PRE-DOC-01: document text input + persist
    await page.getByRole('button', { name: '预处理' }).click();
    await page.waitForTimeout(800);
    const textarea = page.locator('.text-panel textarea');
    await textarea.click();
    await textarea.fill(DOC_TEXT);
    await page.locator('.episode-panel').click();
    await page.waitForTimeout(1200);
    await page.reload({ waitUntil: 'networkidle' });
    await selectProjectByName(page, PROJECT);
    await page.getByRole('button', { name: '预处理' }).click();
    await page.waitForTimeout(800);
    const docVal = await page.locator('.text-panel textarea').inputValue();
    record('PRE-DOC-01', docVal.includes('手册验证原文'), `len=${docVal.length}`);

    // PRE-DOC-02: document upload via file input
    await page.getByRole('button', { name: '预处理' }).click();
    await page.waitForTimeout(500);
    const uploadInput = page.locator('.text-panel input[type="file"]');
    await uploadInput.setInputFiles({
      name: 'README-test.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# 标题\n\n导入测试段落内容。'),
    });
    await page.waitForTimeout(2000);
    const uploaded = await page.locator('.text-panel textarea').inputValue();
    record('PRE-DOC-02', uploaded.includes('导入测试段落'), `upload len=${uploaded.length}`);

    const failed = results.filter((item) => !item.ok);
    console.log('\n=== Summary ===');
    console.log(`Total: ${results.length}, Failed: ${failed.length}`);
    await browser.close();
    process.exit(failed.length ? 1 : 0);
  } catch (error) {
    console.error('Browser verify error:', error);
    await browser.close();
    process.exit(1);
  }
}

main();
