import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './tests', timeout: 45000, retries: 0, use: { baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000', headless: true, launchOptions: { executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox', '--disable-dev-shm-usage'] } }, reporter: 'list' });
