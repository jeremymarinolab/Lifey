import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.LIFEY_TEST_PORT || 4174);

export default defineConfig({
  testDir: './tests/browser',
  timeout: 30_000,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure'
  },
  webServer: {
    command: `LIFEY_PORT=${port} python3 local_server.py`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    stdout: 'ignore',
    stderr: 'ignore',
    timeout: 15_000
  }
});
