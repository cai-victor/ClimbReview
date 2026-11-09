import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Hold, OverlaySample } from "./api";

const BONES: [string, string][] = [
  ["left_shoulder", "right_shoulder"], ["left_hip", "right_hip"], ["left_shoulder", "left_hip"], ["right_shoulder", "right_hip"],
  ["left_shoulder", "left_elbow"], ["left_elbow", "left_wrist"], ["right_shoulder", "right_elbow"], ["right_elbow", "right_wrist"],
  ["left_hip", "left_knee"], ["left_knee", "left_ankle"], ["right_hip", "right_knee"], ["right_knee", "right_ankle"],
  ["left_ankle", "left_foot_index"], ["right_ankle", "right_foot_index"],
  ["left_ankle", "left_heel"], ["right_ankle", "right_heel"], ["left_heel", "left_foot_index"], ["right_heel", "right_foot_index"],
];
export type Focus = "all" | "feet" | "hands";
const inFocus = (focus: Focus, name: string) =>
  focus === "all" || (focus === "feet" ? /(knee|ankle|heel|foot_index)$/.test(name) : /(shoulder|elbow|wrist)$/.test(name));
const FOOT_ANCHOR: [string, string][] = [["left_ankle", "L foot"], ["right_ankle", "R foot"]];
export interface Trail { points: { t: number; x: number; y: number }[]; side: "left" | "right" }
const COLOR = { left: "#f28c28", right: "#2ab7f5", center: "#ffffff" };
const side = (name: string) => (name.startsWith("left") ? COLOR.left : name.startsWith("right") ? COLOR.right : COLOR.center);
// A 10 Hz track: use a sample only if it is the nearest one to this moment; never hold it longer.
const MAX_SAMPLE_DISTANCE_MS = 60;

function nearest(samples: OverlaySample[], ms: number): OverlaySample | null {
  let low = 0, high = samples.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (samples[mid].t < ms) low = mid + 1; else high = mid;
  }
  const options = [samples[low], samples[low - 1]].filter(Boolean);
  options.sort((a, b) => Math.abs(a.t - ms) - Math.abs(b.t - ms));
  return options[0] && Math.abs(options[0].t - ms) <= MAX_SAMPLE_DISTANCE_MS ? options[0] : null;
}

export interface PlayerHandle { seek: (ms: number) => void; video: HTMLVideoElement | null }
interface Props {
  src: string; samples: OverlaySample[]; showSkeleton: boolean; onTime: (ms: number) => void;
  loop: { start: number; end: number } | null; focus?: Focus; trails?: Trail[]; holds?: Hold[]; marks?: Mark[];
}
export interface Mark { x: number; y: number; label: string }

