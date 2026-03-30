const { test, expect } = require('@playwright/test');
const { loginAsAdmin } = require('./helpers.cjs');

test('auth persists across hard navigation', async ({ page }) => {
  await loginAsAdmin(page);

  const before = await page.evaluate(() => {
    const raw = window.localStorage.getItem('plant_auth_token');
    return raw ? JSON.parse(raw) : null;
  });
  await page.goto('http://127.0.0.1:5500/?workspace=details', { waitUntil: 'networkidle' });
  const after = await page.evaluate(() => {
    const raw = window.localStorage.getItem('plant_auth_token');
    return raw ? JSON.parse(raw) : null;
  });
  const userBlockCount = await page.locator('.topbar__user').count();
  const dialogCount = await page.getByRole('dialog', { name: '登录与注册' }).count();

  expect(before?.v).toBe(1);
  expect(typeof before?.iv).toBe('string');
  expect(typeof before?.cipher).toBe('string');
  expect(after?.v).toBe(1);
  expect(typeof after?.iv).toBe('string');
  expect(typeof after?.cipher).toBe('string');
  expect(userBlockCount).toBe(1);
  expect(dialogCount).toBe(0);
});
