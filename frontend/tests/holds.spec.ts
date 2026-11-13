import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Public samples: portrait (204x360) and landscape (1280x720); both letterboxed in a fixed stage.
const CLIPS = ["public_rockspot_v3.mp4", "public_khazanov_v3.mp4"].map((n) => path.resolve(import.meta.dirname, "../../data/public_samples/converted", n));

for (const clip of CLIPS) {
  test(`hold coordinates align and persist: ${path.basename(clip)}`, async ({ page, request }) => {
    test.skip(!fs.existsSync(clip), "Public sample missing");
    await page.goto("/");
    await page.getByPlaceholder("Blue problem, attempt 2").fill("Hold fixture");
    await page.getByTestId("file-input").setInputFiles(clip);
    await expect(page.getByTestId("start-analysis")).toBeVisible({ timeout: 120_000 });
    const id = await page.evaluate(() => location.hash.split("/").pop()!);
    await page.goto(`/#/holds/${id}`);
    await page.getByTestId("map-frame").fill("2");
    await page.getByTestId("create-map").click();
    await expect(page.getByTestId("hold-svg")).toBeVisible();

    // Compute where the image content lies in the letterboxed stage, independently of the SVG.
    const geometry = await page.getByTestId("hold-image").evaluate((node) => {
      const img = node as HTMLImageElement, box = img.getBoundingClientRect();
      const scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight);
      const w = img.naturalWidth * scale, h = img.naturalHeight * scale;
      return { left: box.left + (box.width - w) / 2, top: box.top + (box.height - h) / 2, w, h, natural: [img.naturalWidth, img.naturalHeight] };
    });
    await page.getByTestId("route-input").fill("blue");
    const target = { x: 0.25, y: 0.75 };
    await page.mouse.click(geometry.left + geometry.w * target.x, geometry.top + geometry.h * target.y);
    await expect(page.getByTestId("hold-circle")).toHaveCount(1);

    // A click on the letterbox band must not create a hold.
    const stage = await page.getByTestId("hold-stage").boundingBox();
    if (geometry.left - stage!.x > 10) {
      await page.mouse.click(stage!.x + 4, stage!.y + stage!.height / 2);
      await page.waitForTimeout(200);
      await expect(page.getByTestId("hold-circle")).toHaveCount(1);
    }

    // An accidental mark can be undone, and the editor says when the change is saved.
    await page.mouse.click(geometry.left + geometry.w * 0.6, geometry.top + geometry.h * 0.4);
    await expect(page.getByTestId("hold-circle")).toHaveCount(2);
    await page.getByTestId("undo-hold").click();
    await expect(page.getByTestId("hold-circle")).toHaveCount(1);
    await expect(page.getByTestId("save-state")).toHaveText("All changes saved");
    await expect(page.getByTestId("mode-hint")).toContainText("Adding holds");
    await page.evaluate(() => window.scrollTo(0, 0));     // the measured picture position below is for the unscrolled page

    const maps = await (await request.get(`/api/attempts/${id}/hold-maps`)).json();
    expect(maps[0].holds[0].x).toBeCloseTo(target.x, 2);
    expect(maps[0].holds[0].y).toBeCloseTo(target.y, 2);
    expect(maps[0].holds[0].route).toBe("blue");
    expect([maps[0].width, maps[0].height]).toEqual(geometry.natural);

    // The drawn circle lies where the content calculation says it should.
    const circle = await page.getByTestId("hold-circle").boundingBox();
    expect(Math.abs(circle!.x + circle!.width / 2 - (geometry.left + geometry.w * target.x))).toBeLessThan(1.5);
    expect(Math.abs(circle!.y + circle!.height / 2 - (geometry.top + geometry.h * target.y))).toBeLessThan(1.5);

    // Keyboard nudge, then persistence after reload.
    await page.getByTestId("hold-circle").focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(async () => (await (await request.get(`/api/hold-maps/${maps[0].id}`)).json()).holds[0].x).toBeCloseTo(maps[0].holds[0].x + 0.005, 6);
    await page.reload();
    await page.getByRole("button", { name: `Open map Route 1` }).click();
    await expect(page.getByTestId("hold-circle")).toHaveCount(1);
    await page.getByTestId("hold-circle").focus();
    await page.keyboard.press("Delete");
    await expect(page.getByTestId("hold-circle")).toHaveCount(0);

    expect((await request.delete(`/api/attempts/${id}`)).status()).toBe(204);
  });
}