export const Player = forwardRef<PlayerHandle, Props>(function Player({ src, samples, showSkeleton, onTime, loop, focus = "all", trails = [], holds = [], marks = [] }, ref) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [rate, setRate] = useState(1);
  const latest = useRef({ samples, showSkeleton, loop, onTime, focus, trails, holds, marks });
  latest.current = { samples, showSkeleton, loop, onTime, focus, trails, holds, marks };

  useImperativeHandle(ref, () => ({
    seek: (ms) => { if (video.current) video.current.currentTime = ms / 1000; },
    get video() { return video.current; },
  }), []);

  useEffect(() => { if (video.current) video.current.playbackRate = rate; }, [rate]);

  useEffect(() => {
    const element = video.current!, surface = canvas.current!;
    let frame = 0;

    const draw = () => {
      const { samples, showSkeleton, onTime, focus, trails, holds, marks } = latest.current;
      const ms = element.currentTime * 1000;
      onTime(ms);
      const dpr = window.devicePixelRatio || 1;
      const width = element.clientWidth, height = element.clientHeight;
      if (surface.width !== Math.round(width * dpr) || surface.height !== Math.round(height * dpr)) {
        surface.width = Math.round(width * dpr);
        surface.height = Math.round(height * dpr);
      }
      const context = surface.getContext("2d")!;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, surface.width, surface.height);
      surface.dataset.sampleT = "";
      if (!showSkeleton || !element.videoWidth) return;
      // The displayed picture is letterboxed inside the element; map onto its content rectangle.
      const scale = Math.min(width / element.videoWidth, height / element.videoHeight);
      const contentW = element.videoWidth * scale, contentH = element.videoHeight * scale;
      const offsetX = (width - contentW) / 2, offsetY = (height - contentH) / 2;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Marked holds appear only when the caller has verified that this reference frame lines up with the video.
      surface.dataset.holds = String(holds.length);
      holds.forEach((hold, index) => {
        const cx = offsetX + hold.x * contentW, cy = offsetY + hold.y * contentH;
        context.strokeStyle = hold.role === "start" ? "#2fbf71" : hold.role === "finish" ? "#e0245e" : "#ffc800";
        context.lineWidth = 2;
        context.beginPath(); context.arc(cx, cy, hold.radius * contentW, 0, Math.PI * 2); context.stroke();
        context.font = "600 11px system-ui, sans-serif"; context.fillStyle = "#fff"; context.fillText(String(index + 1), cx - 4, cy + 4);
      });
      surface.dataset.marks = String(marks.length);
      marks.forEach((mark) => {
        const cx = offsetX + mark.x * contentW, cy = offsetY + mark.y * contentH;
        context.strokeStyle = "#fff"; context.lineWidth = 3; context.setLineDash([4, 4]);
        context.beginPath(); context.arc(cx, cy, 13, 0, Math.PI * 2); context.stroke(); context.setLineDash([]);
        context.font = "600 12px system-ui, sans-serif"; context.lineWidth = 3; context.strokeStyle = "rgba(0,0,0,.8)"; context.strokeText(mark.label, cx + 16, cy + 4);
        context.fillStyle = "#fff"; context.fillText(mark.label, cx + 16, cy + 4);
      });
      const sample = samples.length ? nearest(samples, ms) : null;
      if (!sample) return;
      surface.dataset.sampleT = String(sample.t); // lets verification compare the drawn pose time with media time
      const at = (name: string): [number, number] | null => {
        const joint = sample.joints[name];
        return joint ? [offsetX + joint[0] * contentW, offsetY + joint[1] * contentH] : null;
      };
      context.lineWidth = 3;
      context.lineCap = "round";
      surface.dataset.focus = focus;
      let drawnTrail = 0;
      for (const trail of trails) {
        // The tracked point's path during the selected moment, drawn only up to the current time.
        const shown = trail.points.filter((point) => point.t <= ms);
        const place = (point: { x: number; y: number }): [number, number] => [offsetX + point.x * contentW, offsetY + point.y * contentH];
        drawnTrail += shown.length;
        context.strokeStyle = side(`${trail.side}_`);
        context.lineWidth = 4;
        context.setLineDash([2, 6]);
        context.beginPath();
        shown.forEach((point, index) => { const [x, y] = place(point); if (index) context.lineTo(x, y); else context.moveTo(x, y); });
        context.stroke();
        context.setLineDash([]);
        if (shown[0]) { const [x, y] = place(shown[0]); context.strokeStyle = "#fff"; context.lineWidth = 2; context.beginPath(); context.arc(x, y, 7, 0, Math.PI * 2); context.stroke(); }
        context.lineWidth = 3;
      }
      surface.dataset.trail = trails.length ? String(drawnTrail) : "";
      for (const [a, b] of BONES) {
        if (!inFocus(focus, a) || !inFocus(focus, b)) continue;
        const p = at(a), q = at(b);
        if (!p || !q) continue; // never draw across an unavailable joint
        context.strokeStyle = a.split("_")[0] === b.split("_")[0] ? side(a) : COLOR.center;
        context.beginPath(); context.moveTo(p[0], p[1]); context.lineTo(q[0], q[1]); context.stroke();
      }
      for (const name of Object.keys(sample.joints)) {
        if (!inFocus(focus, name)) continue;
        const p = at(name)!;
        context.fillStyle = side(name);
        context.beginPath(); context.arc(p[0], p[1], focus === "feet" ? 6 : 4, 0, Math.PI * 2); context.fill();
      }
      if (focus === "feet") {
        context.font = "600 13px system-ui, sans-serif";
        for (const [name, label] of FOOT_ANCHOR) {
          const p = at(name);
          if (!p) continue;
          context.lineWidth = 3; context.strokeStyle = "rgba(0,0,0,.75)"; context.strokeText(label, p[0] + 10, p[1] - 8);
          context.fillStyle = side(name); context.fillText(label, p[0] + 10, p[1] - 8);
        }
      }
    };

    // Event loops use the media element's own clock, so they also work if drawing is throttled.
    const onTimeUpdate = () => {
      const { loop } = latest.current;
      if (loop && !element.paused && element.currentTime * 1000 >= loop.end) element.currentTime = loop.start / 1000;
    };
    element.addEventListener("timeupdate", onTimeUpdate);
    const loopFrames = () => { draw(); frame = requestAnimationFrame(loopFrames); };
    frame = requestAnimationFrame(loopFrames);
    return () => { cancelAnimationFrame(frame); element.removeEventListener("timeupdate", onTimeUpdate); };
  }, []);

  return (
    <div className="player">
      <div className="stage">
        <video ref={video} src={src} controls playsInline preload="auto" data-testid="review-video" />
        <canvas ref={canvas} aria-hidden="true" data-testid="overlay-canvas" />
      </div>
      <div className="row tight">
        <span className="muted">Speed</span>
        {[0.5, 1].map((value) => (
          <button key={value} className={`button small ${rate === value ? "active" : ""}`} onClick={() => setRate(value)}>{value}×</button>
        ))}
      </div>
    </div>
  );
});
