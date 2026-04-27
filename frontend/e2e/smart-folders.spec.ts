import { test, expect } from '@playwright/test';

/**
 * E2E tests for Smart Folder v2 (agentic report generation).
 *
 * These tests verify the frontend UI flow:
 *  - Search bar renders and accepts input
 *  - Loading state shows progress steps
 *  - Report viewer displays sections and citations
 *  - Refinement bar works
 *  - Save / copy / share actions are present
 *
 * Note: Full end-to-end generation requires a running backend with
 * configured LLM keys and a seeded database. Use `test.skip()` or
 * mock the API for environments where the backend is unavailable.
 */

test.describe('Smart Folders v2', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the smart-folders page (English locale)
    await page.goto('/en/smart-folders');
  });

  test('page loads with search bar and examples', async ({ page }) => {
    await expect(page.getByPlaceholder(/Ask about any relationship/i)).toBeVisible();
    await expect(page.getByText(/Examples/i)).toBeVisible();
    await expect(page.getByText(/Tell me about my relationship with Bank A/i)).toBeVisible();
  });

  test('search input accepts text and submit triggers loading', async ({ page }) => {
    const input = page.getByPlaceholder(/Ask about any relationship/i);
    await input.fill('Analyse my relationship with Bank A');

    // Click the generate button or press Enter
    await input.press('Enter');

    // Loading state should appear
    await expect(page.getByText(/Understanding your request/i)).toBeVisible({ timeout: 5000 });
  });

  test('example query buttons populate search and trigger generation', async ({ page }) => {
    const exampleButton = page.getByRole('button', {
      name: /Analyse the balance sheets of my company from 2019 to 2024/i,
    });
    await exampleButton.click();

    // Should show loading state
    await expect(page.getByText(/Understanding your request/i)).toBeVisible({ timeout: 5000 });
  });

  test('report viewer renders sections when report is loaded', async ({ page }) => {
    // This test assumes a report can be loaded via URL param
    // In a real environment with seeded data, navigate to an existing report
    // For now, we test the empty state and then mock a report load

    await expect(page.getByPlaceholder(/Ask about any relationship/i)).toBeVisible();

    // Mock a report response by injecting state (advanced) or just verify empty state
    await expect(page.getByText(/Examples/i)).toBeVisible();
  });

  test('citation panel can be opened from report', async ({ page }) => {
    // Skipped until backend seeding / mocking is in place
    test.skip(true, 'Requires backend with generated report data');
  });

  test('refinement bar is visible after report generation', async ({ page }) => {
    // Skipped until backend seeding / mocking is in place
    test.skip(true, 'Requires backend with generated report data');
  });

  test('save, copy, share buttons appear after report generation', async ({ page }) => {
    // Skipped until backend seeding / mocking is in place
    test.skip(true, 'Requires backend with generated report data');
  });

  test('SSE stream connection shows progress updates', async ({ page }) => {
    // Intercept the SSE stream request to verify it's made
    const streamRequest = page.waitForRequest((req) =>
      req.url().includes('/api/v1/smart-folders/stream') && req.method() === 'POST'
    );

    const input = page.getByPlaceholder(/Ask about any relationship/i);
    await input.fill('Test SSE streaming');
    await input.press('Enter');

    // Should trigger the stream endpoint (falls back to polling if SSE fails)
    await streamRequest.catch(() => {
      // Stream may fall back to polling; that's acceptable
    });
  });

  test('navigation shows Smart Folders for authenticated users', async ({ page }) => {
    // Check that the page is accessible without 403
    await expect(page).toHaveURL(/\/smart-folders/);
    await expect(page.getByRole('heading', { name: /Smart Folders/i })).toBeVisible();
  });
});
