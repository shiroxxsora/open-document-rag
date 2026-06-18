import { expect, test } from '@playwright/test';

test('dev login redirects to home', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel(/email/i).fill('e2e-user@example.com');
  await page.getByRole('button', { name: /sign in|login|dev/i }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByText(/Universal RAG MVP/i)).toBeVisible();
});

test('settings page loads', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel(/email/i).fill('e2e-settings@example.com');
  await page.getByRole('button', { name: /sign in|login|dev/i }).click();
  await page.goto('/settings');
  await expect(page.getByText(/LLM settings/i)).toBeVisible();
});
