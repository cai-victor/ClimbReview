import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Real teammate tripod footage through the real worker; nothing here is mocked. The legacy step below
// rewrites this test's own run into the shape stored before foot analysis, inside the separate e2e data folder.
const CLIP = path.resolve(import.meta.dirname, "../../data/tripod_nov09/originals/IMG_4301.mov");
const DATA = path.resolve(import.meta.dirname, "../../data/e2e_app");

function makeLegacy(attemptId: string, runId: string) {
  const dir = path.join(DATA, "attempts", attemptId, "runs", runId);
  const FOOT = ["foot_motion_left", "foot_motion_right"];
  fs.rmSync(path.join(dir, "movement.json"));
  const result = JSON.parse(fs.readFileSync(path.join(dir, "result.json"), "utf8"));
  for (const key of FOOT) { delete result.coverage.detectors[key]; delete result.detection.detectors[key]; }
  result.detection.detector_version = "detectors-v1";
  fs.writeFileSync(path.join(dir, "result.json"), JSON.stringify(result));
  const events = JSON.parse(fs.readFileSync(path.join(dir, "events.json"), "utf8"));
  events.events = events.events.filter((e: { type: string }) => e.type !== "foot_motion")
    .map((e: { feedback: Record<string, string>; context?: unknown }) => { delete e.context; delete e.feedback.context; return e; });
  for (const key of FOOT) delete events.detectors[key];
  fs.writeFileSync(path.join(dir, "events.json"), JSON.stringify(events));
}

