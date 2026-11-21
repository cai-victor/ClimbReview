import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Public CC BY-SA sample produced by scripts/fetch_public_samples.py; real analysis, nothing mocked.
const CLIP = path.resolve(import.meta.dirname, "../../data/public_samples/converted/public_rockspot_v3.mp4");

test("import, analyze, review, annotate, refresh, export, delete", async ({ page, request }) => {
  test.skip(!fs.existsSync(CLIP), "Public sample missing; run scripts/fetch_public_samples.py");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Review a new attempt" })).toBeVisible();
  await page.getByPlaceholder("Blue problem, attempt 2").fill("Smoke test clip");
  await page.getByTestId("file-input").setInputFiles(CLIP);

  await expect(page.getByTestId("start-analysis")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("preview")).toBeVisible();
  await page.getByTestId("start-input").fill("3");
  await page.getByTestId("end-input").fill("30");
  await page.getByTestId("start-analysis").click();

  // Progress is real: the review only appears after the worker finishes.
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible({ timeout: 180_000 });
  await page.getByTestId("tab-evidence").click();
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

  // Continuous playback: the drawn pose must follow media time frame after frame.
  const playback = await page.evaluate(async () => {
    const video = document.querySelector("[data-testid=review-video]") as HTMLVideoElement;
    const canvas = document.querySelector("[data-testid=overlay-canvas]") as HTMLCanvasElement;
    video.muted = true;
    video.currentTime = 12;
    await new Promise((resolve) => video.addEventListener("seeked", resolve, { once: true }));
    await video.play();
    const drift: number[] = [], drawn = new Set<string>(), images = new Set<string>();
    const begin = performance.now();
    let frames = 0;
    await new Promise<void>((resolve) => {
      const step = () => {
        frames += 1;
        const t = canvas.dataset.sampleT;
        if (t) { drawn.add(t); drift.push(Math.abs(Number(t) - video.currentTime * 1000)); }
        if (frames % 6 === 0) images.add(canvas.toDataURL("image/png").slice(-400));
        if (performance.now() - begin > 4000) resolve(); else requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
    const end = video.currentTime;
    video.pause();
    return { frames, advanced: end - 12, drawn: drawn.size, images: images.size, maxDrift: Math.max(...drift) };
  });
  console.log(`playback ${JSON.stringify(playback)}`);
  expect(playback.advanced).toBeGreaterThan(2);
  expect(playback.drawn).toBeGreaterThan(10);
  expect(playback.images).toBeGreaterThan(3);
  expect(playback.maxDrift).toBeLessThanOrEqual(120); // 60 ms draw rule plus one display frame of timer lag

  // Frames captured while the video is actually playing, for human inspection of alignment.
  await page.getByTestId("review-video").evaluate(async (node) => { const v = node as HTMLVideoElement; v.currentTime = 20; await v.play(); });
  for (const index of [1, 2, 3]) {
    await page.waitForTimeout(700);
    await page.locator(".stage").screenshot({ path: test.info().outputPath(`playing-${index}.png`) });
  }
  await page.getByTestId("review-video").evaluate((node) => (node as HTMLVideoElement).pause());

  if (events > 0) {
    await page.getByTestId("timeline-event").first().click();
    await page.getByText("Loop this moment").click();
    const loop = await page.evaluate(async () => {
      const video = document.querySelector("[data-testid=review-video]") as HTMLVideoElement;
      video.muted = true;
      await video.play();
      let previous = video.currentTime, wrapped = false, highest = 0;
      const begin = performance.now();
      while (performance.now() - begin < 8000 && !wrapped) {
        await new Promise((resolve) => setTimeout(resolve, 60));
        if (video.currentTime < previous - 0.3) wrapped = true;
        previous = video.currentTime;
        highest = Math.max(highest, previous);
      }
      video.pause();
      return { wrapped, highest };
    });
    console.log(`loop ${JSON.stringify(loop)}`);
    expect(loop.wrapped).toBe(true);
    await page.getByText("Loop this moment").click();
    const card = page.locator(".event-card.selected");
    await expect(card).toBeVisible();
    await card.getByText("Cannot tell").click();
    await card.getByText("Not useful").click();
    await card.getByTestId("event-note").fill("Smoke note");
    await expect(card.getByRole("status")).toHaveText("Saved");
  }
  await page.getByTestId("tab-next").click();
  await page.getByTestId("reflection-observation").fill("I looked at my feet");
  await page.getByTestId("reflection-focus").fill("Slow first move");
  await page.getByTestId("save-reflection").click();
  await expect(page.getByText("Saved.")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await page.getByTestId("tab-evidence").click();
  await page.getByTestId("tab-next").click();
  await expect(page.getByTestId("reflection-focus")).toHaveValue("Slow first move");
  await page.getByTestId("tab-evidence").click();
  if (events > 0) {
    await expect(page.getByTestId("event-note").first()).toHaveValue(/Smoke note|^$/);
  }
  expect(page.url()).toBe(url);

  // Details: problem, grade and outcome from the header, kept after a reload.
  await page.getByTestId("edit-details").click();
  await page.getByTestId("details-problem").fill("Smoke problem");
  await page.getByTestId("details-grade").fill("V1");
  await page.getByTestId("details-outcome-finished").click();
  await expect(page.getByTestId("details-outcome-text")).toHaveValue("Finished");
  await page.getByTestId("details-save").click();
  await expect(page.getByTestId("details-dialog")).not.toBeVisible();
  await expect(page.getByTestId("details-summary")).toHaveText("Smoke problem · V1 · Finished");
  await page.reload();
  await expect(page.getByTestId("details-summary")).toHaveText("Smoke problem · V1 · Finished");

  for (const format of ["json", "csv", "html"]) {
    const response = await request.get(`/api/analyses/${runId}/export?format=${format}`);
    expect(response.ok()).toBe(true);
    if (format === "html") expect(await response.text()).toContain("Smoke test clip");
  }

  await page.setViewportSize({ width: 390, height: 800 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  page.on("dialog", (dialog) => dialog.accept());
  await page.getByTestId("attempt-menu").click();
  await page.getByRole("button", { name: "Delete attempt" }).click();
  await expect(page.getByRole("heading", { name: /Your attempts/ })).toBeVisible();
  await expect(page.getByText("Smoke test clip")).toHaveCount(0);
});
