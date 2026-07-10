import { expect, test } from '@playwright/test';

test.beforeEach(async ({ context }) => {
  await context.addInitScript(() => {
    const state = {
      tasks: [
        {
          id: 'smoke-task',
          text: 'Smoke test task',
          source: 'Daily/Smoke.md',
          line: 7,
          raw: '- [ ] Smoke test task',
          done: false,
          priority: 'normal'
        }
      ],
      suggestions: []
    };
    localStorage.clear();
    localStorage.setItem('lifey-state', JSON.stringify(state));
    localStorage.setItem('lifey-ui-state-v1', JSON.stringify(state));
  });
});

test('dashboard boots and renders primary cards', async ({ page }) => {
  const failures = browserFailureCollector(page);

  await page.goto('/');
  await expect(page.locator('.shell')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Lifey home' })).toBeVisible();
  await expect(page.locator('#dashboard-stats')).toBeVisible();
  await expect(page.locator('#dashboard-grid')).toBeVisible();
  await expect(page.locator('[data-card-key="tasks"]')).toBeVisible();
  await expect(page.getByRole('heading', { name: /Today.s tasks/ })).toBeVisible();
  await expect(page.locator('[data-card-key="tasks"] > header')).toBeVisible();
  await expect(page.locator('[data-card-key="projects"] [data-ui="empty-state"]')).toContainText('No project-tagged tasks');

  expect(failures()).toEqual([]);
});

test('extracted UI components expose stable semantics', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.shell')).toBeVisible();

  const youtubePanel = page.locator('[data-card-key="youtube"]');
  await expect(youtubePanel.locator('.segmented-control')).toBeVisible();
  await expect(youtubePanel.getByRole('tab', { name: 'Today' })).toHaveAttribute('aria-selected', 'true');
  await expect(youtubePanel.getByRole('tab', { name: 'This week' })).toHaveAttribute('aria-selected', 'false');
  await expect(youtubePanel.locator('.segmented-filter')).toBeVisible();

  await expect(page.locator('[data-card-key="spotify"]').getByRole('button', { name: 'Connect Spotify' }).first()).toBeVisible();
  await expect(page.locator('.suggestion-list .save').first()).toHaveAttribute('aria-label', /Open|Source link unavailable/);
});

test('quick capture and settings modal workflows are wired', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.shell')).toBeVisible();

  await page.getByRole('button', { name: /Quick capture/ }).click();
  await expect(page.locator('dialog[open] .capture-raycast')).toBeVisible();
  await page.locator('#capture-task').fill('Call Alex tomorrow at 2');
  await expect(page.locator('#capture-preview')).toContainText('Call Alex');
  await page.locator('[data-action="open-capture-calendar"]').click();
  await expect(page.locator('#capture-calendar .capture-datetime')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('dialog[open] .capture-raycast')).toHaveCount(0);

  await page.getByRole('button', { name: /Settings/ }).click();
  await expect(page.locator('dialog[open] .preferences')).toBeVisible();
  await expect(page.getByRole('button', { name: /Integrations/ })).toBeVisible();
  await page.getByRole('button', { name: /Appearance/ }).click();
  await expect(page.getByRole('heading', { name: 'Appearance' })).toBeVisible();
  await page.getByRole('button', { name: /Profile/ }).click();
  await expect(page.getByRole('heading', { name: 'Backup and transfer' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Version and cache' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Check for updates' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Clear app cache and reload' })).toBeVisible();
});

test('show note path toggle keeps settings open and only updates task metadata', async ({ page }) => {
  const failures = browserFailureCollector(page);

  await page.goto('/');
  await expect(page.locator('[data-card-key="tasks"] [data-task-meta]').first()).toContainText('Daily/Smoke.md');

  await page.getByRole('button', { name: /Settings/ }).click();
  await page.getByRole('button', { name: /Appearance/ }).click();
  await expect(page.locator('dialog[open] .preferences')).toBeVisible();

  const tasksVisibility = page.locator('[data-visibility="tasks"]');
  const showPath = page.locator('[data-task-display="showPath"]');
  await expect(tasksVisibility).toBeChecked();
  await expect(showPath).toBeChecked();

  await showPath.click();

  await expect(page.locator('dialog[open] .preferences')).toBeVisible();
  await expect(page.locator('dialog[open] .preferences main')).not.toBeEmpty();
  await expect(tasksVisibility).toBeChecked();
  await expect(showPath).not.toBeChecked();
  await expect(page.locator('[data-card-key="tasks"] [data-task-meta]').first()).toHaveText('L7');

  await showPath.click();

  await expect(page.locator('dialog[open] .preferences')).toBeVisible();
  await expect(tasksVisibility).toBeChecked();
  await expect(showPath).toBeChecked();
  await expect(page.locator('[data-card-key="tasks"] [data-task-meta]').first()).toContainText('Daily/Smoke.md');
  expect(failures()).toEqual([]);
});

test('service worker registers for the app shell', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.shell')).toBeVisible();

  const registration = await page.evaluate(async () => {
    if (!('serviceWorker' in navigator)) return null;
    const ready = await navigator.serviceWorker.ready;
    return {
      scope: ready.scope,
      scriptURL: ready.active?.scriptURL || ready.installing?.scriptURL || ready.waiting?.scriptURL || ''
    };
  });

  expect(registration?.scope).toBe(new URL('/', page.url()).href);
  expect(registration?.scriptURL).toContain('/service-worker.js');
});

function browserFailureCollector(page) {
  const failures = [];
  page.on('pageerror', error => failures.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') failures.push(message.text());
  });
  return () => failures;
}
