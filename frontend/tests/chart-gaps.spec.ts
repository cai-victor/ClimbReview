import { expect, test } from "@playwright/test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { EventChart, runPaths, untracked } from "../src/MovementChart";
import type { ClimbEvent, LimbSeries, Movement } from "../src/api";

test("a missing speed sample breaks the plotted line even inside one run", () => {
  const paths = runPaths([0, 100, 200, 300, 400], [0, 1, null, 1, 0], [0, 0, 0, 0, 0], t => t, v => v);
  expect(paths).toHaveLength(2);
  expect(paths[0]).toBe("M0.0 0.0L100.0 1.0");
  expect(paths[1]).toBe("M300.0 1.0L400.0 0.0");
});

test("a blocked interval is marked unavailable even with valid endpoint joints", () => {
  const series = { x: [.1, .1, .2, .2], y: [.5, .5, .5, .5], speed_L_per_s: [0, 0, 0, 0], run: [0, 0, 1, 1] } as LimbSeries;
  expect(untracked([0, 100, 200, 300], series, t => t)).toEqual([{ x: 100, w: 100 }]);
});

test("event displacement excludes a later camera/tracking run", () => {
  const series: LimbSeries = { detector: "foot_motion_right", anchor: "right_ankle", x: [.1, .1, .2, .9, .9],
    y: [.5, .5, .5, .5, .5], speed_L_per_s: [0, 1, 1, 0, 0], run: [0, 0, 0, 1, 1] };
  const movement = { available: true, width: 100, height: 100, L_px: 100, t: [0, 100, 200, 300, 400],
    limbs: { left_foot: series, right_foot: series, left_wrist: series, right_wrist: series } } as Extract<Movement, { available: true }>;
  const event = { id: "synthetic-foot", type: "foot_motion", hand: "right", start_ms: 100, end_ms: 200 } as ClimbEvent;
  const svg = renderToStaticMarkup(createElement(EventChart, { movement, event, time: 100, onSeek: () => {} }));
  // The 0.8 L jump belongs to a different camera coordinate frame. The
  // event plot retains its small local scale and explicitly marks the gap.
  expect(svg).toContain("reaching 0.30 torso lengths");
  expect(svg).toContain('class="event-chart-gap"');
  expect(svg.match(/<path /g)).toHaveLength(1);
});
