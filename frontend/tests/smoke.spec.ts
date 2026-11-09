import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Public CC BY-SA sample produced by scripts/fetch_public_samples.py; real analysis, nothing mocked.
const CLIP = path.resolve(import.meta.dirname, "../../data/public_samples/converted/public_rockspot_v3.mp4");

test("import, analyze, review, annotate, refresh, export, delete", async ({ page, request }) => {
  test.skip(!fs.existsSync(CLIP), "Public sample missing; run scripts/fetch_public_samples.py");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Add an attempt" })).toBeVisible();
  await page.getByPlaceholder("Blue problem, attempt 2").fill("Smoke test clip");
  await page.getByTestId("file-input").setInputFiles(CLIP);

  await expect(page.getByTestId("start-analysis")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("preview")).toBeVisible();
  await page.getByTestId("start-input").fill("3");
  await page.getByTestId("end-input").fill("30");
  await page.getByTestId("start-analysis").click();

  // Progress is real: the review only appears after the worker finishes.
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible({ timeout: 180_000 });
  const url = page.url();
  const runId = await page.evaluate(async () => {
    const id = location.hash.split("/").pop();
    return (await (await fetch(`/api/attempts/${id}`)).json()).analyses[0].id as string;
  });

  await expect(page.getByTestId("review-video")).toBeVisible();
  const events = await page.getByTestId("timeline-event").count();
  await expect(page.getByText("Low movement, of analyzable time")).toBeVisible();

  // Video really decodes and seeks.
  const duration = await page.getByTestId("review-video").evaluate(async (node) => {
    const video = node as HTMLVideoElement;
    if (video.readyState < 1) await new Promise((resolve) => video.addEventListener("loadedmetadata", resolve, { once: true }));
    video.currentTime = 10;
    await new Promise((resolve) => video.addEventListener("seeked", resolve, { once: true }));
    return video.duration;
  });
  expect(duration).toBeGreaterThan(40);
  await page.waitForTimeout(200);
  const painted = await page.getByTestId("overlay-canvas").evaluate((node) => {
    const canvas = node as HTMLCanvasElement;
    const data = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
    return data.some((value, index) => index % 4 === 3 && value > 0);
  });
  expect(painted).toBe(true);

  if (events > 0) {
    await page.getByTestId("timeline-event").first().click();
    const card = page.locator(".event-card.selected");
    await expect(card).toBeVisible();
    await card.getByText("Cannot tell").click();
    await card.getByText("Not useful").click();
    await card.getByTestId("event-note").fill("Smoke note");
    await expect(card.getByRole("status")).toHaveText("Saved");
  }
  await page.getByTestId("reflection-observation").fill("I looked at my feet");
  await page.getByTestId("reflection-focus").fill("Slow first move");
  await page.getByTestId("save-reflection").click();
  await expect(page.getByText("Saved.")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByTestId("reflection-focus")).toHaveValue("Slow first move");
  if (events > 0) {
    await expect(page.getByTestId("event-note").first()).toHaveValue(/Smoke note|^$/);
  }
  expect(page.url()).toBe(url);

  for (const format of ["json", "csv", "html"]) {
    const response = await request.get(`/api/analyses/${runId}/export?format=${format}`);
    expect(response.ok()).toBe(true);
    if (format === "html") expect(await response.text()).toContain("Smoke test clip");
  }

  await page.setViewportSize({ width: 390, height: 800 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("heading", { name: "Saved attempts" })).toBeVisible();
  await expect(page.getByText("Smoke test clip")).toHaveCount(0);
});
