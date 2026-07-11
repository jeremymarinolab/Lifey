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
      suggestions: [],
      taskDate: '2026-01-01'
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
  await expect(page.locator('[data-card-key="calendar"]').getByRole('button', { name: /Create event/ })).toHaveCount(0);

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
  const showPath = page.getByRole('switch', { name: 'Show note path' });
  await expect(tasksVisibility).toBeChecked();
  await expect(showPath).toHaveAttribute('aria-checked', 'true');
  await page.locator('#modal').evaluate(element => { element.dataset.regressionIdentity = 'original'; });

  await showPath.click();

  await expect(page.locator('dialog[open] .preferences')).toBeVisible();
  await expect(page.locator('dialog[open] .preferences main')).not.toBeEmpty();
  await expect(page.locator('#modal')).toHaveAttribute('data-regression-identity', 'original');
  await expect(tasksVisibility).toBeChecked();
  await expect(showPath).toHaveAttribute('aria-checked', 'false');
  await expect(page.locator('[data-card-key="tasks"] [data-task-meta]').first()).toHaveText('L7');

  await showPath.click();

  await expect(page.locator('dialog[open] .preferences')).toBeVisible();
  await expect(tasksVisibility).toBeChecked();
  await expect(showPath).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('[data-card-key="tasks"] [data-task-meta]').first()).toContainText('Daily/Smoke.md');
  expect(failures()).toEqual([]);
});

test('show note path storage failure rolls back without emptying settings', async ({ page }) => {
  const failures = browserFailureCollector(page);
  await page.goto('/');
  await page.getByRole('button', { name: /Settings/ }).click();
  await page.getByRole('button', { name: /Appearance/ }).click();

  const showPath = page.getByRole('switch', { name: 'Show note path' });
  await expect(showPath).toHaveAttribute('aria-checked', 'true');
  await page.evaluate(() => {
    window.__lifeyOriginalStorageSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = () => { throw new DOMException('Storage full', 'QuotaExceededError'); };
  });

  await showPath.click();

  await expect(page.locator('dialog[open] .preferences')).toBeVisible();
  await expect(page.locator('dialog[open] .preferences main')).not.toBeEmpty();
  await expect(showPath).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('dialog[open] .modal-error')).toContainText('could not save this setting');
  await page.evaluate(() => { Storage.prototype.setItem = window.__lifeyOriginalStorageSetItem; });
  expect(failures()).toEqual([]);
});

test('show note path visible switch remains usable in mobile settings', async ({ page }) => {
  const failures = browserFailureCollector(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.locator('[data-action="settings"]').evaluate(button => button.click());
  await page.getByRole('button', { name: /Appearance/ }).click();

  const modal = page.locator('dialog[open] .preferences');
  const showPath = page.getByRole('switch', { name: 'Show note path' });
  await expect(modal).toBeVisible();
  await expect(showPath).toHaveAttribute('aria-checked', 'true');
  await showPath.click();

  await expect(modal).toBeVisible();
  await expect(page.locator('dialog[open] .preferences main')).not.toBeEmpty();
  await expect(showPath).toHaveAttribute('aria-checked', 'false');
  expect(failures()).toEqual([]);
});

test('calendar open today action stays on one line and right aligned on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');

  const footer = page.locator('[data-card-key="calendar"] > footer');
  const verifyButton = footer.locator('[data-action="connect-google"]');
  const openTodayButton = footer.locator('[data-action="open-google-calendar"]');
  await expect(openTodayButton).toBeVisible();

  const layout = await footer.evaluate(element => {
    const verify = element.querySelector('[data-action="connect-google"]');
    const openToday = element.querySelector('[data-action="open-google-calendar"]');
    const footerRect = element.getBoundingClientRect();
    const openRect = openToday.getBoundingClientRect();
    const verifyStyle = getComputedStyle(verify);
    const openStyle = getComputedStyle(openToday);
    return {
      rightGap: Math.round(footerRect.right - openRect.right),
      footerPaddingRight: Math.round(parseFloat(getComputedStyle(element).paddingRight)),
      whiteSpace: openStyle.whiteSpace,
      fitsOneLine: openToday.scrollWidth <= openToday.clientWidth,
      equalHorizontalPadding: verifyStyle.paddingLeft === openStyle.paddingLeft && verifyStyle.paddingRight === openStyle.paddingRight,
    };
  });

  expect(layout.whiteSpace).toBe('nowrap');
  expect(layout.fitsOneLine).toBe(true);
  expect(layout.equalHorizontalPadding).toBe(true);
  expect(layout.rightGap).toBe(layout.footerPaddingRight);
});

