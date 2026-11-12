import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// The defaults a new user gets: automatic analysis and the simple view. Real 4K HDR tripod footage, nothing mocked.
test.use({ storageState: { cookies: [], origins: [] } });
const CLIP = path.resolve(import.meta.dirname, "../../data/tripod_nov09/originals/IMG_7238.MOV");

test("upload, automatic analysis, simple view, and two-click route setup", async ({ page, request }) => {
  test.skip(!fs.existsSync(CLIP), "Tripod footage is private and not present");
  test.setTimeout(480_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1280, height: 1500 });
  await page.goto("/");
  await expect(page.getByTestId("auto-analyze")).toBeChecked();
  await page.getByTestId("file-input").setInputFiles(CLIP);

  // No bounds screen and no Analyze button: the review appears by itself.
  await expect(page.getByTestId("glance")).toBeVisible({ timeout: 300_000 });
  await expect(page.getByTestId("start-analysis")).toHaveCount(0);
  const attemptId = page.url().split("/").pop()!;
  const attempt = await (await request.get(`/api/attempts/${attemptId}`)).json();
  expect(attempt.analyses).toHaveLength(1);
  expect(attempt.analyses[0].attempt_bounds_ms).toEqual({ start: 0, end: attempt.duration_ms });
  const runId = attempt.analyses[0].id;

  // Simple view: suggestions and route, without the evidence panels.
  await expect(page.getByTestId("view-simple")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "Timeline" })).toHaveCount(0);
  await expect(page.getByTestId("movement-chart")).toHaveCount(0);
  const coaching = await (await request.get(`/api/analyses/${runId}/coaching`)).json();
  expect(await page.getByTestId("cue-card").count()).toBe(Math.min(3, coaching.cards.length));
  if (coaching.cards.length > 3) {
    await page.getByTestId("toggle-all-cards").click();
    await expect(page.getByTestId("cue-card")).toHaveCount(coaching.cards.length);
  }
  await expect(page.getByTestId("glance")).toContainText("hand moves tracked");

  // Route setup: one click on a hold, one on the start, then save.
  await page.getByTestId("route-setup-open").click();
  const svg = page.getByTestId("route-setup-svg");
  await expect(svg).toBeVisible({ timeout: 60_000 });
  await svg.scrollIntoViewIfNeeded();
  const clickAt = async (x: number, y: number) => {
    const point = await svg.evaluate((node, [px, py]) => {
      const s = node as SVGSVGElement;
      const p = new DOMPoint(px * s.viewBox.baseVal.width, py * s.viewBox.baseVal.height).matrixTransform(s.getScreenCTM()!);
      return { x: p.x, y: p.y };
    }, [x, y]);
    await page.mouse.click(point.x, point.y);
  };
  await clickAt(0.02, 0.5);                                   // bare wall is refused
  await expect(page.getByTestId("route-setup").getByRole("alert")).toContainText("looks like wall");
  await clickAt(0.444, 0.649);                                // a saturated blue hold of this route
  await expect(page.getByTestId("proposed-hold").first()).toBeVisible({ timeout: 30_000 });
  const proposed = await page.getByTestId("proposed-hold").count();
  console.log(`proposed holds ${proposed}`);
  expect(proposed).toBeGreaterThanOrEqual(6);
  await expect(page.locator('[data-testid="proposed-hold"][data-role="finish"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="proposed-hold"][data-role="start"]')).toHaveCount(0);   // start is never guessed
  await expect(page.getByTestId("route-save")).toBeDisabled();
  await expect(page.getByTestId("route-step")).toContainText("Step 2 of 2");
  expect((await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json())).toHaveLength(0);   // nothing saved yet
  await page.getByTestId("proposed-hold").first().click();    // lowest proposed hold as the start
  await expect(page.locator('[data-testid="proposed-hold"][data-role="start"]')).toHaveCount(1);
  await page.getByTestId("route-save").click();

  // The saved route appears on the wall, is checked against the video, and feeds the route panels.
  await expect(page.getByTestId("beta-figure")).toBeVisible({ timeout: 60_000 });
  const maps = await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json();
  expect(maps).toHaveLength(1);
  expect(maps[0].holds.filter((h: { role: string }) => h.role === "start")).toHaveLength(1);
  expect(maps[0].holds.filter((h: { role: string }) => h.role === "finish")).toHaveLength(1);
  await expect(page.getByTestId("observed-route")).toBeVisible({ timeout: 60_000 });
  const after = await (await request.get(`/api/analyses/${runId}/coaching`)).json();
  console.log(`alignment ${after.hold_map.alignment.status}; visits ${after.observed_route.visits.length}; unvisited ${after.observed_route.unvisited.length}; uses ${maps[0].holds.filter((h: { use: string }) => h.use).length}/${maps[0].holds.length}`);
  expect(after.hold_map.alignment.status).toBe("fixed_verified");
  const beta = await (await request.get(`/api/analyses/${runId}/candidate-beta`)).json();
  console.log(`candidate status ${beta.status}; candidates ${beta.candidates.length}; needs ${JSON.stringify(beta.needs)}`);
  expect(["ready", "no_candidate"]).toContain(beta.status);
  // Distances on this real wall are measured on the wall plane recovered from its bolt holes.
  console.log(`perspective ${JSON.stringify({ applied: beta.perspective.applied, bolts: beta.perspective.bolts_used, change: beta.perspective.scale_change, tilt: beta.perspective.tilt?.angle_to_camera_deg, reason: beta.perspective.reason })}`);
  expect(beta.perspective.applied).toBe(true);
  expect(beta.perspective.bolts_used).toBeGreaterThan(100);
  expect(beta.perspective.scale_change).toBeGreaterThan(1.1);
  await expect(page.getByTestId("perspective-note")).toHaveAttribute("data-applied", "yes");
  await expect(page.getByTestId("perspective-note")).toContainText("square grid");
  const uncorrected = await (await request.get(`/api/analyses/${runId}/candidate-beta?rectify=false`)).json();
  expect(uncorrected.perspective.applied).toBe(false);
  const editor = await page.context().newPage();
  await editor.goto(`/#/holds/${attemptId}`);
  await editor.getByRole("button", { name: /Open map/ }).click();
  await editor.getByTestId("grid-toggle").check();
  await expect(editor.getByTestId("grid-point").first()).toBeVisible({ timeout: 60_000 });
  expect(await editor.getByTestId("grid-point").count()).toBeGreaterThan(100);
  await editor.close();

  // Detailed view brings the evidence back, and the choice is remembered.
  await page.getByTestId("view-detailed").click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("view-simple").click();

  await page.setViewportSize({ width: 390, height: 800 });
  await expect(page.getByTestId("glance")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("heading", { name: "Saved attempts" })).toBeVisible();
});
