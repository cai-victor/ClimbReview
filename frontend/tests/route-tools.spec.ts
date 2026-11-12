import { expect, test } from "@playwright/test";

// A drawn, synthetic wall photo. It exercises the real upload, worker, suggester, and planner; it is not a real climb.
const SPOTS = [[200, 900], [260, 700], [190, 500], [270, 300]];

test("photo: suggest holds by color, confirm, set scale, and plan with height and wingspan", async ({ page, request }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1280, height: 1100 });      // keeps the whole tall picture clickable
  await page.goto("/");
  const dataUrl = await page.evaluate((spots) => {
    const canvas = document.createElement("canvas");
    canvas.width = 480; canvas.height = 1000;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#e6e4e1"; context.fillRect(0, 0, 480, 1000);
    context.fillStyle = "#1e78c8";
    for (const [x, y] of spots) { context.beginPath(); context.arc(x, y, 16, 0, Math.PI * 2); context.fill(); }
    context.fillStyle = "#d22828"; context.beginPath(); context.arc(400, 600, 16, 0, Math.PI * 2); context.fill();
    return canvas.toDataURL("image/png");
  }, SPOTS);
  await page.getByPlaceholder("Blue problem, attempt 2").fill("Synthetic wall photo");
  await page.getByTestId("file-input").setInputFiles({ name: "wall.png", mimeType: "image/png", buffer: Buffer.from(dataUrl.split(",")[1], "base64") });
  await expect(page.getByTestId("photo-attempt")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("start-analysis")).toHaveCount(0);
  const attemptId = page.url().split("/").pop()!;

  // Planner asks for marks first instead of inventing anything.
  await page.getByTestId("photo-plan").click();
  await expect(page.getByTestId("planner-no-map")).toBeVisible();
  await page.goto(`/#/holds/${attemptId}`);
  await page.getByTestId("create-map").click();
  const svg = page.getByTestId("hold-svg");
  await expect(svg).toBeVisible();
  const clickAt = async (x: number, y: number) => {
    const point = await svg.evaluate((node, [px, py]) => {
      const s = node as SVGSVGElement;
      const p = new DOMPoint(px, py).matrixTransform(s.getScreenCTM()!);
      return { x: p.x, y: p.y };
    }, [x, y]);
    expect(point.y).toBeLessThan(1100);
    await page.mouse.click(point.x, point.y);
  };

  // Tapping bare wall is refused.
  await page.getByTestId("mode-suggest").click();
  await clickAt(40, 40);
  await expect(page.getByRole("alert")).toContainText("looks like wall");
  // Tapping a blue hold suggests the four blue ones, and adds nothing until confirmed.
  await clickAt(SPOTS[0][0], SPOTS[0][1]);
  await expect(page.getByTestId("hold-suggestion")).toHaveCount(4);
  await expect(page.getByTestId("hold-circle")).toHaveCount(0);
  await expect(page.getByTestId("suggest-note")).toContainText("not confirmed holds");
  await page.getByTestId("hold-suggestion").first().click();              // confirm one
  await expect(page.getByTestId("hold-circle")).toHaveCount(1);
  await page.getByTestId("accept-all").click();
  await expect(page.getByTestId("hold-circle")).toHaveCount(4);
  await expect(page.getByTestId("hold-suggestion")).toHaveCount(0);

  // A foothold added by hand, and roles set in the editor.
  await page.getByTestId("mode-add").click();
  await clickAt(180, 970);
  await expect(page.getByTestId("hold-circle")).toHaveCount(5);
  await page.getByTestId("hold-use").selectOption("foot");
  const map = (await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json())[0];
  const byHeight = [...map.holds].sort((a: { y: number }, b: { y: number }) => b.y - a.y);
  for (const [index, role, use] of [[1, "start", "both"], [2, "", "both"], [3, "", "both"], [4, "finish", "hand"]] as const) {
    const hold = byHeight[index];
    await request.put(`/api/hold-maps/${map.id}/holds/${hold.id}`, { data: { x: hold.x, y: hold.y, radius: hold.radius, route: "", hold_type: "", role, use } });
  }

  // Without a scale the planner says what is missing.
  await page.goto(`/#/plan/${attemptId}`);
  await page.getByTestId("body-height").fill("170");
  await page.getByTestId("body-wingspan").fill("172");
  await page.getByTestId("run-plan").click();
  await expect(page.getByTestId("plan-needs")).toContainText("scale");

  // Set the scale with two clicks: 800 px of this drawing stand for 320 cm.
  await page.goto(`/#/holds/${attemptId}`);
  await page.getByRole("button", { name: /Open map/ }).click();
  await expect(page.getByTestId("scale-status")).toContainText("No scale set");
  await page.getByTestId("mode-scale").click();
  await clickAt(440, 100);
  await clickAt(440, 900);
  await page.getByTestId("scale-cm").fill("320");
  await page.getByTestId("save-scale").click();
  await expect(page.getByTestId("scale-status")).toContainText("320 cm");
  const saved = (await (await request.get(`/api/hold-maps/${map.id}`)).json()).scale;
  expect(Math.abs((saved.y2 - saved.y1) * 1000 - 800)).toBeLessThan(6);    // clicks landed where intended on the letterboxed picture

  // Planning uses the entered measurements, which persist in this browser.
  await page.getByTestId("open-planner").click();
  await expect(page.getByTestId("body-height")).toHaveValue("170");
  await page.getByTestId("run-plan").click();
  await expect(page.getByTestId("plan-steps").getByRole("listitem").first()).toBeVisible();
  await expect(page.getByTestId("plan-body")).toContainText("arm 58.3 cm");
  await expect(page.getByText("average body proportions")).toBeVisible();
  await expect(page.getByTestId("beta-figure")).toBeVisible();
  // The drawn wall has no bolt holes, so the planner says it could not correct for the wall's angle.
  await expect(page.getByTestId("perspective-note")).toHaveAttribute("data-applied", "no");
  await expect(page.getByTestId("perspective-note")).toContainText("Too few bolt holes");

  // A much shorter climber gets a different, honest answer for the same marks.
  await page.getByTestId("body-height").fill("120");
  await page.getByTestId("body-wingspan").fill("110");
  await page.getByTestId("run-plan").click();
  await expect(page.getByTestId("plan-needs")).toContainText("No sequence");

  await page.setViewportSize({ width: 390, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
  await page.goto(`/#/attempt/${attemptId}`);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("heading", { name: "Saved attempts" })).toBeVisible();
});
