import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { OverlaySample } from "./api";

const BONES: [string, string][] = [
  ["left_shoulder", "right_shoulder"], ["left_hip", "right_hip"], ["left_shoulder", "left_hip"], ["right_shoulder", "right_hip"],
  ["left_shoulder", "left_elbow"], ["left_elbow", "left_wrist"], ["right_shoulder", "right_elbow"], ["right_elbow", "right_wrist"],
  ["left_hip", "left_knee"], ["left_knee", "left_ankle"], ["right_hip", "right_knee"], ["right_knee", "right_ankle"],
  ["left_ankle", "left_foot_index"], ["right_ankle", "right_foot_index"],
];
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
  loop: { start: number; end: number } | null;
}

export const Player = forwardRef<PlayerHandle, Props>(function Player({ src, samples, showSkeleton, onTime, loop }, ref) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [rate, setRate] = useState(1);
  const latest = useRef({ samples, showSkeleton, loop, onTime });
  latest.current = { samples, showSkeleton, loop, onTime };

  useImperativeHandle(ref, () => ({
    seek: (ms) => { if (video.current) video.current.currentTime = ms / 1000; },
    get video() { return video.current; },
  }), []);

  useEffect(() => { if (video.current) video.current.playbackRate = rate; }, [rate]);

  useEffect(() => {
    const element = video.current!, surface = canvas.current!;
    let frame = 0;

    const draw = () => {
      const { samples, showSkeleton, loop, onTime } = latest.current;
      const ms = element.currentTime * 1000;
      onTime(ms);
      if (loop && ms >= loop.end && !element.paused) element.currentTime = loop.start / 1000;
      const dpr = window.devicePixelRatio || 1;
      const width = element.clientWidth, height = element.clientHeight;
      if (surface.width !== Math.round(width * dpr) || surface.height !== Math.round(height * dpr)) {
        surface.width = Math.round(width * dpr);
        surface.height = Math.round(height * dpr);
      }
      const context = surface.getContext("2d")!;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, surface.width, surface.height);
      if (!showSkeleton || !element.videoWidth) return;
      // The displayed picture is letterboxed inside the element; map onto its content rectangle.
      const scale = Math.min(width / element.videoWidth, height / element.videoHeight);
      const contentW = element.videoWidth * scale, contentH = element.videoHeight * scale;
      const offsetX = (width - contentW) / 2, offsetY = (height - contentH) / 2;
      const sample = samples.length ? nearest(samples, ms) : null;
      if (!sample) return;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      const at = (name: string): [number, number] | null => {
        const joint = sample.joints[name];
        return joint ? [offsetX + joint[0] * contentW, offsetY + joint[1] * contentH] : null;
      };
      context.lineWidth = 3;
      context.lineCap = "round";
      for (const [a, b] of BONES) {
        const p = at(a), q = at(b);
        if (!p || !q) continue; // never draw across an unavailable joint
        context.strokeStyle = a.split("_")[0] === b.split("_")[0] ? side(a) : COLOR.center;
        context.beginPath(); context.moveTo(p[0], p[1]); context.lineTo(q[0], q[1]); context.stroke();
      }
      for (const name of Object.keys(sample.joints)) {
        const p = at(name)!;
        context.fillStyle = side(name);
        context.beginPath(); context.arc(p[0], p[1], 4, 0, Math.PI * 2); context.fill();
      }
    };

    const loopFrames = () => { draw(); frame = requestAnimationFrame(loopFrames); };
    frame = requestAnimationFrame(loopFrames);
    return () => cancelAnimationFrame(frame);
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