test('quick capture becomes a proportional appearance-aware floating action on narrow portrait screens', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');

  const quickCapture = page.locator('.quick-action-mobile[data-action="quick-add"]');
  await expect(quickCapture).toHaveAttribute('aria-label', 'Quick capture');

  const mobileLayout = await quickCapture.evaluate(element => {
    const style = getComputedStyle(element);
    const icon = element.querySelector('.quick-action-icon');
    const iconRect = icon.getBoundingClientRect();
    const horizontalBar = getComputedStyle(icon, '::before');
    const verticalBar = getComputedStyle(icon, '::after');
    const quickActionRadius = Number(getComputedStyle(document.documentElement).getPropertyValue('--quick-action-radius').replace('px', ''));
    const rect = element.getBoundingClientRect();
    return {
      position: style.position,
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      radius: Math.round(Number(style.borderTopLeftRadius.replace('px', ''))),
      expectedRadius: quickActionRadius,
      borderWidth: style.borderTopWidth,
      shadow: style.boxShadow,
      transitionProperty: style.transitionProperty,
      hasLinearGlass: style.backgroundImage.startsWith('linear-gradient'),
      solidAccentBase: style.backgroundColor === 'rgb(255, 110, 85)',
      iconCentered: Math.abs((rect.left + rect.width / 2) - (iconRect.left + iconRect.width / 2)) < .5 && Math.abs((rect.top + rect.height / 2) - (iconRect.top + iconRect.height / 2)) < .5,
      horizontalBar: [horizontalBar.width, horizontalBar.height, horizontalBar.backgroundColor],
      verticalBar: [verticalBar.width, verticalBar.height, verticalBar.backgroundColor],
      rightGap: Math.round(document.documentElement.clientWidth - rect.right),
      bottomGap: Math.round(document.documentElement.clientHeight - rect.bottom),
    };
  });

  expect(mobileLayout).toEqual({
    position: 'fixed',
    width: 60,
    height: 60,
    radius: mobileLayout.expectedRadius,
    expectedRadius: mobileLayout.expectedRadius,
    borderWidth: '0px',
    shadow: 'none',
    transitionProperty: 'transform',
    hasLinearGlass: true,
    solidAccentBase: true,
    iconCentered: true,
    horizontalBar: ['26px', '3px', 'rgb(255, 255, 255)'],
    verticalBar: ['3px', '26px', 'rgb(255, 255, 255)'],
    rightGap: 18,
    bottomGap: 18,
  });

  await quickCapture.hover();
  await page.waitForTimeout(220);
  const hoverLayout = await quickCapture.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return { width: Math.round(rect.width), height: Math.round(rect.height), filter: style.filter, shadow: style.boxShadow };
  });
  expect(hoverLayout).toEqual({ width: 63, height: 63, filter: 'none', shadow: 'none' });

  await quickCapture.click();
  await expect(page.locator('dialog[open] .capture-raycast')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('dialog[open] .capture-raycast')).toHaveCount(0);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(220);

  await page.setViewportSize({ width: 700, height: 1000 });
  const narrowDesktopLayout = await quickCapture.evaluate(element => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return {
      position: style.position,
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      rightGap: Math.round(document.documentElement.clientWidth - rect.right),
      bottomGap: Math.round(document.documentElement.clientHeight - rect.bottom),
    };
  });

  expect({ ...narrowDesktopLayout, bottomGap: 18 }).toEqual({ position: 'fixed', width: 60, height: 60, rightGap: 18, bottomGap: 18 });
  expect(narrowDesktopLayout.bottomGap).toBeGreaterThanOrEqual(18);
  expect(narrowDesktopLayout.bottomGap).toBeLessThanOrEqual(19);
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
