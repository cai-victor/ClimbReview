import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Blind labeling workflow on a public sample. Intervals here are synthetic test data.
const CLIP = path.resolve(import.meta.dirname, "../../data/public_samples/converted/public_rockspot_v3.mp4");

test("blind labeling: create, edit, reload, delete, export without model data", async ({ page, request }) => {
  test.skip(!fs.existsSync(CLIP), "Public sample missing");
  const modelRequests: string[] = [];
  page.on("request", (r) => { if (/\/(poses|events)|\/analyses/.test(new URL(r.url()).pathname) && r.url().includes("/api/")) modelRequests.push(r.url()); });

  await page.goto("/");
  await page.getByPlaceholder("Blue problem, attempt 2").fill("Annotation fixture");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  await expect(page.getByTestId("start-analysis")).toBeVisible({ timeout: 120_000 });
  const id = await page.evaluate(() => location.hash.split("/").pop()!);
  modelRequests.length = 0; // the attempt page itself does not fetch model data before analysis

  await page.goto(`/#/annotate/${id}`);
  await expect(page.getByRole("heading", { name: /Reference labeling/ })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Blind mode");
  await page.getByTestId("rater-alias").fill("synthetic_rater");
  await page.getByTestId("synthetic-flag").check();
  await page.getByTestId("create-set").click();

  const add = async (kind: string, start: string, end: string) => {
    await page.getByTestId("interval-kind").selectOption(kind);
    await page.getByTestId("interval-start").fill(start);
    await page.getByTestId("interval-end").fill(end);
    await page.getByTestId("save-interval").click();
  };
  await add("low_movement", "2", "3");            // too short
  await expect(page.getByRole("alert")).toContainText("at least 2");
  await add("low_movement", "2", "5");
  await expect(page.getByTestId("interval-list").getByRole("listitem")).toHaveCount(1);
  await add("wrist_left", "6", "6.5");
  await expect(page.getByTestId("interval-list").getByRole("listitem")).toHaveCount(2);
  await add("foot_right", "7", "7.6");
  await expect(page.getByTestId("interval-list").getByRole("listitem")).toHaveCount(3);
  await expect(page.getByTestId("interval-list")).toContainText("Right foot movement");
  await page.getByTestId("interval-kind").selectOption("unscorable");
  await page.getByTestId("interval-start").fill("8");
  await page.getByTestId("interval-end").fill("9");
  await page.getByRole("checkbox", { name: "All" }).check();
  await page.getByTestId("save-interval").click();
  await expect(page.getByTestId("interval-list").getByRole("listitem")).toHaveCount(4);

  await page.getByRole("button", { name: "Edit interval at 00:02.0" }).click();
  await page.getByTestId("interval-end").fill("5.5");
  await page.getByTestId("save-interval").click();
  await expect(page.getByTestId("interval-list")).toContainText("00:05.5");
  await page.getByRole("button", { name: "Delete interval at 00:06.0" }).click();
  await expect(page.getByTestId("interval-list").getByRole("listitem")).toHaveCount(3);

  // Keyboard marks.
  await page.getByTestId("annotate-video").evaluate(async (node) => { const v = node as HTMLVideoElement; v.currentTime = 11; await new Promise((r) => v.addEventListener("seeked", r, { once: true })); });
  await page.locator("h3", { hasText: "Intervals" }).click();
  await page.keyboard.press("[");
  await expect(page.getByTestId("interval-start")).toHaveValue("11.00");

  await page.reload();
  await page.getByRole("button", { name: "Open set synthetic_rater" }).click();
  await expect(page.getByTestId("interval-list").getByRole("listitem")).toHaveCount(3);

  const sets = await (await request.get(`/api/attempts/${id}/annotation-sets`)).json();
  const csv = await (await request.get(`/api/annotation-sets/${sets[0].id}/export?format=csv`)).text();
  expect(csv).toContain("low_movement");
  expect(await (await request.get(`/api/attempts/${id}/annotations/export`)).text()).not.toContain("synthetic_rater");
  expect(modelRequests).toEqual([]);

  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(`/#/attempt/${id}`);
  await page.getByTestId("attempt-menu").click();
  await page.getByRole("button", { name: "Delete attempt" }).click();
  await expect(page.getByRole("heading", { name: /Your attempts/ })).toBeVisible();
});

test("import Cancel button stops the import", async ({ page, request }) => {
  test.skip(!fs.existsSync(CLIP), "Public sample missing");
  await page.goto("/");
  await page.getByPlaceholder("Blue problem, attempt 2").fill("Cancel fixture");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  const cancel = page.getByTestId("cancel-job");
  await cancel.waitFor({ timeout: 30_000 });
  await cancel.click();
  await expect(page.getByRole("alert")).toContainText("cancelled", { timeout: 30_000 });
  await page.getByRole("button", { name: "Retry import" }).click();
  await expect(page.getByTestId("start-analysis")).toBeVisible({ timeout: 120_000 });
  const id = await page.evaluate(() => location.hash.split("/").pop()!);
  expect((await request.delete(`/api/attempts/${id}`)).status()).toBe(204);
});
