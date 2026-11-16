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
  // Looking for a color is one click. The next click adds a hold by hand and the outlines stay, and Ctrl+Z takes the hold back.
  await expect(page.getByTestId("mode-add")).toHaveAttribute("aria-pressed", "true");
  await clickAt(40, 40);
  await expect(page.getByTestId("hold-circle")).toHaveCount(1);
  await expect(page.getByTestId("hold-suggestion")).toHaveCount(4);
  await page.keyboard.press("Control+z");
  await expect(page.getByTestId("hold-circle")).toHaveCount(0);
  await expect(page.getByTestId("hold-suggestion")).toHaveCount(4);
  await page.getByTestId("hold-suggestion").first().click();              // confirm one
  await expect(page.getByTestId("hold-circle")).toHaveCount(1);
  await page.getByTestId("accept-all").click();
  await expect(page.getByTestId("hold-circle")).toHaveCount(4);
  await expect(page.getByTestId("hold-suggestion")).toHaveCount(0);
  await expect(page.getByTestId("undo-hold")).toHaveText("Undo adding 3 holds");      // a batch is one undo

  // A foothold added by hand, and roles set in the editor.
  await page.getByTestId("mode-add").click();
  await clickAt(180, 970);
  await expect(page.getByTestId("hold-circle")).toHaveCount(5);
  await page.getByTestId("hold-use-foot").click();
  await expect(page.getByTestId("hold-use-foot")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("hold-pull")).toHaveCount(0);                 // a foothold has no pull direction
  await expect(page.getByTestId("save-state")).toHaveText("All changes saved");

  // Zooming in keeps clicks on target, and a hold can be dragged to a new place and resized by its handle.
  await page.getByTestId("zoom-in").click();
  await page.getByTestId("zoom-in").click();
  await expect(page.getByTestId("zoom-level")).toHaveText("200%");
  await page.waitForTimeout(150);                                            // the view re-centers one frame after the zoom changes
  const before = (await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json())[0].holds[4];
  const grab = await svg.evaluate((node, [px, py]) => {
    const s = node as SVGSVGElement, p = new DOMPoint(px, py).matrixTransform(s.getScreenCTM()!);
    (document.querySelector('[data-testid="hold-stage"]') as HTMLElement).scrollTo({ left: 0, top: 1e6 });
    const q = new DOMPoint(px, py).matrixTransform(s.getScreenCTM()!);
    return { x: q.x, y: q.y, moved: p.y - q.y };
  }, [before.x * 480, before.y * 1000]);
  await page.mouse.move(grab.x, grab.y);
  await page.mouse.down();
  await page.mouse.move(grab.x + 30, grab.y - 20, { steps: 4 });
  await page.mouse.up();
  await expect.poll(async () => (await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json())[0].holds[4].x).toBeGreaterThan(before.x + 0.01);
  const moved = (await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json())[0].holds[4];
  expect(moved.y).toBeLessThan(before.y - 0.005);
  expect(moved.radius).toBeCloseTo(before.radius, 6);
  await expect(page.getByTestId("hold-circle")).toHaveCount(5);              // dragging did not add a hold
  const handle = (await page.getByTestId("hold-handle").boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2 + 24, handle.y + handle.height / 2, { steps: 3 });
  await page.mouse.up();
  await expect.poll(async () => (await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json())[0].holds[4].radius).toBeGreaterThan(moved.radius * 1.2);
  await page.getByTestId("zoom-reset").click();
  await expect(page.getByTestId("zoom-level")).toHaveText("100%");

  // One click sets a role, the highest hold is offered as the finish, and a top out needs no finish hold.
  await expect(page.getByTestId("finish-proposal")).toContainText("highest mark");
  await page.getByTestId("propose-top").click();
  await expect(page.getByTestId("finish-proposal")).toHaveCount(0);
  await expect(page.locator('[data-testid="hold-circle"][data-role="finish"]')).toHaveCount(1);
  await page.locator('[data-testid="hold-circle"][data-role="finish"]').focus();
  await expect(page.getByTestId("hold-role-top")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("hold-pull-left").click();
  await expect(page.getByTestId("pull-arrow")).toHaveCount(1);
  await page.keyboard.press("Tab");
  await page.locator('[data-testid="hold-circle"][data-role="finish"]').focus();
  await page.keyboard.press("m");                                            // keyboard: back to a middle hold
  await expect(page.locator('[data-testid="hold-circle"][data-role="finish"]')).toHaveCount(0);
  await expect(page.getByTestId("marking-tips")).toContainText("Volumes");
  const map = (await (await request.get(`/api/attempts/${attemptId}/hold-maps`)).json())[0];
  const byHeight = [...map.holds].sort((a: { y: number }, b: { y: number }) => b.y - a.y);
  for (const [index, role, use] of [[1, "start", "both"], [2, "", "both"], [3, "", "both"], [4, "finish", "hand"]] as const) {
    const hold = byHeight[index];
    await request.put(`/api/hold-maps/${map.id}/holds/${hold.id}`, { data: { x: hold.x, y: hold.y, radius: hold.radius, route: "", hold_type: "", role, use, pull: "" } });
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
  await expect(page.getByTestId("plan-body")).toContainText("arm 58 cm");

  // The sketch climber is drawn on the holds, can be stepped and played, and hands and feet have their own colors.
  await expect(page.getByTestId("beta-stick")).toBeVisible();
  await expect(page.getByTestId("plan-legend")).toContainText("Hands");
  await expect(page.getByTestId("beta-figure")).toHaveAttribute("data-position", "0");
  await page.getByTestId("plan-next").click();
  await expect(page.getByTestId("beta-figure")).toHaveAttribute("data-position", "1");
  await page.getByTestId("plan-play").click();
  await expect(page.getByTestId("beta-figure")).not.toHaveAttribute("data-position", "1", { timeout: 5000 });
  await page.getByTestId("plan-prev").click();

  // Measurements can be entered in feet and inches; the same person gets the same reach lengths.
  await page.getByTestId("unit-in").click();
  await expect(page.getByTestId("body-height-ft")).toHaveValue("5");
  await expect(page.getByTestId("body-height-in")).toHaveValue("7");
  await page.getByTestId("run-plan").click();
  await expect(page.getByTestId("plan-body")).toContainText("arm 2");
  await expect(page.getByTestId("plan-body")).toContainText(" in");
  await page.getByTestId("unit-cm").click();
  await expect(page.getByTestId("body-height")).toHaveValue("170");
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
  await page.getByTestId("attempt-menu").click();
  await page.getByRole("button", { name: "Delete attempt" }).click();
  await expect(page.getByRole("heading", { name: /Your attempts/ })).toBeVisible();
});