test("left and right feet: filtering, detail, seek, loop, persistence, exports, old runs", async ({ page, request }) => {
  test.skip(!fs.existsSync(CLIP), "Tripod footage is private and not present");
  test.setTimeout(420_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  await page.getByPlaceholder("Blue problem, attempt 2").fill("Footwork spec clip");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  await expect(page.getByTestId("start-analysis")).toBeVisible({ timeout: 120_000 });
  await page.getByTestId("start-analysis").click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible({ timeout: 180_000 });
  await page.getByTestId("tab-evidence").click();
  const attemptId = page.url().split("/").pop()!;
  const firstRun = (await (await request.get(`/api/attempts/${attemptId}`)).json()).analyses[0].id as string;

  // Rows and digest come from real analysis.
  for (const label of ["Left foot", "Right foot", "Left wrist", "Right wrist", "Low movement"]) await expect(page.locator(".track-label", { hasText: label })).toBeVisible();
  await expect(page.getByTestId("digest")).toContainText("What moved and when");
  await expect(page.getByTestId("digest")).toContainText("Worth rewatching");
  await expect(page.getByTestId("movement-chart")).toBeVisible();
  const allCards = await page.getByTestId("event-card").count();

  // Feet-only filter reduces rows, cards, and the overlay.
  await page.getByTestId("filter-feet").click();
  await expect(page.locator(".track")).toHaveCount(2);
  const footCards = await page.getByTestId("event-card").count();
  expect(footCards).toBeGreaterThan(3);
  expect(footCards).toBeLessThan(allCards);
  for (const title of await page.locator(".event-head strong").allTextContents()) expect(title).toMatch(/foot movement/);
  await expect(page.getByTestId("overlay-focus")).toHaveValue("feet");

  // Selecting one foot seeks, draws its path, shows the drill-down, and loops.
  const firstFoot = page.getByTestId("timeline-event").nth(2);
  await firstFoot.click();
  const card = page.locator(".event-card.selected");
  await expect(card).toContainText("ankle point");
  await expect(card.getByTestId("event-chart")).toBeVisible();
  await page.waitForTimeout(400);
  const seeked = await page.getByTestId("review-video").evaluate((node) => (node as HTMLVideoElement).currentTime);
  const window = await card.locator(".event-head span").textContent();
  const startSeconds = Number(window!.slice(0, 2)) * 60 + Number(window!.slice(3, 7));
  expect(Math.abs(seeked - Math.max(0, startSeconds - 1))).toBeLessThan(0.25);
  await page.getByTestId("review-video").evaluate(async (node) => { const v = node as HTMLVideoElement; v.currentTime += 1.5; await new Promise((r) => v.addEventListener("seeked", r, { once: true })); });
  await page.waitForTimeout(250);
  const overlay = await page.getByTestId("overlay-canvas").evaluate((node) => ({ focus: (node as HTMLCanvasElement).dataset.focus, trail: (node as HTMLCanvasElement).dataset.trail }));
  expect(overlay.focus).toBe("feet");
  expect(Number(overlay.trail)).toBeGreaterThan(0);
  await page.getByText("Loop this moment").click();
  const loop = await page.evaluate(async () => {
    const video = document.querySelector("[data-testid=review-video]") as HTMLVideoElement;
    video.muted = true; await video.play();
    let previous = video.currentTime, wrapped = false; const begin = performance.now();
    while (performance.now() - begin < 12_000 && !wrapped) { await new Promise((r) => setTimeout(r, 60)); if (video.currentTime < previous - 0.3) wrapped = true; previous = video.currentTime; }
    video.pause(); return wrapped;
  });
  expect(loop).toBe(true);
  await page.getByText("Loop this moment").click();

  // Filtering away a selected limb must also stop its hidden loop and trail.
  await page.getByTestId("filter-hands").click();
  await page.getByTestId("timeline-event").first().click();
  await page.getByLabel("Loop this moment", { exact: true }).check();
  await page.getByTestId("filter-feet").click();
  await expect(page.getByLabel("Loop this moment", { exact: true })).not.toBeChecked();
  await expect(page.getByLabel("Loop this moment", { exact: true })).toBeDisabled();
  await expect(page.locator(".event-card.selected")).toHaveCount(0);

  // Clicking the chart seeks to that time.
  await page.getByTestId("filter-all").click();
  await page.getByTestId("movement-chart").scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  const box = (await page.getByTestId("movement-chart").boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + 30);
  await page.waitForTimeout(300);
  const middle = await page.getByTestId("review-video").evaluate((node) => (node as HTMLVideoElement).currentTime);
  expect(Math.abs(middle - 26.6)).toBeLessThan(1);

  // A judgment on a foot event persists.
  await page.getByTestId("filter-feet").click();
  await page.getByTestId("timeline-event").first().click();
  const selected = page.locator(".event-card.selected");
  await selected.getByText("Cannot tell").click();
  await expect(selected.getByRole("status")).toHaveText("Saved");
  const noteSaved = page.waitForResponse((r) => r.url().includes("/review") && r.request().postData()!.includes("foot note"));
  await selected.getByTestId("event-note").fill("foot note");
  await noteSaved;
  await page.reload();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await page.getByTestId("tab-evidence").click();
  await page.getByTestId("filter-feet").click();
  await expect.poll(() => page.getByTestId("event-note").evaluateAll((nodes) => nodes.map((n) => (n as HTMLTextAreaElement).value))).toContain("foot note");

  // Exports carry foot events.
  const csv = await (await request.get(`/api/analyses/${firstRun}/export?format=csv`)).text();
  expect(csv).toContain("foot_motion"); expect(csv).toContain("left_foot"); expect(csv).toContain("foot note");
  const json = await (await request.get(`/api/analyses/${firstRun}/export?format=json`)).json();
  expect(json.summary.foot_analysis_available).toBe(true);
  expect(json.result.detection.detectors.foot_motion_left.event_count).toBeGreaterThan(0);
  const html = await (await request.get(`/api/analyses/${firstRun}/export?format=html`)).text();
  expect(html).toContain("Foot movement"); expect(html).toContain("What moved");

  // Phone width.
  await page.setViewportSize({ width: 390, height: 800 });
  await expect(page.getByTestId("movement-chart")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  await page.screenshot({ path: test.info().outputPath("phone.png"), fullPage: false });
  await page.setViewportSize({ width: 1280, height: 860 });

  // A run stored before foot analysis still opens, says what it lacks, and keeps its notes after reanalysis.
  makeLegacy(attemptId, firstRun);
  await page.reload();
  await expect(page.getByTestId("old-run-notice")).toBeVisible();
  await expect(page.locator(".track-label", { hasText: "Left foot" })).toHaveCount(0);
  await expect(page.getByTestId("digest")).toHaveCount(0);
  await page.getByTestId("tab-evidence").click();
  const wristCard = page.getByTestId("event-card").first();
  const oldSaved = page.waitForResponse((r) => r.url().includes("/review") && r.request().postData()!.includes("old run note"));
  await wristCard.getByTestId("event-note").fill("old run note");
  await oldSaved;
  await page.getByTestId("tab-moments").click();
  await page.getByTestId("reanalyze-feet").click();
  await page.getByTestId("start-analysis").click();
  await expect(page.getByTestId("run-picker")).toBeVisible({ timeout: 180_000 });
  await page.getByTestId("tab-evidence").click();
  await expect(page.locator(".track-label", { hasText: "Left foot" })).toBeVisible();
  await page.getByTestId("run-picker").selectOption(firstRun);
  await expect(page.getByTestId("old-run-notice")).toBeVisible();
  await page.getByTestId("tab-evidence").click();
  await expect(page.getByTestId("event-note").first()).toHaveValue("old run note");

  expect(errors).toEqual([]);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByTestId("attempt-menu").click();
  await page.getByRole("button", { name: "Delete attempt" }).click();
  await expect(page.getByRole("heading", { name: /Your attempts/ })).toBeVisible();
});
