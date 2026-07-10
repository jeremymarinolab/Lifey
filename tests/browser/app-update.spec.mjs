import { expect, test } from '@playwright/test';
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';

const updateModule = readFileSync(new URL('../../js/app-updates.js', import.meta.url), 'utf8');

async function startUpdateFixture() {
  let workerVersion = 'version-a';
  let htmlVersion = 'version-a';
  let navigations = 0;
  const server = createServer((request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1');
    response.setHeader('Cache-Control', 'no-store');
    if (url.pathname === '/control') {
      workerVersion = url.searchParams.get('worker') || workerVersion;
      htmlVersion = url.searchParams.get('html') || htmlVersion;
      response.writeHead(204).end();
      return;
    }
    if (url.pathname === '/stats') {
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({ navigations, workerVersion, htmlVersion }));
      return;
    }
    if (url.pathname === '/js/app-updates.js') {
      response.setHeader('Content-Type', 'text/javascript');
      response.end(updateModule);
      return;
    }
    if (url.pathname === '/service-worker.js') {
      response.setHeader('Content-Type', 'text/javascript');
      response.end(`
        const ASSET_VERSION = '${workerVersion}';
        self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
        self.addEventListener('activate', event => event.waitUntil(
          self.clients.claim()
            .then(() => self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
            .then(clients => clients.forEach(client => client.postMessage({ type: 'LIFEY_ACTIVATED', version: ASSET_VERSION })))
        ));
        self.addEventListener('message', event => {
          if (event.data?.type === 'LIFEY_GET_VERSION') event.source?.postMessage({ type: 'LIFEY_VERSION', version: ASSET_VERSION });
        });
      `);
      return;
    }
    if (url.pathname === '/') {
      navigations += 1;
      response.setHeader('Content-Type', 'text/html');
      response.end(`<!doctype html>
        <html data-loaded-version="${htmlVersion}">
          <head><meta name="lifey-asset-version" content="${htmlVersion}"></head>
          <body>
            <main>Update fixture ${htmlVersion}</main>
            <script type="module">
              import { createAppUpdateManager } from './js/app-updates.js';
              window.appUpdates = createAppUpdateManager({ autoReloadDelay: 500 });
              window.appUpdates.init();
            </script>
          </body>
        </html>`);
      return;
    }
    response.writeHead(404).end('Not found');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  return {
    baseURL: `http://127.0.0.1:${address.port}`,
    close: () => new Promise(resolve => server.close(resolve)),
  };
}

test('an already-open Lifey page advances to a newly activated worker exactly once', async ({ page, request }) => {
  const fixture = await startUpdateFixture();
  try {
    await page.goto(fixture.baseURL);
    await page.waitForFunction(() => Boolean(window.appUpdates && navigator.serviceWorker.controller));
    await request.get(`${fixture.baseURL}/control?worker=version-b&html=version-b`);

    await page.evaluate(() => window.appUpdates.checkForUpdates());
    await expect(page.locator('#app-update-banner')).toContainText('A new Lifey version is ready.');
    await page.waitForFunction(() => document.documentElement.dataset.loadedVersion === 'version-b');
    await expect(page.locator('#app-update-banner')).toHaveCount(0);

    await expect.poll(async () => (await (await request.get(`${fixture.baseURL}/stats`)).json()).navigations).toBe(2);
    await page.waitForTimeout(700);
    expect((await (await request.get(`${fixture.baseURL}/stats`)).json()).navigations).toBe(2);
  } finally {
    await fixture.close();
  }
});

test('a stuck HTML version enters recovery instead of reloading forever', async ({ page, request }) => {
  const fixture = await startUpdateFixture();
  try {
    await page.goto(fixture.baseURL);
    await page.waitForFunction(() => Boolean(window.appUpdates && navigator.serviceWorker.controller));
    await request.get(`${fixture.baseURL}/control?worker=version-b&html=version-a`);

    await page.evaluate(() => window.appUpdates.checkForUpdates());
    await expect(page.locator('#app-update-banner')).toContainText('A new Lifey version is ready.');
    await expect(page.locator('#app-update-banner.recovery')).toContainText('Lifey could not finish updating.');
    await expect.poll(async () => (await (await request.get(`${fixture.baseURL}/stats`)).json()).navigations).toBe(2);
    await page.waitForTimeout(700);
    expect((await (await request.get(`${fixture.baseURL}/stats`)).json()).navigations).toBe(2);
  } finally {
    await fixture.close();
  }
});
