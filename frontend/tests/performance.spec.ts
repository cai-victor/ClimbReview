import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Real tripod footage and real analysis. Hold marks and comparison labels below are test fixtures in the separate e2e folder.
const CLIP = path.resolve(import.meta.dirname, "../../data/tripod_nov09/originals/IMG_4301.mov");

async function importAndAnalyze(page: import("@playwright/test").Page, title: string) {
  await page.goto("/");
  await page.getByPlaceholder("Blue problem, attempt 2").fill(title);
  await page.getByTestId("file-input").setInputFiles(CLIP);
  await expect(page.getByTestId("start-analysis")).toBeVisible({ timeout: 120_000 });
  await page.getByTestId("start-analysis").click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible({ timeout: 180_000 });
  return page.url().split("/").pop()!;
}

test("coaching cards, placements, candidate beta, and matched comparison", async ({ page, request }) => {
  test.skip(!fs.existsSync(CLIP), "Tripod footage is private and not present");
  test.setTimeout(420_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const attemptId = await importAndAnalyze(page, "Performance spec A");
  const runId = (await (await request.get(`/api/attempts/${attemptId}`)).json()).analyses[0].id as string;

  // Coaching is the first thing in the side panel and comes from real measurements.
  await expect(page.getByRole("heading", { name: /Performance opportunities \(\d+\)/ })).toBeVisible();
  const cards = page.getByTestId("cue-card");
  expect(await cards.count()).toBeGreaterThan(0);
  await expect(cards.first()).toContainText("Hypothesis to test");
  await expect(cards.first()).toContainText("Try this");
  await expect(cards.first()).toContainText("Keep your way if");
  await expect(page.getByTestId("not-flagged")).toBeVisible();
  await expect(page.getByTestId("cannot-evaluate")).toBeVisible();
  await expect(page.getByTestId("next-attempt")).toContainText("Suggested first");

  // Forbidden claims must not appear anywhere in the coaching payload's advice text.
  const coaching = await (await request.get(`/api/analyses/${runId}/coaching`)).json();
  const advice = coaching.cards.map((c: { title: string; moment: string; try_this: string; why: string }) => `${c.title} ${c.moment} ${c.try_this} ${c.why}`).join(" ").toLowerCase();
  for (const word of ["score", "injur", "optimal", "fatigue", "best beta", "center of mass"]) expect(advice).not.toContain(word);

  // Opening a card seeks to its moment, draws evidence, and can loop.
  const first = cards.first();
  const timeText = await first.locator(".cue-head span").textContent();
  const startSeconds = Number(timeText!.slice(0, 2)) * 60 + Number(timeText!.slice(3, 7));
  await first.getByTestId("cue-open").click();
  await page.waitForTimeout(400);
  const seeked = await page.getByTestId("review-video").evaluate((n) => (n as HTMLVideoElement).currentTime);
  expect(Math.abs(seeked - Math.max(0, startSeconds - 1))).toBeLessThan(0.25);
  await expect(page.getByLabel("Loop selected event (±1 s)", { exact: true })).toBeEnabled();

  // Decisions and results persist.
  await first.getByTestId("cue-will_try").click();
  await expect(page.getByTestId("next-attempt")).not.toContainText("Suggested first");
  await page.locator(".cue-card").first().getByTestId("cue-outcome-helped").click();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByTestId("next-attempt")).toContainText("Your result: helped");

  // A placement can be confirmed only by the climber; nothing is pre-filled as contact.
  const placements = page.getByTestId("placement");
  expect(await placements.count()).toBeGreaterThan(0);
  expect(await page.locator('[data-testid="foot-placements"] [aria-pressed="true"]').count()).toBe(0);
  await placements.first().getByTestId("placement-seek").click();
  await page.waitForTimeout(300);
  expect(await page.getByTestId("overlay-canvas").evaluate((n) => (n as HTMLCanvasElement).dataset.marks)).toBe("1");
  await placements.first().getByTestId("placement-intentional_smear").click();
  await expect(placements.first().getByTestId("placement-intentional_smear")).toHaveAttribute("aria-pressed", "true");

  // With no marks there is a setup action, not an invented route.
  await expect(page.getByTestId("beta-needs")).toContainText("Mark the holds");
  await expect(page.getByTestId("beta-setup")).toBeVisible();

  // Test-fixture route on the real video's reference frame.
  const map = await (await request.post(`/api/attempts/${attemptId}/hold-maps`, { data: { name: "Fixture route", reference_frame_ms: 200 } })).json();
  const marks = [[0.08, 0.62, "start", "hand"], [0.2, 0.60, "start", "hand"], [0.1, 0.78, "", "foot"], [0.2, 0.76, "", "foot"], [0.16, 0.68, "", "both"], [0.24, 0.66, "", "foot"],
    [0.16, 0.54, "", "hand"], [0.2, 0.48, "finish", "hand"]] as const;
  for (const [x, y, role, use] of marks) await request.post(`/api/hold-maps/${map.id}/holds`, { data: { x, y, radius: 0.035, route: "fixture", hold_type: "", role, use } });
  // The editor shows a wall picture combined from the real video, with the tracked climber cut out.
  const wall = await (await request.get(`/api/hold-maps/${map.id}/wall-info`)).json();
  console.log(`wall ${JSON.stringify(wall)}`);
  expect(wall.basis).toBe("clean_wall_pose_masked");
  expect(wall.frames_used).toBeGreaterThanOrEqual(5);
  const editor = await page.context().newPage();
  await editor.goto(`/#/holds/${attemptId}`);
  await editor.getByRole("button", { name: /Open map/ }).click();
  await expect(editor.getByTestId("wall-toggle")).toBeChecked({ timeout: 30_000 });
  await expect(editor.getByTestId("hold-image")).toHaveAttribute("src", /wall-image/);
  expect(await editor.getByTestId("hold-image").evaluate((n) => (n as HTMLImageElement).naturalWidth)).toBe(720);
  await editor.getByTestId("wall-toggle").uncheck();
  await expect(editor.getByTestId("hold-image")).toHaveAttribute("src", /frame\?ms=/);
  await editor.close();
  await page.reload();
  await expect(page.getByTestId("beta-figure")).toBeVisible({ timeout: 60_000 });     // the first request builds the wall picture and fits its bolt grid
  await expect(page.getByTestId("beta-steps").getByRole("listitem").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("beta-panel")).toContainText("none is the best");
  expect(await page.getByTestId("beta-candidate").count()).toBeGreaterThan(0);
  const alignment = (await (await request.get(`/api/analyses/${runId}/coaching`)).json()).hold_map.alignment;
  console.log(`alignment ${JSON.stringify(alignment)}`);
  expect(alignment.status).toBe("fixed_verified");
  await page.waitForTimeout(500);
  expect(Number(await page.getByTestId("overlay-canvas").evaluate((n) => (n as HTMLCanvasElement).dataset.holds))).toBe(marks.length);

  // Comparison needs explicit matching labels.
  await expect(page.getByTestId("compare-panel")).toContainText("Add a problem and climber name");
  await page.getByTestId("problem-label").fill("Spec Problem");
  await page.getByTestId("climber-label").fill("A");
  await page.getByTestId("outcome-label").fill("Topped");
  await page.getByTestId("save-compare").click();
  await expect(page.getByTestId("compare-none")).toBeVisible();
  const other = await importAndAnalyze(page, "Performance spec B");
  await request.patch(`/api/attempts/${other}`, { data: { problem_label: "spec  problem", climber_label: "B" } });
  await page.reload();
  await expect(page.getByTestId("compare-none")).toBeVisible();     // a different climber is never matched
  await request.patch(`/api/attempts/${other}`, { data: { climber_label: "a", outcome: "Fell" } });
  await page.reload();
  await expect(page.getByTestId("compare-table")).toContainText("Fell");
  await expect(page.getByTestId("compare-table")).toContainText("Topped");

  await page.setViewportSize({ width: 390, height: 800 });
  await expect(page.getByTestId("cue-card").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);

  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("heading", { name: "Saved attempts" })).toBeVisible();
  await page.goto(`/#/attempt/${attemptId}`);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("heading", { name: "Saved attempts" })).toBeVisible();
});
